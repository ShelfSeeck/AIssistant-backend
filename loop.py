"""
loop.py - AI Agent 聊天循环与路由模块

核心职责：
1. 接收 HTTP 请求，验证用户权限
2. 构建对话历史，调用 AI 模型
3. 处理工具调用循环（Agent Loop）
4. 持久化消息记录

详细架构文档见 ARCHITECTURE.md
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, ModelMessagesTypeAdapter, RunContext
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.tools import Tool, ToolDefinition
from pydantic_ai.usage import UsageLimits
from pydantic_core import to_json

from auth import get_current_user
from config import DATABASE_PATH, get_chat_model
from db import (
    create_message_for_user,
    get_message_for_user,
    get_project_for_user,
    get_session_for_user,
    get_max_version_for_parent,
    list_latest_messages_by_session_for_user,
    list_message_versions,
    list_messages_by_session_for_user,
    list_projects_by_user,
    list_sessions_by_project,
    mark_messages_not_latest_after,
    switch_message_version,
)

# 从 tool.py 导入工具相关函数和注册表
from tool import (
    ALLOWED_TOOLS_GLOBAL,
    effective_tools,
    get_registered_tool_names,
    get_tool_registry,
)

# ============================================================
# 常量配置
# ============================================================

# 模型调用失败时的最大重试次数
MAX_MODEL_RETRIES = 3

# 单次请求中工具调用的最大次数（防止无限循环）
MAX_TOOL_LOOPS = 20

# FORCE 模式下，AI 未调用工具时注入的提示
TOOL_FORCE_PROMPT = (
    "Tool mode is force. Call one allowed tool at least once before returning final output. "
    "When the tool process is complete, set tool_in_progress to 0."
)

# 工具循环继续时注入的提示
TOOL_CONTINUE_PROMPT = (
    "If you still need tools, keep tool_in_progress as 1 and continue. "
    "If everything is complete, set tool_in_progress to 0 and return the final answer."
)


# ============================================================
# 数据模型定义
# ============================================================


class ToolMode(str, Enum):
    """
    工具使用模式枚举
    
    - OFF:   完全禁止工具调用，AI 只能纯文本回复
    - AUTO:  自动模式，AI 根据需要决定是否调用工具
    - FORCE: 强制模式，AI 必须至少调用一次工具才能返回
    """
    OFF = "off"
    AUTO = "auto"
    FORCE = "force"


class ChatSendRequest(BaseModel):
    """
    聊天发送请求体
    
    数据来源：前端 HTTP POST body
    数据去向：_handle_chat_turn() 处理
    
    字段说明：
    - pid: 项目 ID，用于权限校验
    - sid: 会话 ID，用于关联消息历史
    - user_input: 用户输入的文本
    - retry_of_request_id: 重试时关联的原请求 ID
    - tool_mode: 工具使用模式
    - allowed_tools: 前端指定的允许工具列表（会与后端白名单取交集）
    """
    pid: str = Field(min_length=1)
    sid: str = Field(min_length=1)
    user_input: str = Field(min_length=1)
    retry_of_request_id: str | None = None
    tool_mode: ToolMode = ToolMode.AUTO
    allowed_tools: list[str] | None = None

    @field_validator("user_input", "pid", "sid")
    @classmethod
    def validate(cls, value: str) -> str:
        """清洗并验证字段，去除首尾空白，拒绝空字符串"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank")
        return cleaned


class ChatSendResponse(BaseModel):
    """
    聊天响应体
    
    数据来源：_handle_chat_turn() 返回
    数据去向：HTTP 响应返回给前端
    """
    request_id: str
    retry_of_request_id: str | None = None
    assistant_message: str
    assistant_message_id: str


class ApiError(BaseModel):
    """
    API 错误响应体（用于构造 HTTPException.detail）
    """
    code: str
    message: str
    request_id: str
    retry_of_request_id: str | None = None
    retryable: bool
    detail: dict[str, Any] | None = None


class AgentOutput(BaseModel):
    """
    AI Agent 的结构化输出格式
    
    数据来源：AI 模型生成（通过 Pydantic AI 的 output_type 约束）
    数据去向：_handle_chat_turn() 解析并决定是否继续循环
    
    字段说明：
    - answer: AI 的文本回复
    - tool_in_progress: 0=完成，1=还需要继续调用工具
    - tool_name: （可选）当前调用的工具名
    - tool_payload: （可选）工具调用参数
    - meta: （可选）元信息
    """
    answer: str = ""
    tool_in_progress: int = Field(default=0, ge=0, le=1)
    tool_name: str | None = None
    tool_payload: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


