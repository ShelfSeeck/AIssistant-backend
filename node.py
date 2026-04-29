"""node.py - 状态机节点函数集合。

每个节点函数通过 @register_node 注册，签名统一为:
    async def xxx_node(ctx: LoopContext) -> NodeOutput

节点函数只执行业务逻辑，不控制流程去向 —— 流程由 loop.py 的图 + run_loop 决定。
"""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    PartDeltaEvent,
    PartEndEvent,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from config import DATABASE_PATH, create_chat_agent
from context import (
    ActionKind,
    ChatDeps,
    LoopContext,
    NodeName,
    NodeOutput,
    ToolMode,
    register_node,
)
from db import DatabaseFacade
from tool import build_tools


# ── 辅助函数 ──

async def _emit(ctx: LoopContext, event: dict[str, Any]) -> None:
    """向 SSE 队列发送事件。队列不存在时静默跳过。"""
    if ctx.sse_queue is not None:
        await ctx.sse_queue.put(event)


# ── 节点函数 ──


@register_node(NodeName.VALIDATE)
async def validate_node(ctx: LoopContext) -> NodeOutput:
    """校验请求归属与合法性。

    所有 action 统一走归属链验证: user → project → session。
    REGENERATE 额外校验 parent_msg_id 存在性。
    SEND 额外校验 user_input 和 pid 非空。
    STOP 仅归属链校验，不过则拒绝。
    """
    db = DatabaseFacade(db_path=DATABASE_PATH)

    # 归属校验
    if not db.access.validate_project_session(
        user_uuid=ctx.user_uuid,
        pid=ctx.pid,
        sid=ctx.sid,
    ):
        ctx.error = "Access denied: project/session does not belong to user"
        ctx.error_code = "FORBIDDEN"
        return NodeOutput(transition=NodeName.STREAM_ERROR)

    if ctx.action == ActionKind.REGENERATE:
        if not ctx.parent_msg_id:
            ctx.error = "Missing parent_msg_id for regenerate"
            ctx.error_code = "BAD_REQUEST"
            return NodeOutput(transition=NodeName.STREAM_ERROR)

        parent = db.messages.get_for_user(
            msg_id=ctx.parent_msg_id,
            user_uuid=ctx.user_uuid,
        )
        if parent is None:
            ctx.error = "Parent message not found"
            ctx.error_code = "RESOURCE_NOT_FOUND"
            return NodeOutput(transition=NodeName.STREAM_ERROR)

    elif ctx.action == ActionKind.SEND:
        if not ctx.user_input.strip():
            ctx.error = "Missing user input"
            ctx.error_code = "BAD_REQUEST"
            return NodeOutput(transition=NodeName.STREAM_ERROR)
        if not ctx.pid:
            ctx.error = "Missing project id"
            ctx.error_code = "BAD_REQUEST"
            return NodeOutput(transition=NodeName.STREAM_ERROR)

    return NodeOutput()


@register_node(NodeName.LOAD_HISTORY)
async def load_history_node(ctx: LoopContext) -> NodeOutput:
    """加载会话最新消息历史并反序列化为 ModelMessage 列表。

    REGENERATE 模式: 截断到 parent_msg_id 之前。
    parent_msg_id 是数据库的 msg_id（非 ModelMessage.run_id），
    因此用原始行中的 msg_id 做匹配。
    """
    db = DatabaseFacade(db_path=DATABASE_PATH)

    raw_messages = db.messages.list_latest_by_session_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
    )

    adapter = TypeAdapter(ModelMessage)
    history: list[ModelMessage] = []

    for m in raw_messages:
        if ctx.action == ActionKind.REGENERATE and ctx.parent_msg_id:
            if m["msg_id"] == ctx.parent_msg_id:
                break  # 停止在前一条，不包含 parent 消息
        history.append(adapter.validate_json(m["raw_json"]))

    ctx.history_messages = history
    return NodeOutput()


@register_node(NodeName.BUILD_MESSAGES)
async def build_messages_node(ctx: LoopContext) -> NodeOutput:
    """组装传给模型的完整消息列表 ctx.messages。

    SEND: 在历史末尾追加当前用户消息 ModelRequest。
    REGENERATE: 历史已截断至 target 之前，最后一条为用户消息，直接复用。
    """
    if ctx.action == ActionKind.SEND:
        now = datetime.datetime.now(datetime.timezone.utc)
        user_part = UserPromptPart(content=ctx.user_input, timestamp=now)
        user_msg: ModelMessage = ModelRequest(parts=[user_part])  # type: ignore[arg-type]
        ctx.messages = ctx.history_messages + [user_msg]
    else:
        ctx.messages = list(ctx.history_messages)

    return NodeOutput()


