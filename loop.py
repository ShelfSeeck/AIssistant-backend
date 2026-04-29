"""
loop.py - AI Agent 聊天循环与路由模块

核心职责：
1. 处理聊天主链路与 regenerate 主链路。
2. 组织模型调用、重试与工具循环控制。
3. 通过 db facade 完成消息持久化与权限校验。
4. 通过 tool.build_tools 注入可调用工具。

详细架构文档见 ARCHITECTURE.md
"""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, ModelMessagesTypeAdapter, RunContext
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits
from pydantic_core import to_json

from auth import get_current_user, verify_nonce
from config import DATABASE_PATH, get_chat_model
from db import DatabaseFacade

# 从 tool.py 导入工具相关函数和注册表
from tool import (
    build_tools,
    effective_tools,
    get_registered_tool_names,
)
from loop_nodes import (
    ApiError,
    LoopCtx,
    LoopResult,
    Node,
    TOOL_CONTINUE_PROMPT,
    TOOL_EXHAUSTED_PROMPT,
    TOOL_FORCE_PROMPT,
    ToolCheck,
    _call_agent,
    _check_quota,
    _finish,
    _inject_continue,
    _inject_exhausted,
    _inject_force,
    _load_history,
    _persist_messages,
    _update_tracker,
)

db = DatabaseFacade(db_path=DATABASE_PATH)

# ============================================================
# 常量配置
# ============================================================

# 模型调用失败时的最大重试次数
MAX_MODEL_RETRIES = 3

# 单次请求中工具调用的最大次数（防止无限循环）
MAX_TOOL_LOOPS = 20

