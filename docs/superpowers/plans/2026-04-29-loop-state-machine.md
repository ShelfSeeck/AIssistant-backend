# Loop State Machine Implementation Plan

> **For agentic workers:** Execute task-by-task. Each task ends with a commit.

**Goal:** Create context.py → node.py → loop.py from scratch, building a state-machine-driven chat loop.

**Architecture:** context.py holds types + registry. node.py defines node functions registered via `@register_node`. loop.py declares `LoopGraph` edges + `run_loop` engine + FastAPI router.

**Tech Stack:** Python 3.13+, PydanticAI, FastAPI, SQLite

---

### Task 1: Create context.py — types and registry

**Files:**
- Create: `context.py`

- [ ] **Step 1: Write context.py**

```python
"""
context.py - 类型定义与节点注册表

职责：
1. 定义 LoopContext（请求级可变上下文）、NodeOutput（节点返回值）、
   ChatDeps（注入 PydanticAI Agent）、LoopGraph（有向状态机图）等核心类型
2. 维护节点注册表 _registry 和 register_node 装饰器
3. 零内部依赖，由 node.py 和 loop.py 导入
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic_ai.messages import ModelMessage


class ActionKind(StrEnum):
    """HTTP body action 字段驱动入口选择。"""
    SEND = "send"
    REGENERATE = "regenerate"
    STOP = "stop"


class NodeName(StrEnum):
    """图中所有节点统一命名。"""
    VALIDATE = "validate"
    LOAD_HISTORY = "load_history"
    BUILD_MESSAGES = "build_messages"
    CALL_MODEL = "call_model"
    SAVE = "save"
    STREAM_COMPLETE = "stream_complete"
    STREAM_ERROR = "stream_error"
    STOP = "stop"


class ToolMode(StrEnum):
    ON = "on"
    OFF = "off"
    AUTO = "auto"


@dataclass
class LoopContext:
    """贯穿请求生命周期的可变上下文。节点读写 ctx，run_loop 只负责调度。"""

    user_uuid: str
    pid: str
    sid: str
    allowed_tools: set[str] = field(default_factory=set)

    action: ActionKind = ActionKind.SEND

    user_input: str = ""
    parent_msg_id: str | None = None
    history_messages: list[ModelMessage] = field(default_factory=list)
    messages: list[ModelMessage] = field(default_factory=list)

    retries: int = 0
    tool_rounds: int = 0

    response_text: str = ""
    response_msg_id: str | None = None

    error: str | None = None
    error_code: str | None = None

    sse_queue: asyncio.Queue | None = field(default=None, repr=False)


@dataclass
class NodeOutput:
    """节点函数返回值。transition 非空时引擎直接跳转该节点，否则按图查询。"""

    transition: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatDeps:
    """注入 PydanticAI Agent 的依赖对象。

    在 CALL_MODEL 节点从 LoopContext 构建，工具函数通过 RunContext.deps 访问。
    """
    user_uuid: str
    pid: str
    sid: str
    allowed_tools: set[str]
    tool_mode: ToolMode = ToolMode.ON


# ── 节点注册表 ──

# 节点函数签名: async def xxx(ctx: LoopContext) -> NodeOutput
NodeFn = Callable[[LoopContext], Coroutine[Any, Any, NodeOutput]]
# 条件函数签名: (ctx) -> bool
ConditionFn = Callable[[LoopContext], bool]
# 路由函数签名: async def xxx(ctx, candidates) -> NodeName
RouterFn = Callable[[LoopContext, list[NodeName]], Coroutine[Any, Any, NodeName]]

_registry: dict[NodeName, NodeFn] = {}


def register_node(name: NodeName):
    """装饰器：将异步函数注册为图节点。"""
    def deco(fn: NodeFn) -> NodeFn:
        _registry[name] = fn
        return fn

    return deco
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "from context import LoopContext, NodeOutput, NodeName, ChatDeps, ToolMode, ActionKind, register_node; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add context.py
git commit -m "feat: add context.py with types and node registry"
```

---

### Task 2: Create node.py — node functions

**Files:**
- Create: `node.py`

- [ ] **Step 1: Write node.py**

Nodes: validate_node, load_history_node, build_messages_node, call_model_node, save_node.