@dataclass
class ChatDeps:
    """
    Agent 运行时依赖（通过 RunContext.deps 注入到工具函数）
    
    数据来源：_handle_chat_turn() 构造
    数据去向：传入 agent.run_sync(deps=...)，工具函数通过 ctx.deps 访问
    
    字段说明：
    - tool_mode: 当前请求的工具模式
    - allowed_tools: 当前请求的有效工具集合
    """
    tool_mode: ToolMode
    allowed_tools: set[str]


# ============================================================
# 工具过滤与安全包装
# ============================================================


async def _prepare_tools(ctx: RunContext[ChatDeps], tools: list[ToolDefinition]) -> list[ToolDefinition] | None:
    """
    Pydantic AI 工具准备回调 - 在每次模型调用前动态过滤可用工具
    
    数据流：
    ┌─────────────────────────────────────────────────────────┐
    │  Pydantic AI 框架调用（每次 run_sync 前）                │
    │       │                                                 │
    │       ▼                                                 │
    │  ctx.deps (ChatDeps)                                    │
    │       │ 包含 tool_mode 和 allowed_tools                 │
    │       ▼                                                 │
    │  tools (所有已注册的 ToolDefinition 列表)                │
    │       │                                                 │
    │       ▼                                                 │
    │  过滤：只保留 name 在 allowed_tools 中的工具             │
    │       │                                                 │
    │       ▼                                                 │
    │  返回过滤后的工具列表 → 模型只能看到这些工具             │
    └─────────────────────────────────────────────────────────┘
    
    输入：
    - ctx: RunContext，包含 deps（运行时依赖）
    - tools: 所有注册的工具定义列表
    
    输出：
    - 过滤后的工具列表（或空列表表示禁用所有工具）
    """
    deps = ctx.deps
    if deps.tool_mode == ToolMode.OFF:
        return []

    if not deps.allowed_tools:
        return []

    return [tool for tool in tools if tool.name in deps.allowed_tools]


def _create_guarded_tool(func: Any, tool_name: str) -> Any:
    """
    为工具函数创建带安全检查的包装器
    
    数据流：
    ┌─────────────────────────────────────────────────────────┐
    │  原始工具函数 (func)                                     │
    │       │                                                 │
    │       ▼                                                 │
    │  包装为 guarded 函数                                     │
    │       │                                                 │
    │  AI 模型调用工具时：                                     │
    │       ▼                                                 │
    │  guarded(ctx, *args, **kwargs)                          │
    │       │                                                 │
    │       ├─→ 检查 tool_name 是否已注册                      │
    │       ├─→ 检查是否在全局白名单中                         │
    │       ├─→ 检查 tool_mode 是否为 OFF                      │
    │       ├─→ 检查是否在请求级 allowed_tools 中              │
    │       │                                                 │
    │       ▼                                                 │
    │  全部通过 → 调用原函数 func(ctx, *args, **kwargs)        │
    │  任一失败 → 返回 {"error": "...", "tool_name": "..."}   │
    └─────────────────────────────────────────────────────────┘
    
    输入：
    - func: 原始工具函数
    - tool_name: 工具名称
    
    输出：
    - 包装后的函数（带运行时权限校验）
    
    设计原因：
    - _prepare_tools 在模型调用前过滤工具定义（让模型看不到被禁用的工具）
    - guarded 在实际执行时再次校验（防止模型绕过或缓存问题）
    - 双重保障，确保安全
    """
    @wraps(func)
    def guarded(ctx: RunContext[ChatDeps], *args: Any, **kwargs: Any) -> dict[str, Any]:
        deps = ctx.deps
        registered_tools = get_registered_tool_names()

        # 校验：工具是否已注册
        if tool_name not in registered_tools:
            return {
                "error": "tool_invalid",
                "tool_name": tool_name,
            }

        # 校验：工具是否在全局白名单中
        if ALLOWED_TOOLS_GLOBAL is not None and tool_name not in ALLOWED_TOOLS_GLOBAL:
            return {
                "error": "tool_not_enabled",
                "tool_name": tool_name,
            }

        # 校验：工具模式是否为 OFF
        if deps.tool_mode == ToolMode.OFF:
            return {
                "error": "tools_disabled",
                "tool_name": tool_name,
            }

        # 校验：工具是否在请求级允许列表中
        if tool_name not in deps.allowed_tools:
            return {
                "error": "tool_not_allowed",
                "tool_name": tool_name,
            }

        # 全部通过，执行原函数
        return func(ctx, *args, **kwargs)

    return guarded


