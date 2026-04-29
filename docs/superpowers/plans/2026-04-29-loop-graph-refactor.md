# Loop Graph 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `_run_loop` 的过程式 while 循环替换为声明式状态图驱动，提升可读性和可扩展性。

**Architecture:** 新建 `loop_nodes.py` 存放 Node 类 + 8 个状态节点函数；修改 `loop.py` 删除 `_run_loop`、新增图定义 `_LOOP_NODES` 和执行函数 `_run_graph`；`_chat()` 和 `regenerate_message()` 改为调用 `_run_graph()`。节点间通过 `LoopCtx` 传递数据，函数签名统一为 `async (ctx: LoopCtx) -> str`。

**Tech Stack:** Python 3.14, Pydantic AI, FastAPI, dataclasses

---

## 文件分工

| 文件 | 状态 | 职责 |
|------|------|------|
| `loop_nodes.py` | 新建 | Node 类 + NodeFunc 类型 + Prompt 常量 + 8 个状态节点函数 |
| `loop.py` | 修改 | 删除 `_run_loop`，新增 `_LOOP_NODES` + `_run_graph`，`LoopCtx` 扩展，`_chat`/`regenerate_message` 改为图调用 |
| `state.py` | 不变 | — |
| `tool.py` | 不变 | — |
| `db.py` | 不变 | — |

## 图结构（9 节点）

```
加载历史 ────────→ 配额检查 ──[exhausted]──→ 注入结束提示 ──→ 调用模型
                   └[ok]────────────────────→ 调用模型
调用模型 ────────→ 持久化消息 ──→ 计数更新
计数更新 ──[force]───→ 注入FORCE ──→ 加载历史
         ├─[final]───→ 结束
         └─[continue]→ 注入继续 ──→ 加载历史
```

---

### Task 1: 新建 `loop_nodes.py` — Node 类 + Prompt 常量

**Files:**
- Create: `loop_nodes.py`

- [ ] **Step 1: 写模块骨架，包含 Node 类、NodeFunc 类型别名和 prompt 常量**

```python
"""
loop_nodes.py — Agent Loop 状态图节点模块

本模块职责：
1. 定义 Node 类（单节点：执行函数 + 出边映射）
2. 提供 Agent Loop 所需的所有状态节点函数
3. 统一节点函数签名为 async (ctx: LoopCtx) -> str

节点函数通过延迟导入访问 loop.py 中的共享资源（db, _to_history, _to_json, _call_model 等），
避免循环导入。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from pydantic_ai.messages import ModelRequest, UserPromptPart

if TYPE_CHECKING:
    from loop import LoopCtx

# 节点函数签名：接收 ctx，返回路由 key（str）
NodeFunc = Callable[[Any], Awaitable[str]]


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
```

- [ ] **Step 2: 验证模块可导入**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run python -c "from loop_nodes import Node, NodeFunc, TOOL_EXHAUSTED_PROMPT; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add loop_nodes.py
git commit -m "feat: add loop_nodes.py with Node class and prompt constants"
```

---

### Task 2: 迁移 prompt 常量引用

**Files:**
- Modify: `loop.py:53-75`

将 `loop.py` 中的 `TOOL_EXHAUSTED_PROMPT`、`TOOL_FORCE_PROMPT`、`TOOL_CONTINUE_PROMPT` 常量定义改为从 `loop_nodes` 导入。

- [ ] **Step 1: 替换 prompt 常量定义**

将 `loop.py:53-75` 的三段常量：

```python
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

TOOL_EXHAUSTED_PROMPT = (
    "Tool usage limit reached. You cannot call any more tools. "
    "Please provide the best possible final answer based on the information you already have. "
    "Set tool_in_progress to 0."
)
```

替换为：

```python
from loop_nodes import TOOL_EXHAUSTED_PROMPT, TOOL_FORCE_PROMPT, TOOL_CONTINUE_PROMPT

# 模型调用失败时的最大重试次数
MAX_MODEL_RETRIES = 3