```python
"""node.py - 状态机节点函数集合。

每个节点函数通过 @register_node 注册，签名统一为:
    async def xxx_node(ctx: LoopContext) -> NodeOutput

节点函数只负责业务逻辑，不控制流程去向 —— 流程由图 + run_loop 决定。
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest
from pydantic_ai.agent import StreamEvent

from config import create_chat_agent, DATABASE_PATH
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


@register_node(NodeName.VALIDATE)
async def validate_node(ctx: LoopContext) -> NodeOutput:
    """校验请求归属与合法性。

    所有 action 都通过归属链验证。generate 额外校验 parent_msg_id。
    """
    db = DatabaseFacade(db_path=DATABASE_PATH)

    # 归属校验：user → project → session
    if not db.access.validate_project_session(
        user_uuid=ctx.user_uuid,
        pid=ctx.pid,
        sid=ctx.sid,
    ):
        ctx.error = "Access denied"
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
    """加载会话最新消息历史，并反序列化为 ModelMessage 列表。"""
    db = DatabaseFacade(db_path=DATABASE_PATH)

    raw_messages = db.messages.list_latest_by_session_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
    )

    history: list[ModelMessage] = []
    for m in raw_messages:
        history.append(ModelMessage.from_json(m["raw_json"]))

    # regenerate 时截断到 parent_msg_id 之前的消息
    if ctx.action == ActionKind.REGENERATE:
        cutoff = -1
        for i, msg in enumerate(history):
            if msg.msg_id == ctx.parent_msg_id:
                cutoff = i
                break
        if cutoff >= 0:
            history = history[:cutoff]

    ctx.history_messages = history
    return NodeOutput()


@register_node(NodeName.BUILD_MESSAGES)
async def build_messages_node(ctx: LoopContext) -> NodeOutput:
    """组装本轮传给模型的完整消息列表。"""
    if ctx.action == ActionKind.SEND:
        user_msg = ModelRequest.from_text(ctx.user_input)
        ctx.messages = ctx.history_messages + [user_msg]
    else:
        ctx.messages = list(ctx.history_messages)

    return NodeOutput()


@register_node(NodeName.CALL_MODEL)
async def call_model_node(ctx: LoopContext) -> NodeOutput:
    """调用 PydanticAI Agent，以 run_stream 获取流式事件并推送 SSE。

    PydanticAI 内部自动处理工具调用循环，图层面只看最终结果。
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

    try:
        async with agent.run_stream(
            ctx.user_input,
            message_history=ctx.messages[:-1] if len(ctx.messages) > 1 else None,
            deps=deps,
        ) as stream:
            async for event in stream.stream_events():
                await _handle_stream_event(ctx, event)

            ctx.messages = ctx.history_messages + stream.all_messages()
            ctx.tool_rounds = stream.usage().tool_calls

    except Exception as exc:
        ctx.error = str(exc)
        ctx.error_code = "MODEL_CALL_FAILED"

    return NodeOutput()


async def _emit(ctx: LoopContext, event: dict[str, Any]) -> None:
    """向 SSE 队列发送事件。队列不存在时静默跳过。"""
    if ctx.sse_queue is not None:
        await ctx.sse_queue.put(event)


async def _handle_stream_event(ctx: LoopContext, event: Any) -> None:
    """分类处理 PydanticAI 流式事件。"""
    event_type = type(event).__name__

    if event_type == "TextPartDelta":
        delta = event.content
        ctx.response_text += delta
        await _emit(ctx, {"type": "text_delta", "content": delta})

    elif event_type == "ToolCallPart":
        await _emit(ctx, {
            "type": "tool_call",
            "tool_name": event.tool_name,
            "args": str(event.args),
        })

    elif event_type == "ToolReturnPart":
        await _emit(ctx, {
            "type": "tool_result",
            "tool_name": event.tool_name,
        })


@register_node(NodeName.SAVE)
async def save_node(ctx: LoopContext) -> NodeOutput:
    """落库本轮新消息，并更新会话时间戳。"""
    db = DatabaseFacade(db_path=DATABASE_PATH)

    new_messages = [
        m for m in ctx.messages
        if m not in ctx.history_messages
    ]

    if new_messages:
        parent_msg_id = ctx.parent_msg_id if ctx.action == ActionKind.REGENERATE else None
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
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import node; print('node.py OK, registered:', list(node._registry.keys()))"
```

- [ ] **Step 3: Commit**

```bash
git add node.py
git commit -m "feat: add node.py with all state machine nodes"
```

---

### Task 3: Create loop.py — graph, engine, router

**Files:**
- Create: `loop.py`

- [ ] **Step 1: Write loop.py with condition functions, graph declaration, run_loop engine, SSE stream, and FastAPI router**