def _build_tools() -> list[Tool[ChatDeps]]:
    """
    从 tool.py 的注册表构建 Agent 的工具列表
    
    数据流：
    ┌─────────────────────────────────────────────────────────┐
    │  tool.py: _TOOL_REGISTRY = {"read_file": func, ...}     │
    │       │                                                 │
    │       ▼                                                 │
    │  get_tool_registry() → 返回注册表副本                    │
    │       │                                                 │
    │       ▼                                                 │
    │  遍历每个工具：                                          │
    │       │ _create_guarded_tool(func, name) → 安全包装     │
    │       │ Tool(guarded_func) → Pydantic AI 工具对象       │
    │       ▼                                                 │
    │  返回 list[Tool] → 传入 Agent 构造函数                   │
    └─────────────────────────────────────────────────────────┘
    
    输入：无（从 tool.py 全局注册表读取）
    输出：Tool 对象列表，用于 Agent(tools=...)
    
    调用时机：模块加载时（创建 _CHAT_AGENT 单例）
    """
    tool_registry = get_tool_registry()
    tools: list[Tool[ChatDeps]] = []
    for tool_name, func in tool_registry.items():
        guarded_func = _create_guarded_tool(func, tool_name)
        tools.append(Tool(guarded_func))
    return tools


# ============================================================
# Agent 单例
# ============================================================


# Agent 单例：模块加载时创建，整个应用共享
# - get_chat_model(): 从配置获取 LLM 模型
# - deps_type: 声明运行时依赖类型
# - output_type: 约束 AI 输出必须符合 AgentOutput 结构
# - tools: 所有可用工具（已包装安全检查）
# - prepare_tools: 每次调用前动态过滤工具的回调
_CHAT_AGENT: Agent[ChatDeps, AgentOutput] = Agent(
    get_chat_model(),
    deps_type=ChatDeps,
    output_type=AgentOutput,
    instructions=(
        "You are a backend assistant orchestrator. "
        "Always return structured output that matches the output schema. "
        "Use tools only when needed and follow tool_mode constraints. "
        "When all required tool work is done, set tool_in_progress to 0."
    ),
    tools=_build_tools(),
    prepare_tools=_prepare_tools,
)


# ============================================================
# FastAPI 路由
# ============================================================

router = APIRouter(tags=["chatloop"])#tags 用于给路由分组，自动生成文档时会展示


# ============================================================
# 辅助函数
# ============================================================


def _raise_api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    retry_of_request_id: str | None,
    retryable: bool,
    detail: dict[str, Any] | None = None,
) -> NoReturn:
    """构造并抛出标准化的 API 错误"""
    payload = ApiError(
        code=code,
        message=message,
        request_id=request_id,
        retry_of_request_id=retry_of_request_id,
        retryable=retryable,
        detail=detail,
    ).model_dump(exclude_none=True)
    raise HTTPException(status_code=status_code, detail=payload)


def _build_model_history(rows: list[dict]) -> list[ModelMessage]:
    """将数据库消息记录反序列化为 Pydantic AI ModelMessage 列表"""
    history: list[ModelMessage] = []
    for row in rows:
        raw_json = row.get("raw_json", "")
        if not raw_json:
            continue
        try:
            messages = ModelMessagesTypeAdapter.validate_json(f"[{raw_json}]")
            if messages:
                history.append(messages[0])
        except Exception:
            pass
    return history


def _serialize_message(message: ModelMessage) -> str:
    """将单条 ModelMessage 序列化为 JSON 字符串"""
    return to_json(message).decode("utf-8")