# 单次请求中工具调用的最大次数（防止无限循环）
MAX_TOOL_LOOPS = 20
```

- [ ] **Step 2: 验证模块加载无异常**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run python -c "from loop import TOOL_EXHAUSTED_PROMPT, TOOL_FORCE_PROMPT, TOOL_CONTINUE_PROMPT; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add loop.py
git commit -m "refactor: import prompt constants from loop_nodes"
```

---

### Task 3: 扩展 `LoopCtx` — 加节点间数据字段

**Files:**
- Modify: `loop.py:86-99`

- [ ] **Step 1: 在 LoopCtx 中新增字段**

将原来的 `LoopCtx`：

```python
@dataclass
class LoopCtx:
    """
    Agent Loop 循环上下文

    封装循环所需的所有状态，用于 _run_loop 函数。
    通过 parent_msg_id 的有无区分 chat/regenerate 场景。
    """
    sid: str
    user_uuid: str
    deps: "ChatDeps"
    request_id: str
    retry_of_request_id: str | None
    parent_msg_id: str | None = None  # regenerate 专用
    version: int | None = None         # regenerate 专用
```

修改为：

```python
@dataclass
class LoopCtx:
    """
    Agent Loop 循环上下文

    封装循环所需的所有状态，通过 parent_msg_id 的有无区分 chat/regenerate 场景。
    节点间通过额外字段传递中间数据，字段在节点执行过程中逐步填充。
    """
    sid: str
    user_uuid: str
    deps: "ChatDeps"
    request_id: str
    retry_of_request_id: str | None
    parent_msg_id: str | None = None
    version: int | None = None

    # 节点间数据传递（由各节点逐步填充）
    model_history: list["ModelMessage"] = field(default_factory=list)
    result: Any = None              # AgentRunResult
    output: "AgentOutput" | None = None
    final_msg_id: str | None = None
    loop_result: "LoopResult" | None = None
    tracker: "ToolCheck" | None = None
```

并在 `loop.py` 顶部增加 `from dataclasses import dataclass, field`（检查 `import dataclasses` 或 `from dataclasses import dataclass` 现有导入行，加上 `field`）。

- [ ] **Step 2: 验证**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run python -c "from loop import LoopCtx; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add loop.py
git commit -m "feat: extend LoopCtx with inter-node data fields"
```

---

### Task 4: 实现 8 个状态节点函数

**Files:**
- Modify: `loop_nodes.py`

每个节点函数签名统一为 `async def xxx(ctx: LoopCtx) -> str`，返回路由 key。
通过函数内延迟导入访问 `loop.py` 中的 `db`, `_to_history`, `_to_json`, `_call_model`, `_err` 等。

- [ ] **Step 1: 在 loop_nodes.py 尾部依次添加所有节点函数**

在 `loop_nodes.py` 末尾追加以下代码（在 prompt 常量之后）：

```python
# ============================================================
# 状态节点函数
# ============================================================

from typing import cast


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
    if ctx.tracker.is_quota_exceeded():
        return "exhausted"
    return "ok"


async def _inject_exhausted(ctx: LoopCtx) -> str:
    """注入工具配额耗尽提示并重新加载历史"""
    from loop import _to_history, _to_json, db

    exhausted_msg = ModelRequest(parts=[UserPromptPart(content=TOOL_EXHAUSTED_PROMPT)])
    db.messages.create_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
        kind="route_user",
        raw_json=_to_json(exhausted_msg),
        parent_msg_id=ctx.parent_msg_id,
        version=ctx.version,
    )
    history_rows = db.messages.list_latest_by_session_for_user(
        sid=ctx.sid,
        user_uuid=ctx.user_uuid,
    )
    ctx.model_history = _to_history(history_rows)
    return "ok"


async def _call_agent(ctx: LoopCtx) -> str:
    """调用 AI 模型（重试逻辑在 _call_model 内部）"""
    from loop import _call_model, AgentOutput

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
    from loop import LoopResult, db

    db.sessions.touch_timestamp(ctx.sid)
    ctx.loop_result = LoopResult(
        answer=ctx.output.answer if ctx.output else "",
        msg_id=ctx.final_msg_id or "",
        version=ctx.version,
    )
    return ""  # 终端节点，无出边