# 防重放配置：Nonce 有效期（秒）
NONCE_EXPIRY_SECONDS = 300


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
    数据去向：_chat() 处理
    
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
    
    数据来源：_chat() 返回
    数据去向：HTTP 响应返回给前端
    """
    request_id: str
    retry_of_request_id: str | None = None
    assistant_message: str
    assistant_message_id: str


class AgentOutput(BaseModel):
    """
    AI Agent 的结构化输出格式
    
    数据来源：AI 模型生成（通过 Pydantic AI 的 output_type 约束）
    数据去向：_chat() 解析并决定是否继续循环
    
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
    
    字段说明：
    - tool_mode: 当前请求的工具模式
    - allowed_tools: 当前请求的有效工具集合
    - pid: 当前操作的项目ID（从请求上下文获取，不可由AI修改）
    - user_uuid: 当前操作的用户ID（从认证态获取，不可由AI修改）
    """
    tool_mode: ToolMode
    allowed_tools: set[str]
    pid: str
    user_uuid: str


# ============================================================
# 工具过滤与安全包装
# ============================================================


async def _prepare_tools(ctx: RunContext[ChatDeps], tools: list[ToolDefinition]) -> list[ToolDefinition] | None:
    """
    每次模型调用前按请求上下文过滤工具列表。

    规则：
    - tool_mode 为 off 时禁用全部工具。
    - allowed_tools 为空时禁用全部工具。
    - 其余情况下仅保留名称命中的 ToolDefinition。
    """
    deps = ctx.deps
    if deps.tool_mode == ToolMode.OFF:
        return []

    if not deps.allowed_tools:
        return []

    return [tool for tool in tools if tool.name in deps.allowed_tools]


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
    tools=build_tools(),
    prepare_tools=_prepare_tools,
)


# ============================================================
# FastAPI 路由
# ============================================================

router = APIRouter(tags=["chatloop"])#tags 用于给路由分组，自动生成文档时会展示


# ============================================================
# 辅助函数 用于错误处理、消息转换等
# ============================================================


def _err(
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


def _to_history(rows: list[dict]) -> list[ModelMessage]:
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


def _to_json(message: ModelMessage) -> str:
    """将单条 ModelMessage 序列化为 JSON 字符串"""
    return to_json(message).decode("utf-8")


async def _call_model(
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
            return await _CHAT_AGENT.run(
                user_prompt=None,
                message_history=message_history,
                deps=deps,
                usage_limits=UsageLimits(tool_calls_limit=tool_limit),
            )
        except UsageLimitExceeded as exc:
            _err(
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
                _err(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    code="MODEL_UPSTREAM_ERROR",
                    message="Model upstream failed after retries",
                    request_id=request_id,
                    retry_of_request_id=retry_of_request_id,
                    retryable=True,
                    detail={"error": str(last_error)},
                )

    # 防御性分支，正常情况不应到达
    _err(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        message="Unexpected model retry state",
        request_id=request_id,
        retry_of_request_id=retry_of_request_id,
        retryable=True,
    )


# ============================================================
# Agent Loop 状态图
# ============================================================

_LOOP_NODES: dict[str, Node] = {
    "加载历史":   Node(run=_load_history,      edges={"ok": "配额检查"}),
    "配额检查":   Node(run=_check_quota,       edges={"exhausted": "注入结束提示", "ok": "调用模型"}),
    "注入结束提示": Node(run=_inject_exhausted,  edges={"ok": "调用模型"}),
    "调用模型":   Node(run=_call_agent,        edges={"ok": "持久化消息"}),
    "持久化消息": Node(run=_persist_messages,   edges={"ok": "计数更新"}),
    "计数更新":   Node(run=_update_tracker,     edges={"force": "注入FORCE", "final": "结束", "continue": "注入继续"}),
    "注入FORCE":  Node(run=_inject_force,      edges={"ok": "加载历史"}),
    "注入继续":   Node(run=_inject_continue,   edges={"ok": "加载历史"}),
    "结束":       Node(run=_finish,            edges={}),
}


async def _run_graph(ctx: LoopCtx) -> LoopResult:
    """按声明式状态图执行 Agent Loop"""
    current = "加载历史"
    while current:
        node = _LOOP_NODES[current]
        route = await node.run(ctx)
        current = node.edges.get(route, "")
        if not current and route:
            import logging
            _log = logging.getLogger(__name__)
            _log.warning("Unexpected route key '%s', terminating graph", route)
    return ctx.loop_result or LoopResult(answer="", msg_id="")


async def _chat(
    *,
    Usersend: ChatSendRequest,
    user_uuid: str,
    request_id: str,
) -> ChatSendResponse:
    """处理单次聊天轮次的核心逻辑（Agent Loop）"""
    # 1. 权限校验
    if not db.access.validate_project_session(user_uuid=user_uuid, pid=Usersend.pid, sid=Usersend.sid):
        _err(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Resource not found",
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
            retryable=False,
        )

    # 2. 保存用户消息
    user_message = ModelRequest(parts=[UserPromptPart(content=Usersend.user_input)])
    db.messages.create_for_user(
        sid=Usersend.sid,
        user_uuid=user_uuid,
        kind="user",
        raw_json=_to_json(user_message),
    )

    # 3. 计算有效工具集合（后端白名单 ∩ 前端请求）
    effective_allowed_tools = effective_tools(Usersend.allowed_tools)

    if Usersend.tool_mode == ToolMode.FORCE and not effective_allowed_tools:
        _err(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="FORCE_MODE_NO_ALLOWED_TOOLS",
            message="No allowed tools available for force mode",
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
            retryable=False,
            detail={
                "global_allowed_tools": sorted(effective_tools(None)),
                "registered_tools": sorted(get_registered_tool_names()),
            },
        )

    # 4. 构造运行时依赖
    deps = ChatDeps(
        tool_mode=Usersend.tool_mode,
        allowed_tools=effective_allowed_tools,
        pid=Usersend.pid,
        user_uuid=user_uuid,
    )

    # 5. 构造循环上下文，初始化 tracker，调用状态图
    ctx = LoopCtx(
        sid=Usersend.sid,
        user_uuid=user_uuid,
        deps=deps,
        request_id=request_id,
        retry_of_request_id=Usersend.retry_of_request_id,
        tracker=ToolCheck(
            max_tool_loops=MAX_TOOL_LOOPS,
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
        ),
    )
    result = await _run_graph(ctx)

    # 6. 返回响应
    return ChatSendResponse(
        request_id=request_id,
        retry_of_request_id=Usersend.retry_of_request_id,
        assistant_message=result.answer,
        assistant_message_id=result.msg_id,
    )


# ============================================================
# HTTP 路由处理器
# ============================================================


@router.post("/chat/{sid}", response_model=ChatSendResponse, dependencies=[Depends(verify_nonce)])
async def post_chat_message(
    sid: str,
    Usersend: ChatSendRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ChatSendResponse:
    """发送聊天消息 API 端点"""
    request_id = str(uuid.uuid4())

    if sid != Usersend.sid:
        _err(
            status_code=status.HTTP_409_CONFLICT,
            code="SESSION_CONFLICT",
            message="Path sid and body sid mismatch",
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
            retryable=False,
        )

    raw_user_uuid = current_user.get("uuid")
    if not isinstance(raw_user_uuid, str) or not raw_user_uuid:
        _err(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_TOKEN_INVALID",
            message="Invalid user token payload",
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
            retryable=False,
        )
    user_uuid = cast(str, raw_user_uuid)

    try:
        return await _chat(
            Usersend=Usersend,
            user_uuid=user_uuid,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except PermissionError:
        _err(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Resource not found",
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
            retryable=False,
        )
    except Exception as exc:
        _err(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Internal server error",
            request_id=request_id,
            retry_of_request_id=Usersend.retry_of_request_id,
            retryable=True,
            detail={"error": str(exc)},
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


@router.post("/chat/{sid}/regenerate", response_model=RegenerateResponse, dependencies=[Depends(verify_nonce)])
async def regenerate_message(
    sid: str,
    Usersend: RegenerateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> RegenerateResponse:
    """
    重新生成 AI 回复
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
    if not db.access.validate_project_session(user_uuid=user_uuid, pid=Usersend.pid, sid=sid):
        _err(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Resource not found",
            request_id=request_id,
            retry_of_request_id=None,
            retryable=False,
        )

    # 获取目标消息
    target_msg = db.messages.get_for_user(
        msg_id=Usersend.target_msg_id,
        user_uuid=user_uuid,
    )
    if target_msg is None:
        _err(
            status_code=status.HTTP_404_NOT_FOUND,
            code="MESSAGE_NOT_FOUND",
            message="Target message not found",
            request_id=request_id,
            retry_of_request_id=None,
            retryable=False,
        )

    # 校验消息类型必须是 user
    if target_msg["kind"] != "user":
        _err(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_TARGET_MESSAGE",
            message="Can only regenerate from a user message",
            request_id=request_id,
            retry_of_request_id=None,
            retryable=False,
        )

    # 将目标消息之后的所有消息标记为非最新
    target_timestamp = target_msg["timestamp"]
    db.messages.mark_not_latest_after(
        sid=sid,
        timestamp=target_timestamp,
    )

    # 计算新版本号
    new_version = db.messages.get_max_version_for_parent(parent_msg_id=Usersend.target_msg_id) + 1

    # 构造运行时依赖
    effective_allowed_tools = effective_tools(Usersend.allowed_tools)
    deps = ChatDeps(
        tool_mode=Usersend.tool_mode,
        allowed_tools=effective_allowed_tools,
        pid=Usersend.pid,
        user_uuid=user_uuid,
    )

    # 构造循环上下文，初始化 tracker，调用状态图
    ctx = LoopCtx(
        sid=sid,
        user_uuid=user_uuid,
        deps=deps,
        request_id=request_id,
        retry_of_request_id=None,
        parent_msg_id=Usersend.target_msg_id,
        version=new_version,
        tracker=ToolCheck(
            max_tool_loops=MAX_TOOL_LOOPS,
            request_id=request_id,
            retry_of_request_id=None,
        ),
    )
    result = await _run_graph(ctx)

    # 返回响应
    return RegenerateResponse(
        request_id=request_id,
        assistant_message=result.answer,
        assistant_message_id=result.msg_id,
        version=result.version or new_version,
    )