def save_agent_messages(
    *,
    sid: str,
    user_uuid: str,
    new_messages: list[ModelMessage],
    is_final_turn: bool = False,
    parent_msg_id: str | None = None,
    version: int = 1,
) -> tuple[int, str | None]:
    """
    持久化 Agent 产生的所有新消息到数据库
    
    返回：(本轮工具调用次数, 最终 assistant 消息的 msg_id 或 None)
    """
    tool_call_count = 0
    final_msg_id: str | None = None

    for message in new_messages:
        if isinstance(message, ModelResponse):
            has_tool_call = any(isinstance(part, ToolCallPart) for part in message.parts)
            if has_tool_call:
                # AI 决定调用工具
                create_message_for_user(
                    sid=sid,
                    user_uuid=user_uuid,
                    kind="tool_call",
                    raw_json=_serialize_message(message),
                    parent_msg_id=parent_msg_id,
                    version=version,
                    db_path=DATABASE_PATH,
                )
                tool_call_count += sum(1 for part in message.parts if isinstance(part, ToolCallPart))
            else:
                # 纯文本回复
                if is_final_turn:
                    # 最终轮次：标记为 assistant
                    row = create_message_for_user(
                        sid=sid,
                        user_uuid=user_uuid,
                        kind="assistant",
                        raw_json=_serialize_message(message),
                        parent_msg_id=parent_msg_id,
                        version=version,
                        db_path=DATABASE_PATH,
                    )
                    final_msg_id = str(row["msg_id"])
                else:
                    # 中间轮次：标记为 agent_response
                    create_message_for_user(
                        sid=sid,
                        user_uuid=user_uuid,
                        kind="agent_response",
                        raw_json=_serialize_message(message),
                        parent_msg_id=parent_msg_id,
                        version=version,
                        db_path=DATABASE_PATH,
                    )

        elif isinstance(message, ModelRequest):
            has_tool_return = any(isinstance(part, ToolReturnPart) for part in message.parts)
            if has_tool_return:
                # 工具执行结果返回
                create_message_for_user(
                    sid=sid,
                    user_uuid=user_uuid,
                    kind="tool_result",
                    raw_json=_serialize_message(message),
                    parent_msg_id=parent_msg_id,
                    version=version,
                    db_path=DATABASE_PATH,
                )

    return tool_call_count, final_msg_id


def _run_model_with_retry(
    *,
    message_history: list[ModelMessage],
    deps: ChatDeps,
    remaining_tool_calls: int,
    request_id: str,
    retry_of_request_id: str | None,
) -> AgentRunResult[Any]:
    """
    调用 AI 模型（带重试机制）
    
    错误处理：
    - UsageLimitExceeded: 抛出 429
    - ModelAPIError 等: 重试后抛出 502
    """
    last_error: Exception | None = None
    tool_limit = max(remaining_tool_calls, 0)

    for attempt in range(1, MAX_MODEL_RETRIES + 1):
        try:
            return _CHAT_AGENT.run_sync(
                user_prompt=None,
                message_history=message_history,
                deps=deps,
                usage_limits=UsageLimits(tool_calls_limit=tool_limit),
            )
        except UsageLimitExceeded as exc:
            _raise_api_error(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="TOOL_LOOP_LIMIT_EXCEEDED",
                message="Tool loop limit exceeded",
                request_id=request_id,
                retry_of_request_id=retry_of_request_id,
                retryable=True,
                detail={"error": str(exc)},
            )
        except (ModelAPIError, ModelHTTPError, AgentRunError) as exc:
            last_error = exc
            if attempt == MAX_MODEL_RETRIES:
                _raise_api_error(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    code="MODEL_UPSTREAM_ERROR",
                    message="Model upstream failed after retries",
                    request_id=request_id,
                    retry_of_request_id=retry_of_request_id,
                    retryable=True,
                    detail={"error": str(last_error)},
                )

    # 防御性分支，正常情况不应到达
    _raise_api_error(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        message="Unexpected model retry state",
        request_id=request_id,
        retry_of_request_id=retry_of_request_id,
        retryable=True,
    )


def _validate_resource_access(
    *,
    user_uuid: str,
    pid: str,
    sid: str,
    request_id: str,
    retry_of_request_id: str | None,
) -> None:
    """验证用户对项目和会话的访问权限，失败则抛出 404"""
    project = get_project_for_user(pid=pid, user_uuid=user_uuid, db_path=DATABASE_PATH)
    if project is None:
        _raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Resource not found",
            request_id=request_id,
            retry_of_request_id=retry_of_request_id,
            retryable=False,
        )

    session = get_session_for_user(sid=sid, user_uuid=user_uuid, db_path=DATABASE_PATH)
    if session is None or session.get("pid") != pid:
        _raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Resource not found",
            request_id=request_id,
            retry_of_request_id=retry_of_request_id,
            retryable=False,
        )


# ============================================================
# 核心业务逻辑
# ============================================================