```

- [ ] **Step 2: 验证所有节点函数可导入**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run python -c "from loop_nodes import _load_history, _check_quota, _inject_exhausted, _call_agent, _persist_messages, _update_tracker, _inject_force, _inject_continue, _finish; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add loop_nodes.py
git commit -m "feat: add 8 state node functions to loop_nodes"
```

---

### Task 5: 重构 `loop.py` — 删 `_run_loop`，加图定义和 `_run_graph`

**Files:**
- Modify: `loop.py:393-534`（删除 `_run_loop`）；
- Modify: `loop.py` 头部 import（新增 `from loop_nodes import Node, ...`）；
- Modify: `loop.py:536-604`（`_chat` 函数内调用改为图执行）；
- Modify: `loop.py:693-787`（`regenerate_message` 内调用改为图执行）

- [ ] **Step 1: 将现有 `from loop_nodes import TOOL_...` 导入行扩展为包含 Node + 全部节点函数**

在 `loop.py` 中找到 Task 2 新增的导入：
```python
from loop_nodes import TOOL_EXHAUSTED_PROMPT, TOOL_FORCE_PROMPT, TOOL_CONTINUE_PROMPT
```

替换为：

```python
from loop_nodes import (
    Node,
    TOOL_CONTINUE_PROMPT,
    TOOL_EXHAUSTED_PROMPT,
    TOOL_FORCE_PROMPT,
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
```

- [ ] **Step 2: 新增图定义和 `_run_graph` 函数**

在 `_call_model` 函数之后、`_run_loop` 之前的位置，插入以下代码：

```python
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
    return ctx.loop_result or LoopResult(answer="", msg_id="")
```

- [ ] **Step 3: 删除 `_run_loop` 函数**

删除 `loop.py:393-534` 的 `_run_loop` 整个函数（包含 docstring 在内的 ~140 行）。

- [ ] **Step 4: 修改 `_chat` 函数中循环调用部分**

将 `_chat` 函数末尾的：

```python
    # 5. 构造循环上下文并调用统一循环
    ctx = LoopCtx(
        sid=Usersend.sid,
        user_uuid=user_uuid,
        deps=deps,
        request_id=request_id,
        retry_of_request_id=Usersend.retry_of_request_id,
    )
    result = await _run_loop(ctx)
```

替换为：

```python
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
```

- [ ] **Step 5: 修改 `regenerate_message` 函数中循环调用部分**

将 `regenerate_message` 函数末尾的：

```python
    # 构造循环上下文并调用统一循环
    ctx = LoopCtx(
        sid=sid,
        user_uuid=user_uuid,
        deps=deps,
        request_id=request_id,
        retry_of_request_id=None,
        parent_msg_id=Usersend.target_msg_id,
        version=new_version,
    )
    result = await _run_loop(ctx)
```

替换为：

```python
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
```

