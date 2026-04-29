"""loop.py - 状态机图声明、引擎、SSE 流式响应与 FastAPI 路由。

架构：
- _graph (LoopGraph): 声明节点间的有向边与条件，模块加载时静态构建
- run_loop: 引擎核心 —— 取节点 → 执行 → 查图 → 路由 → 循环
- router (FastAPI APIRouter): POST /loop/{sid} 协议驱动入口
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_user, verify_nonce
from context import (
    ActionKind,
    LoopContext,
    LoopGraph,
    NodeName,
    _registry,
)
from tool import effective_tools

# 导入 node 会触发所有 @register_node 装饰器，填充 _registry
import node  # noqa: F401

# ── 常量 ──

MAX_RETRIES = 3

# ── 条件函数 ──
# 签名: (ctx: LoopContext) -> bool
# 由图引擎在每步查询时调用，依据 LoopContext 状态判断边是否可选。


def _no_error(ctx: LoopContext) -> bool:
    return ctx.error is None


def _can_retry(ctx: LoopContext) -> bool:
    return ctx.error is not None and ctx.retries < MAX_RETRIES


def _has_error(ctx: LoopContext) -> bool:
    return ctx.error is not None and ctx.retries >= MAX_RETRIES


def _action_is(*actions: str):
    """返回闭包: 当前 action 在指定集合中时返回 True。"""

    def check(ctx: LoopContext) -> bool:
        return ctx.action.value in actions

    return check


# ── 图声明 ──
# 静态结构，模块加载时构建一次。节点在执行时才查询图决定下一跳。

_graph = LoopGraph()

# 入口: 所有 action 统一从 VALIDATE 进入
_graph.set_entry(ActionKind.SEND, NodeName.VALIDATE)
_graph.set_entry(ActionKind.REGENERATE, NodeName.VALIDATE)
_graph.set_entry(ActionKind.STOP, NodeName.VALIDATE)

# VALIDATE 分支
_graph.add_edge(NodeName.VALIDATE, NodeName.LOAD_HISTORY, condition=_action_is("send", "regenerate"))
_graph.add_edge(NodeName.VALIDATE, NodeName.STOP, condition=_action_is("stop"))

# 线形流水 (VALIDATE 通过后 → LOAD → BUILD → CALL)
_graph.add_edge(NodeName.LOAD_HISTORY, NodeName.BUILD_MESSAGES)
_graph.add_edge(NodeName.BUILD_MESSAGES, NodeName.CALL_MODEL)

# CALL_MODEL 三向分支 (按优先级排列: 正常 / 重试 / 失败)
_graph.add_edge(NodeName.CALL_MODEL, NodeName.SAVE, condition=_no_error)
_graph.add_edge(NodeName.CALL_MODEL, NodeName.CALL_MODEL, condition=_can_retry)
_graph.add_edge(NodeName.CALL_MODEL, NodeName.STREAM_ERROR, condition=_has_error)

# 收束
_graph.add_edge(NodeName.SAVE, NodeName.STREAM_COMPLETE)


# ── 引擎 ──


async def run_loop(ctx: LoopContext, entry: NodeName) -> None:
    """状态机引擎核心。

    循环: 取当前节点函数 → 执行 → NodeOutput 带主动跳转则跳 → 查图决定下一跳。
    遇到终态 (STREAM_COMPLETE / STREAM_ERROR / STOP / 无出边) 退出。
    """
    current = entry

    while True:
        if _graph.is_terminal(current):
            break

        node_fn = _registry.get(current)
        if node_fn is None:
            ctx.error = f"Node not registered: {current}"
            ctx.error_code = "LOOP_CONFIG_ERROR"
            current = NodeName.STREAM_ERROR
            continue

        try:
            output = await node_fn(ctx)
        except Exception as exc:
            ctx.error = str(exc)
            ctx.error_code = "LOOP_EXECUTION_ERROR"
            current = NodeName.STREAM_ERROR
            continue

        # 节点主动跳转（优先级高于图查询）
        if output.transition:
            current = NodeName(output.transition)
            continue

        # 查图: 取满足条件的候选边
        candidates = _graph.next_nodes(current, ctx)
        if not candidates:
            break  # 无候选，自然终止

        # 路由: 当前取第一条候选（后期替换为路由 Agent）
        current = await _graph.route(ctx, candidates)


# ── SSE 流式响应 ──


async def stream_response(ctx: LoopContext) -> str:
    """SSE 生成器: 启动引擎并逐帧消费事件队列。"""
    queue: asyncio.Queue = asyncio.Queue()
    ctx.sse_queue = queue

    entry = _graph.entry_node(ctx.action)
    run_task = asyncio.create_task(run_loop(ctx, entry))

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15)
            yield f"data: {json.dumps(event, default=str)}\n\n"
        except asyncio.TimeoutError:
            if run_task.done():
                break

    # 传播引擎异常（如有）
    await run_task

    # 发送结束帧
    done_event: dict[str, Any] = {"type": "done"}
    if ctx.response_msg_id:
        done_event["msg_id"] = ctx.response_msg_id
    if ctx.error:
        done_event["error"] = ctx.error
        done_event["error_code"] = ctx.error_code
    yield f"data: {json.dumps(done_event, default=str)}\n\n"


# ── FastAPI 路由 ──

router = APIRouter(prefix="/loop", tags=["chat"])


class ChatRequest(BaseModel):
    """POST /loop/{sid} 请求体。action 字段驱动状态机入口选择。"""

    pid: str = Field(..., description="项目 ID")
    action: str = Field(default="send", description="send | regenerate | stop")
    message: str = Field(default="", description="用户输入文本 (action=stop 时可为空)")
    parent_msg_id: str | None = Field(default=None, description="regenerate 时指定的父消息 ID")
    allowed_tools: list[str] | None = Field(default=None, description="前端请求允许的工具列表")


@router.post("/{sid}")
async def chat_loop(
    sid: str,
    payload: ChatRequest,
    current_user: dict = Depends(get_current_user),
    _nonce: None = Depends(verify_nonce),
) -> StreamingResponse:
    """协议驱动入口: POST /loop/{sid}

    body.action 区分 send / regenerate / stop，统一进入状态机引擎。
    """
    user_uuid: str = current_user["uuid"]

    ctx = LoopContext(
        user_uuid=user_uuid,
        pid=payload.pid,
        sid=sid,
        action=ActionKind(payload.action),
        user_input=payload.message,
        parent_msg_id=payload.parent_msg_id,
        allowed_tools=effective_tools(payload.allowed_tools),
    )

    return StreamingResponse(
        stream_response(ctx),
        media_type="text/event-stream",
    )