def _handle_chat_turn(
    *,
    payload: ChatSendRequest,
    user_uuid: str,
    request_id: str,
) -> ChatSendResponse:
    """处理单次聊天轮次的核心逻辑（Agent Loop）"""
    # 1. 权限校验
    _validate_resource_access(
        user_uuid=user_uuid,
        pid=payload.pid,
        sid=payload.sid,
        request_id=request_id,
        retry_of_request_id=payload.retry_of_request_id,
    )

    # 2. 保存用户消息
    user_message = ModelRequest(parts=[UserPromptPart(content=payload.user_input)])
    create_message_for_user(
        sid=payload.sid,
        user_uuid=user_uuid,
        kind="user",
        raw_json=_serialize_message(user_message),
        db_path=DATABASE_PATH,
    )

    # 3. 计算有效工具集合（后端白名单 ∩ 前端请求）
    effective_allowed_tools = effective_tools(payload.allowed_tools)

    if payload.tool_mode == ToolMode.FORCE and not effective_allowed_tools:
        _raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="FORCE_MODE_NO_ALLOWED_TOOLS",
            message="No allowed tools available for force mode",
            request_id=request_id,
            retry_of_request_id=payload.retry_of_request_id,
            retryable=False,
            detail={
                "global_allowed_tools": sorted(effective_tools(None)),
                "registered_tools": sorted(get_registered_tool_names()),
            },
        )

    # 4. 构造运行时依赖
    deps = ChatDeps(
        tool_mode=payload.tool_mode,
        allowed_tools=effective_allowed_tools,
    )

    # 循环控制变量
    total_tool_calls = 0       # 累计工具调用次数
    orchestration_round = 0    # 编排轮次
    saw_tool_call = False      # FORCE 模式：是否已调用过工具

    # ===== Agent Loop =====
    while True:
        # a. 从数据库加载历史消息（只加载 is_latest=1 的消息）
        history_rows = list_latest_messages_by_session_for_user(
            sid=payload.sid,
            user_uuid=user_uuid,
            db_path=DATABASE_PATH,
        )
        model_history = _build_model_history(history_rows)

        # 检查工具调用配额
        remaining_tool_calls = MAX_TOOL_LOOPS - total_tool_calls
        if remaining_tool_calls < 0:
            _raise_api_error(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="TOOL_LOOP_LIMIT_EXCEEDED",
                message="Tool loop limit exceeded",
                request_id=request_id,
                retry_of_request_id=payload.retry_of_request_id,
                retryable=True,
            )

        # b. 调用 AI 模型
        result = _run_model_with_retry(
            message_history=model_history,
            deps=deps,
            remaining_tool_calls=remaining_tool_calls,
            request_id=request_id,
            retry_of_request_id=payload.retry_of_request_id,
        )

        output = cast(AgentOutput, result.output)
        is_final = output.tool_in_progress == 0

        # c. 持久化 Agent 产生的所有新消息
        new_messages = result.new_messages()
        calls_in_run, final_msg_id = save_agent_messages(
            sid=payload.sid,
            user_uuid=user_uuid,
            new_messages=new_messages,
            is_final_turn=is_final,
        )

        total_tool_calls += calls_in_run
        saw_tool_call = saw_tool_call or calls_in_run > 0

        # d. 检查循环条件

        # FORCE 模式：必须至少调用一次工具
        if payload.tool_mode == ToolMode.FORCE and not saw_tool_call:
            orchestration_round += 1
            if orchestration_round > MAX_TOOL_LOOPS:
                _raise_api_error(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="TOOL_LOOP_LIMIT_EXCEEDED",
                    message="Tool loop limit exceeded",
                    request_id=request_id,
                    retry_of_request_id=payload.retry_of_request_id,
                    retryable=True,
                )

            # 注入强制工具调用提示
            route_message = ModelRequest(parts=[UserPromptPart(content=TOOL_FORCE_PROMPT)])
            create_message_for_user(
                sid=payload.sid,
                user_uuid=user_uuid,
                kind="route_user",
                raw_json=_serialize_message(route_message),
                db_path=DATABASE_PATH,
            )
            continue

        # AI 表示已完成 → 退出循环，返回最终答案
        if is_final:
            return ChatSendResponse(
                request_id=request_id,
                retry_of_request_id=payload.retry_of_request_id,
                assistant_message=output.answer,
                assistant_message_id=final_msg_id or "",
            )

        # AI 表示还需继续 → 注入继续提示，进入下一轮
        orchestration_round += 1
        if orchestration_round > MAX_TOOL_LOOPS:
            _raise_api_error(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="TOOL_LOOP_LIMIT_EXCEEDED",
                message="Tool loop limit exceeded",
                request_id=request_id,
                retry_of_request_id=payload.retry_of_request_id,
                retryable=True,
            )

        route_continue_message = ModelRequest(parts=[UserPromptPart(content=TOOL_CONTINUE_PROMPT)])
        create_message_for_user(
            sid=payload.sid,
            user_uuid=user_uuid,
            kind="route_user",
            raw_json=_serialize_message(route_continue_message),
            db_path=DATABASE_PATH,
        )


# ============================================================
# HTTP 路由处理器
# ============================================================