- [ ] **Step 6: 验证整个模块可正常导入**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run python -c "from loop import router; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add loop.py
git commit -m "refactor: replace _run_loop with declarative state graph"
```

---

### Task 6: 写集成测试

**Files:**
- Create: `tests/test_loop_graph.py`

- [ ] **Step 1: 写 Node 类单元测试**

```python
"""测试 loop_nodes 模块的节点函数和图的正确性"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_nodes import (
    Node,
    _check_quota,
)


class TestNode:
    """Node 数据类基本行为"""

    def test_node_holds_run_and_edges(self):
        async def dummy(ctx):
            return "next"

        node = Node(run=dummy, edges={"next": "终点"})
        assert node.edges == {"next": "终点"}

    def test_node_edges_empty(self):
        async def dummy(ctx):
            return ""

        node = Node(run=dummy, edges={})
        assert node.edges == {}


class TestGraphLogic:
    """模拟简化的图执行逻辑，验证路由规则"""

    @pytest.mark.asyncio
    async def test_graph_follows_edges(self):
        """用三节点图验证：执行按 edges 路由到下一节点"""
        execution_log = []

        async def node_a(ctx):
            execution_log.append("a")
            return "to_b"

        async def node_b(ctx):
            execution_log.append("b")
            return "to_c"

        async def node_c(ctx):
            execution_log.append("c")
            return ""  # 终端

        graph = {
            "a": Node(run=node_a, edges={"to_b": "b"}),
            "b": Node(run=node_b, edges={"to_c": "c"}),
            "c": Node(run=node_c, edges={}),
        }

        current = "a"
        while current:
            node = graph[current]
            route = await node.run(None)
            current = node.edges.get(route, "")

        assert execution_log == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_graph_stops_on_unknown_route(self):
        """未知路由 key 应终止执行"""
        execution_log = []

        async def node_a(ctx):
            execution_log.append("a")
            return "unknown"

        graph = {
            "a": Node(run=node_a, edges={"ok": "b"}),
        }

        current = "a"
        while current:
            node = graph[current]
            route = await node.run(None)
            current = node.edges.get(route, "")

        # 只执行了一次，因为 "unknown" 不匹配任何出边
        assert execution_log == ["a"]


class TestCheckQuota:
    """_check_quota 节点函数"""

    @pytest.mark.asyncio
    async def test_returns_exhausted_when_quota_exceeded(self):
        ctx = MagicMock()
        ctx.tracker.is_quota_exceeded.return_value = True
        result = await _check_quota(ctx)
        assert result == "exhausted"

    @pytest.mark.asyncio
    async def test_returns_ok_when_quota_not_exceeded(self):
        ctx = MagicMock()
        ctx.tracker.is_quota_exceeded.return_value = False
        result = await _check_quota(ctx)
        assert result == "ok"


class TestUpdateTracker:
    """_update_tracker 节点函数路由测试"""

    @pytest.mark.asyncio
    async def test_returns_force_when_force_mode_and_no_tool_call(self):
        from loop_nodes import _update_tracker

        ctx = MagicMock()
        ctx.result.usage.return_value.tool_calls = 0
        ctx.output.tool_in_progress = 1
        ctx.tracker.should_force_continue.return_value = True

        result = await _update_tracker(ctx)
        assert result == "force"

    @pytest.mark.asyncio
    async def test_returns_final_when_tool_in_progress_is_zero(self):
        from loop_nodes import _update_tracker

        ctx = MagicMock()
        ctx.result.usage.return_value.tool_calls = 0
        ctx.output.tool_in_progress = 0
        ctx.tracker.should_force_continue.return_value = False
        ctx.tracker.update_usage = MagicMock()

        result = await _update_tracker(ctx)
        assert result == "final"

    @pytest.mark.asyncio
    async def test_returns_continue_when_still_needs_tools(self):
        from loop_nodes import _update_tracker

        ctx = MagicMock()
        ctx.result.usage.return_value.tool_calls = 1
        ctx.output.tool_in_progress = 1
        ctx.tracker.should_force_continue.return_value = False
        ctx.tracker.update_usage = MagicMock()

        result = await _update_tracker(ctx)
        assert result == "continue"
```

- [ ] **Step 2: 运行测试并验证失败/通过**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run pytest tests/test_loop_graph.py -v`

Expected: 7 tests pass (Node 2 + Graph 2 + CheckQuota 2 + UpdateTracker 3，如有因 mock 复杂度导致的失败先修复)

- [ ] **Step 3: 验证应用可启动**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && timeout 5 uv run uvicorn main:app --host 0.0.0.0 --port 8000 2>&1 || true`

Expected: 无 ImportError，能在正常生命周期内启动（可能会因端口或超时退出，但不应该有 traceback）

- [ ] **Step 4: Commit**

```bash
git add tests/test_loop_graph.py
git commit -m "test: add unit tests for graph engine and node functions"
```

---

### Task 7: 最终验证并清理

- [ ] **Step 1: 运行完整测试套件**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && uv run pytest tests/ -v`

Expected: 全部通过

- [ ] **Step 2: 确认 loop.py 行数减少**

Run: `wc -l /home/seeck/项目/AIssistan/AIssistant-backend/loop.py`

Expected: < 650 行（原 790 行）

- [ ] **Step 3: 确认 `_run_loop` 不再存在**

Run: `cd /home/seeck/项目/AIssistan/AIssistant-backend && grep -n "_run_loop" loop.py`

Expected: No output（只应保留 _run_graph 和残留注释引用）

- [ ] **Step 4: Commit（如有残留清理）**

```bash
git add -A
git commit -m "chore: final cleanup after graph refactor"
```