```python
"""loop.py - 状态机图声明、引擎、SSE 流式响应与 FastAPI 路由。

架构：
- _graph (LoopGraph): 声明节点间的有向边与条件
- run_loop: 引擎核心 —— 取节点 → 执行 → 查图 → 路由 → 循环
  (只对 _registry、_graph 做查询操作)
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
from config import DATABASE_PATH
from context import (
    ActionKind,
    LoopContext,
    LoopGraph,
    NodeName,
    _registry,
)
from db import DatabaseFacade
from tool import effective_tools

# 导入 node 会触发所有 @register_node 装饰器，填充 _registry
import node  # noqa: F401

# ── 条件函数 ──

MAX_RETRIES = 3


def _no_error(ctx: LoopContext) -> bool:
    return ctx.error is None


def _can_retry(ctx: LoopContext) -> bool:
    return ctx.error is not None and ctx.retries < MAX_RETRIES


def _has_error(ctx: LoopContext) -> bool:
    return ctx.error is not None and ctx.retries >= MAX_RETRIES


def _action_is(*actions: str):
    def check(ctx: LoopContext) -> bool:
        return ctx.action.value in actions
    return check


# ── 图声明 ──

_graph = LoopGraph()

# 入口：三种 action 都从 VALIDATE 进入
_graph.set_entry(ActionKind.SEND, NodeName.VALIDATE)
_graph.set_entry(ActionKind.REGENERATE, NodeName.VALIDATE)
_graph.set_entry(ActionKind.STOP, NodeName.VALIDATE)

# VALIDATE 分支
_graph.add_edge(NodeName.VALIDATE, NodeName.STREAM_ERROR, condition=_has_error)
_graph.add_edge(NodeName.VALIDATE, NodeName.LOAD_HISTORY, condition=_action_is("send", "regenerate"))
_graph.add_edge(NodeName.VALIDATE, NodeName.STOP, condition=_action_is("stop"))

# 线形流水
_graph.add_edge(NodeName.LOAD_HISTORY, NodeName.BUILD_MESSAGES)
_graph.add_edge(NodeName.BUILD_MESSAGES, NodeName.CALL_MODEL)

# CALL_MODEL 三向分支
_graph.add_edge(NodeName.CALL_MODEL, NodeName.SAVE, condition=_no_error)
_graph.add_edge(NodeName.CALL_MODEL, NodeName.CALL_MODEL, condition=_can_retry)
_graph.add_edge(NodeName.CALL_MODEL, NodeName.STREAM_ERROR, condition=_has_error)

# 收束
_graph.add_edge(NodeName.SAVE, NodeName.STREAM_COMPLETE)


# ── 引擎 ──

async def run_loop(ctx: LoopContext, entry: NodeName) -> None:
    """状态机引擎核心。

    循环：取当前节点函数 → 执行 → NodeOutput 有主动跳转则跳 → 否则查图决定下一跳。
    遇到终态退出。
    """
    current = entry

    while True:
        # 终止检查
        if _graph.is_terminal(current):
            break

        # 获取节点函数
        node_fn = _registry.get(current)
        if node_fn is None:
            ctx.error = f"Node not registered: {current}"
            ctx.error_code = "LOOP_CONFIG_ERROR"
            current = NodeName.STREAM_ERROR
            continue

        # 执行节点
        try:
            output = await node_fn(ctx)
        except Exception as exc:
            ctx.error = str(exc)
            ctx.error_code = "LOOP_EXECUTION_ERROR"
            current = NodeName.STREAM_ERROR
            continue

        # 节点主动跳转（优先级最高）
        if output.transition:
            current = NodeName(output.transition)
            continue

        # 查图：取满足条件的候选
        candidates = _graph.next_nodes(current, ctx)
        if not candidates:
            break  # 自然终止

        # 路由：当前取第一条候选（后期可替换为路由 Agent）
        current = await _graph.route(ctx, candidates)


# ── SSE 流式响应 ──

async def stream_response(ctx: LoopContext) -> str:
    """SSE 生成器：启动引擎并逐帧消费事件队列。"""
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
    pid: str = Field(..., description="项目 ID")
    action: str = Field(default="send", description="send | regenerate | stop")
    message: str = Field(default="", description="用户输入文本")
    parent_msg_id: str | None = Field(default=None, description="regenerate 时指定的父消息 ID")
    allowed_tools: list[str] | None = Field(default=None, description="前端请求允许的工具列表")


@router.post("/{sid}")
async def chat_loop(
    sid: str,
    payload: ChatRequest,
    current_user: dict = Depends(get_current_user),
    _nonce: None = Depends(verify_nonce),
) -> StreamingResponse:
    """协议驱动入口：POST /loop/{sid}

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
```

- [ ] **Step 2: Verify syntax and import chain**

```bash
python -c "from loop import router, run_loop, _graph; print('loop.py OK'); print('Edges:', {k.value: list(v.keys()) for k, v in _graph._edges.items()})"
```

- [ ] **Step 3: Commit**

```bash
git add loop.py
git commit -m "feat: add loop.py with LoopGraph, run_loop engine and SSE router"
```

---

### Task 4: Verify with main.py

**Files:**
- Modify: `main.py` (possibly — check if import matches)

- [ ] **Step 1: Check main.py import**

```bash
python -c "from main import app; print('main.py OK'); print('Routes:', [r.path for r in app.routes])"
```

- [ ] **Step 2: Fix import if needed**

main.py currently has `from loop import router as loop_router`. loop.py now exports `router = APIRouter(prefix="/loop", ...)`. The import should work as-is.

- [ ] **Step 3: Commit if any changes**

```bash
git diff main.py && git add main.py && git commit -m "fix: update loop import in main.py" || echo "No changes needed"
```

---

### Task 5: Quick smoke test

- [ ] **Step 1: Run server and health check**

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8000 &
sleep 2
curl -s http://127.0.0.1:8000/health | python -m json.tool
kill %1
```

- [ ] **Step 2: Commit any fixes**

```bash
# if fixes needed
git add -A && git commit -m "fix: smoke test adjustments"
```