@router.post("/chat/{sid}", response_model=ChatSendResponse)
def post_chat_message(
    sid: str,
    payload: ChatSendRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ChatSendResponse:
    """发送聊天消息 API 端点"""
    request_id = str(uuid.uuid4())

    if sid != payload.sid:
        _raise_api_error(
            status_code=status.HTTP_409_CONFLICT,
            code="SESSION_CONFLICT",
            message="Path sid and body sid mismatch",
            request_id=request_id,
            retry_of_request_id=payload.retry_of_request_id,
            retryable=False,
        )

    raw_user_uuid = current_user.get("uuid")
    if not isinstance(raw_user_uuid, str) or not raw_user_uuid:
        _raise_api_error(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_TOKEN_INVALID",
            message="Invalid user token payload",
            request_id=request_id,
            retry_of_request_id=payload.retry_of_request_id,
            retryable=False,
        )
    user_uuid = cast(str, raw_user_uuid)

    try:
        return _handle_chat_turn(
            payload=payload,
            user_uuid=user_uuid,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except PermissionError:
        _raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Resource not found",
            request_id=request_id,
            retry_of_request_id=payload.retry_of_request_id,
            retryable=False,
        )
    except Exception as exc:
        _raise_api_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Internal server error",
            request_id=request_id,
            retry_of_request_id=payload.retry_of_request_id,
            retryable=True,
            detail={"error": str(exc)},
        )


# ============================================================
# 资源查询端点
# ============================================================


class ProjectItem(BaseModel):
    """项目信息"""
    pid: str
    projectname: str
    created_at: str


class ProjectListResponse(BaseModel):
    """用户项目列表响应"""
    projects: list[ProjectItem]


class SessionItem(BaseModel):
    """会话信息"""
    sid: str
    sessionname: str
    created_at: str


class SessionListResponse(BaseModel):
    """项目会话列表响应"""
    sessions: list[SessionItem]


class MessageItem(BaseModel):
    """消息信息"""
    msg_id: str
    kind: str
    raw_json: str
    msg_time: str
    parent_msg_id: str | None = None
    version: int = 1
    is_latest: int = 1


class MessageListResponse(BaseModel):
    """会话消息列表响应"""
    messages: list[MessageItem]


@router.get("/users/{user_id}/projects", response_model=ProjectListResponse)
def list_user_projects(
    user_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ProjectListResponse:
    """查询用户所拥有的项目"""
    # 校验请求的 user_id 与 JWT 中的用户一致
    jwt_user_uuid = current_user.get("uuid")
    if user_id != jwt_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Cannot access other user's projects"},
        )

    projects = list_projects_by_user(user_uuid=user_id, db_path=DATABASE_PATH)
    return ProjectListResponse(
        projects=[
            ProjectItem(
                pid=p["pid"],
                projectname=p["projectname"],
                created_at=str(p["created_at"]),
            )
            for p in projects
        ]
    )


@router.get("/projects/{pid}/sessions", response_model=SessionListResponse)
def list_project_sessions(
    pid: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SessionListResponse:
    """查询项目下的所有会话"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    # 校验用户对项目的所有权
    project = get_project_for_user(pid=pid, user_uuid=user_uuid, db_path=DATABASE_PATH)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Project not found"},
        )

    sessions = list_sessions_by_project(pid=pid, db_path=DATABASE_PATH)
    return SessionListResponse(
        sessions=[
            SessionItem(
                sid=s["sid"],
                sessionname=s["sessionname"],
                created_at=str(s["created_at"]),
            )
            for s in sessions
        ]
    )


@router.get("/sessions/{sid}/messages", response_model=MessageListResponse)
def list_session_messages(
    sid: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MessageListResponse:
    """查询会话的所有消息"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    # 校验用户对会话的所有权
    session = get_session_for_user(sid=sid, user_uuid=user_uuid, db_path=DATABASE_PATH)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Session not found"},
        )

    messages = list_messages_by_session_for_user(
        sid=sid, user_uuid=user_uuid, db_path=DATABASE_PATH
    )
    return MessageListResponse(
        messages=[
            MessageItem(
                msg_id=m["msg_id"],
                kind=m["kind"],
                raw_json=m["raw_json"],
                msg_time=m["msg_time"],
                parent_msg_id=m.get("parent_msg_id"),
                version=m.get("version", 1),
                is_latest=m.get("is_latest", 1),
            )
            for m in messages
        ]
    )


# ============================================================
# 工具查询端点
# ============================================================


class ToolRegistryResponse(BaseModel):
    """工具注册表查询响应"""
    tools: list[str]
    global_allowed_tools: list[str]


