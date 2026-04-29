"""
loop_nodes.py — Agent Loop 状态图节点模块

本模块职责：
1. 定义 LoopCtx / LoopResult / Node 等核心数据结构
2. 提供 Agent Loop 所需的所有状态节点函数与工具用量校验
3. 统一节点函数签名为 async (ctx: LoopCtx) -> str

节点函数通过延迟导入访问 loop.py 中的共享资源（db, _to_history, _to_json, _call_model 等），
避免循环导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, NoReturn, cast

from fastapi import HTTPException, status
from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, UserPromptPart

# 节点函数签名：接收 ctx，返回路由 key（str）
NodeFunc = Callable[["LoopCtx"], Awaitable[str]]


@dataclass
class Node:
    """状态图中的一个节点"""
    run: NodeFunc          # async (ctx) -> str  返回路由 key
    edges: dict[str, str]  # 路由 key → 下一节点名


# ============================================================
# Prompt 常量
# ============================================================

TOOL_EXHAUSTED_PROMPT = (
    "Tool usage limit reached. You cannot call any more tools. "
    "Please provide the best possible final answer based on the information you already have. "
    "Set tool_in_progress to 0."
)

TOOL_FORCE_PROMPT = (
    "Tool mode is force. Call one allowed tool at least once before returning final output. "
    "When the tool process is complete, set tool_in_progress to 0."
)

TOOL_CONTINUE_PROMPT = (
    "If you still need tools, keep tool_in_progress as 1 and continue. "
    "If everything is complete, set tool_in_progress to 0 and return the final answer."
)


# ============================================================
# ApiError（HTTP 异常响应体）
# ============================================================

class ApiError(BaseModel):
    """API 错误响应体（用于构造 HTTPException.detail）"""
    code: str
    message: str
    request_id: str
    retry_of_request_id: str | None = None
    retryable: bool
    detail: dict[str, Any] | None = None


# ============================================================
# ToolCheck（工具用量校验与循环控制）
# ============================================================

@dataclass
class ToolCheck:
    """工具调用计数、FORCE 模式校验以及循环次数限制"""
    max_tool_loops: int
    request_id: str
    retry_of_request_id: str | None = None

    total_tool_calls: int = 0
    orchestration_round: int = 0
    saw_tool_call: bool = False

    def _err(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool,
        detail: dict[str, Any] | None = None,
    ) -> NoReturn:
        payload = ApiError(
            code=code,
            message=message,
            request_id=self.request_id,
            retry_of_request_id=self.retry_of_request_id,
            retryable=retryable,
            detail=detail,
        ).model_dump(exclude_none=True)
        raise HTTPException(status_code=status_code, detail=payload)

    def is_quota_exceeded(self) -> bool:
        return self.total_tool_calls >= self.max_tool_loops

    def update_usage(self, calls_in_run: int, is_final: bool):
        self.total_tool_calls += calls_in_run
        if calls_in_run > 0:
            self.saw_tool_call = True
        if not is_final:
            self.orchestration_round += 1
            if self.orchestration_round > self.max_tool_loops * 2:
                self._err(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="ORCHESTRATION_LIMIT_EXCEEDED",
                    message="Orchestration loop limit exceeded",
                    retryable=True,
                )

    def should_force_continue(self, tool_mode: str) -> bool:
        if tool_mode == "force" and not self.saw_tool_call:
            self.orchestration_round += 1
            if self.orchestration_round > self.max_tool_loops:
                self._err(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="TOOL_LOOP_LIMIT_EXCEEDED",
                    message="Tool loop limit exceeded",
                    retryable=True,
                )
            return True
        return False

    @property
    def remaining_calls(self) -> int:
        return max(self.max_tool_loops - self.total_tool_calls, 0)


# ============================================================
# 循环上下文与返回值
# ============================================================


@dataclass
class LoopCtx:
    """Agent Loop 循环上下文，节点间通过字段传递中间数据"""
    sid: str
    user_uuid: str
    deps: "ChatDeps"
    request_id: str
    retry_of_request_id: str | None
    parent_msg_id: str | None = None
    version: int | None = None

    model_history: list["ModelMessage"] = field(default_factory=list)
    result: "AgentRunResult | None" = None
    output: "AgentOutput | None" = None
    final_msg_id: str | None = None
    loop_result: "LoopResult | None" = None
    tracker: "ToolCheck | None" = None


@dataclass
class LoopResult:
    """Agent Loop 循环返回值"""
    answer: str
    msg_id: str
    version: int | None = None


# ============================================================
# 状态节点函数
# ============================================================


async def _load_history(ctx: LoopCtx) -> str:
    """从数据库加载当前会话的最新消息历史"""
    from loop import _to_history, db

    history_rows = db.messages.list_latest_by_session_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
    )
    ctx.model_history = _to_history(history_rows)
    return "ok"


async def _check_quota(ctx: LoopCtx) -> str:
    """检查工具调用配额是否已用尽"""
    assert ctx.tracker is not None
    if ctx.tracker.is_quota_exceeded():
        return "exhausted"
    return "ok"


async def _inject_exhausted(ctx: LoopCtx) -> str:
    """注入工具配额耗尽提示（历史由 _load_history 在下一轮重新加载）"""
    from loop import _to_json, db

    exhausted_msg = ModelRequest(parts=[UserPromptPart(content=TOOL_EXHAUSTED_PROMPT)])
    db.messages.create_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
        kind="route_user",
        raw_json=_to_json(exhausted_msg),
        parent_msg_id=ctx.parent_msg_id,
        version=ctx.version,
    )
    return "ok"


async def _call_agent(ctx: LoopCtx) -> str:
    """调用 AI 模型（重试逻辑在 _call_model 内部）"""
    from loop import _call_model, AgentOutput

    assert ctx.tracker is not None
    remaining = 0 if ctx.tracker.is_quota_exceeded() else ctx.tracker.remaining_calls
    ctx.result = await _call_model(
        message_history=ctx.model_history or [],
        deps=ctx.deps,
        remaining_tool_calls=remaining,
        request_id=ctx.request_id,
        retry_of_request_id=ctx.retry_of_request_id,
    )
    ctx.output = cast(AgentOutput, ctx.result.output)
    return "ok"


async def _persist_messages(ctx: LoopCtx) -> str:
    """持久化 Agent 产生的所有新消息"""
    from loop import db

    new_messages = ctx.result.new_messages() if ctx.result else []
    is_final = ctx.output.tool_in_progress == 0 if ctx.output else False
    ctx.final_msg_id = db.messages.save_agent_messages(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
        new_messages=new_messages,
        is_final_turn=is_final,
        parent_msg_id=ctx.parent_msg_id,
        version=ctx.version,
    )
    return "ok"


async def _update_tracker(ctx: LoopCtx) -> str:
    """更新工具用量统计并决定下一步路由"""
    assert ctx.tracker is not None
    usage = ctx.result.usage() if ctx.result else None
    calls_in_run = usage.tool_calls if usage else 0
    is_final = ctx.output.tool_in_progress == 0 if ctx.output else False
    ctx.tracker.update_usage(calls_in_run, is_final)

    if ctx.tracker.should_force_continue(ctx.deps.tool_mode.value):
        return "force"
    if is_final:
        return "final"
    return "continue"


async def _inject_force(ctx: LoopCtx) -> str:
    """注入 FORCE 模式提示（要求 AI 必须调用工具）"""
    from loop import _to_json, db

    msg = ModelRequest(parts=[UserPromptPart(content=TOOL_FORCE_PROMPT)])
    db.messages.create_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
        kind="route_user",
        raw_json=_to_json(msg),
        parent_msg_id=ctx.parent_msg_id,
        version=ctx.version,
    )
    return "ok"


async def _inject_continue(ctx: LoopCtx) -> str:
    """注入继续提示（AI 还需继续调用工具）"""
    from loop import _to_json, db

    msg = ModelRequest(parts=[UserPromptPart(content=TOOL_CONTINUE_PROMPT)])
    db.messages.create_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
        kind="route_user",
        raw_json=_to_json(msg),
        parent_msg_id=ctx.parent_msg_id,
        version=ctx.version,
    )
    return "ok"


async def _finish(ctx: LoopCtx) -> str:
    """完成：更新时间戳并设置最终结果"""
    from loop import db

    db.sessions.touch_timestamp(ctx.sid)
    ctx.loop_result = LoopResult(
        answer=ctx.output.answer if ctx.output else "",
        msg_id=ctx.final_msg_id or "",
        version=ctx.version,
    )
    return ""  # 终端节点，无出边