@register_node(NodeName.CALL_MODEL)
async def call_model_node(ctx: LoopContext) -> NodeOutput:
    """调用 PydanticAI Agent，流式消费事件并推送 SSE。

    PydanticAI 内部自动处理工具调用循环（Option A 黑盒模式），
    图表层只看最终结果（成功 → SAVE / 失败 (可重试) → CALL_MODEL / 失败 (耗尽) → STREAM_ERROR）。

    SEND: 以 user_input 为 user_prompt，历史为 message_history。
    REGENERATE: 历史最后一条为用户消息，不传额外 user_prompt，PydanticAI 从历史继续。
    """
    deps = ChatDeps(
        user_uuid=ctx.user_uuid,
        pid=ctx.pid,
        sid=ctx.sid,
        allowed_tools=ctx.allowed_tools,
        tool_mode=ToolMode.ON,
    )

    agent = create_chat_agent().with_tools(build_tools())
    ctx.response_text = ""
    # 新一轮调用开始，清除上一轮的临时错误状态
    ctx.error = None
    ctx.error_code = None

    if ctx.action == ActionKind.SEND:
        user_prompt: str | None = ctx.user_input
        message_history: list[ModelMessage] | None = ctx.history_messages
    else:
        # REGENERATE: 历史已含用户消息，传 None 让 PydanticAI 从历史末尾继续
        user_prompt = None
        message_history = ctx.history_messages if ctx.history_messages else None

    try:
        last_result: AgentRunResultEvent | None = None

        async for event in agent.run_stream_events(
            user_prompt=user_prompt,
            message_history=message_history,
            deps=deps,
        ):
            if isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    delta_text = event.delta.content_delta
                    ctx.response_text += delta_text
                    await _emit(ctx, {"type": "text_delta", "content": delta_text})

            elif isinstance(event, PartEndEvent):
                if isinstance(event.part, ToolCallPart):
                    await _emit(ctx, {
                        "type": "tool_call",
                        "tool_name": event.part.tool_name,
                        "args": str(event.part.args),
                    })
                elif isinstance(event.part, ToolReturnPart):
                    await _emit(ctx, {
                        "type": "tool_result",
                        "tool_name": event.part.tool_name,
                    })

            elif isinstance(event, FunctionToolCallEvent):
                await _emit(ctx, {
                    "type": "tool_call",
                    "tool_name": event.part.tool_name,
                })

            elif isinstance(event, FunctionToolResultEvent):
                await _emit(ctx, {
                    "type": "tool_result",
                    "tool_name": event.result.tool_name,
                })

            elif isinstance(event, AgentRunResultEvent):
                last_result = event

        if last_result is not None:
            result = last_result.result
            ctx.messages = ctx.history_messages + list(result.new_messages)
            ctx.tool_rounds = result.usage.tool_calls
        else:
            ctx.error = "No AgentRunResultEvent received"
            ctx.error_code = "MODEL_CALL_FAILED"

    except Exception as exc:
        ctx.error = str(exc)
        ctx.error_code = "MODEL_CALL_FAILED"
        ctx.retries += 1

    return NodeOutput()


@register_node(NodeName.SAVE)
async def save_node(ctx: LoopContext) -> NodeOutput:
    """落库本轮新消息并更新会话时间戳。"""
    db = DatabaseFacade(db_path=DATABASE_PATH)

    # 计算本轮新产生的消息
    new_messages = [
        m for m in ctx.messages
        if m not in ctx.history_messages
    ]

    if new_messages:
        parent_msg_id = (
            ctx.parent_msg_id if ctx.action == ActionKind.REGENERATE else None
        )
        response_msg_id = db.messages.save_agent_messages(
            sid=ctx.sid,
            user_uuid=ctx.user_uuid,
            new_messages=new_messages,
            is_final_turn=True,
            parent_msg_id=parent_msg_id,
        )
        ctx.response_msg_id = response_msg_id

    db.sessions.touch_timestamp(sid=ctx.sid)
    return NodeOutput()