@router.get("/tools/registry", response_model=ToolRegistryResponse)
def list_tool_registry() -> ToolRegistryResponse:
    """
    查询工具注册表
    
    数据流：
    ┌─────────────────────────────────────────────────────────┐
    │  HTTP GET /tools/registry                                │
    │       │                                                 │
    │       ▼                                                 │
    │  get_registered_tool_names() → 所有已注册工具            │
    │  effective_tools(None) → 全局允许的工具                  │
    │       │                                                 │
    │       ▼                                                 │
    │  ToolRegistryResponse:                                   │
    │  - tools: ["list_workspace_dir", "read_workspace_file"]  │
    │  - global_allowed_tools: ["list_workspace_dir", ...]     │
    └─────────────────────────────────────────────────────────┘
    
    用途：前端可以查询哪些工具可用，用于 UI 展示或配置
    """
    return ToolRegistryResponse(
        tools=sorted(get_registered_tool_names()),
        global_allowed_tools=sorted(effective_tools(None)),
    )


# ============================================================
# Regenerate（重新生成）端点
# ============================================================


class RegenerateRequest(BaseModel):
    """重新生成请求"""
    pid: str = Field(..., description="项目 ID")
    target_msg_id: str = Field(..., description="要重新生成的用户消息 ID")
    tool_mode: ToolMode = Field(default=ToolMode.AUTO, description="工具使用模式")
    allowed_tools: list[str] | None = Field(default=None, description="允许的工具列表")


class RegenerateResponse(BaseModel):
    """重新生成响应"""
    request_id: str
    assistant_message: str
    assistant_message_id: str
    version: int


@router.post("/chat/{sid}/regenerate", response_model=RegenerateResponse)
def regenerate_message(
    sid: str,
    payload: RegenerateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> RegenerateResponse:
    """
    重新生成 AI 回复
    
    逻辑：
    1. 找到目标用户消息
    2. 将该消息之后的所有消息标记为 is_latest=0
    3. 基于截断后的历史重新运行 Agent Loop
    4. 新生成的消息使用递增的 version 号，parent_msg_id 指向目标用户消息
    """
    request_id = str(uuid.uuid4())

    # 用户身份校验
    raw_user_uuid = current_user.get("uuid")
    if not isinstance(raw_user_uuid, str) or not raw_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )
    user_uuid = cast(str, raw_user_uuid)

    # 权限校验
    _validate_resource_access(
        user_uuid=user_uuid,
        pid=payload.pid,
        sid=sid,
        request_id=request_id,
        retry_of_request_id=None,
    )

    # 获取目标消息
    target_msg = get_message_for_user(
        msg_id=payload.target_msg_id,
        user_uuid=user_uuid,
        db_path=DATABASE_PATH,
    )
    if target_msg is None:
        _raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="MESSAGE_NOT_FOUND",
            message="Target message not found",
            request_id=request_id,
            retry_of_request_id=None,
            retryable=False,
        )

    # 校验消息类型必须是 user
    if target_msg["kind"] != "user":
        _raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_TARGET_MESSAGE",
            message="Can only regenerate from a user message",
            request_id=request_id,
            retry_of_request_id=None,
            retryable=False,
        )

    # 将目标消息之后的所有消息标记为非最新
    target_timestamp = target_msg["msg_timestamp"]
    mark_messages_not_latest_after(
        sid=sid,
        msg_timestamp=target_timestamp,
        db_path=DATABASE_PATH,
    )

    # 计算新版本号
    new_version = get_max_version_for_parent(
        parent_msg_id=payload.target_msg_id,
        db_path=DATABASE_PATH,
    ) + 1

    # 构造运行时依赖
    effective_allowed_tools = effective_tools(payload.allowed_tools)
    deps = ChatDeps(
        tool_mode=payload.tool_mode,
        allowed_tools=effective_allowed_tools,
    )

    # 循环控制
    total_tool_calls = 0
    orchestration_round = 0
    saw_tool_call = False

    # ===== Agent Loop =====
    while True:
        # 加载历史消息（只加载 is_latest=1）
        history_rows = list_latest_messages_by_session_for_user(
            sid=sid,
            user_uuid=user_uuid,
            db_path=DATABASE_PATH,
        )
        model_history = _build_model_history(history_rows)

        # 检查工具调用配额
        remaining_tool_calls = MAX_TOOL_LOOPS - total_tool_calls
        if remaining_tool_calls < 0:
            _raise_api_error(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="TOOL_LOOP_LIMIT_EXCEEDED",
                message="Tool loop limit exceeded",
                request_id=request_id,
                retry_of_request_id=None,
                retryable=True,
            )

        # 调用 AI 模型
        result = _run_model_with_retry(
            message_history=model_history,
            deps=deps,
            remaining_tool_calls=remaining_tool_calls,
            request_id=request_id,
            retry_of_request_id=None,
        )

        output = cast(AgentOutput, result.output)
        is_final = output.tool_in_progress == 0

        # 持久化 Agent 产生的新消息（带版本号和 parent_msg_id）
        new_messages = result.new_messages()
        calls_in_run, final_msg_id = save_agent_messages(
            sid=sid,
            user_uuid=user_uuid,
            new_messages=new_messages,
            is_final_turn=is_final,
            parent_msg_id=payload.target_msg_id,
            version=new_version,
        )

        total_tool_calls += calls_in_run
        saw_tool_call = saw_tool_call or calls_in_run > 0

        # FORCE 模式检查
        if payload.tool_mode == ToolMode.FORCE and not saw_tool_call:
            orchestration_round += 1
            if orchestration_round > MAX_TOOL_LOOPS:
                _raise_api_error(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="TOOL_LOOP_LIMIT_EXCEEDED",
                    message="Tool loop limit exceeded",
                    request_id=request_id,
                    retry_of_request_id=None,
                    retryable=True,
                )

            # 注入强制工具调用提示
            route_message = ModelRequest(parts=[UserPromptPart(content=TOOL_FORCE_PROMPT)])
            create_message_for_user(
                sid=sid,
                user_uuid=user_uuid,
                kind="route_user",
                raw_json=_serialize_message(route_message),
                parent_msg_id=payload.target_msg_id,
                version=new_version,
                db_path=DATABASE_PATH,
            )
            continue

        # AI 表示已完成
        if is_final:
            return RegenerateResponse(
                request_id=request_id,
                assistant_message=output.answer,
                assistant_message_id=final_msg_id or "",
                version=new_version,
            )

        # AI 表示还需继续
        orchestration_round += 1
        if orchestration_round > MAX_TOOL_LOOPS:
            _raise_api_error(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="TOOL_LOOP_LIMIT_EXCEEDED",
                message="Tool loop limit exceeded",
                request_id=request_id,
                retry_of_request_id=None,
                retryable=True,
            )

        route_continue_message = ModelRequest(parts=[UserPromptPart(content=TOOL_CONTINUE_PROMPT)])
        create_message_for_user(
            sid=sid,
            user_uuid=user_uuid,
            kind="route_user",
            raw_json=_serialize_message(route_continue_message),
            parent_msg_id=payload.target_msg_id,
            version=new_version,
            db_path=DATABASE_PATH,
        )


# ============================================================
# 消息版本查询与切换端点
# ============================================================


class MessageVersionItem(BaseModel):
    """消息版本项"""
    msg_id: str
    kind: str
    raw_json: str
    version: int
    is_latest: int
    msg_time: str


class MessageVersionsResponse(BaseModel):
    """消息版本列表响应"""
    versions: list[MessageVersionItem]


@router.get("/messages/{msg_id}/versions", response_model=MessageVersionsResponse)
def get_message_versions(
    msg_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MessageVersionsResponse:
    """
    查询某条消息作为 parent 的所有版本
    
    用于前端展示版本切换 UI
    """
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    versions = list_message_versions(
        parent_msg_id=msg_id,
        user_uuid=user_uuid,
        db_path=DATABASE_PATH,
    )
    return MessageVersionsResponse(
        versions=[
            MessageVersionItem(
                msg_id=v["msg_id"],
                kind=v["kind"],
                raw_json=v["raw_json"],
                version=v["version"],
                is_latest=v["is_latest"],
                msg_time=v["msg_time"],
            )
            for v in versions
        ]
    )


class SwitchVersionRequest(BaseModel):
    """切换版本请求"""
    target_version_msg_id: str = Field(..., description="要切换到的版本的消息 ID")


class SwitchVersionResponse(BaseModel):
    """切换版本响应"""
    success: bool
    switched_msg_id: str


@router.post("/messages/{msg_id}/switch-version", response_model=SwitchVersionResponse)
def switch_to_message_version(
    msg_id: str,
    payload: SwitchVersionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SwitchVersionResponse:
    """
    切换到指定版本
    
    将 target_version_msg_id 设为 is_latest=1，同 parent 的其他版本设为 is_latest=0
    """
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    success = switch_message_version(
        msg_id=payload.target_version_msg_id,
        user_uuid=user_uuid,
        db_path=DATABASE_PATH,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SWITCH_FAILED", "message": "Failed to switch version"},
        )

    return SwitchVersionResponse(
        success=True,
        switched_msg_id=payload.target_version_msg_id,
    )
