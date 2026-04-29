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
    """节点函数返回值。

    transition 非空时引擎直接跳转该节点，否则按图查询路由。
    """

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


# ── 节点函数签名 ──

NodeFn = Callable[[LoopContext], Coroutine[Any, Any, NodeOutput]]
"""节点函数: async def xxx(ctx: LoopContext) -> NodeOutput"""

ConditionFn = Callable[[LoopContext], bool]
"""条件函数: def xxx(ctx: LoopContext) -> bool"""

RouterFn = Callable[[LoopContext, list[NodeName]], Coroutine[Any, Any, NodeName]]
"""路由函数: async def xxx(ctx: LoopContext, candidates: list[NodeName]) -> NodeName"""

# ── 节点注册表 ──

_registry: dict[NodeName, NodeFn] = {}


def register_node(name: NodeName):
    """装饰器：将异步函数注册为图节点。

    同一 name 重复注册会覆盖。
    """

    def deco(fn: NodeFn) -> NodeFn:
        _registry[name] = fn
        return fn

    return deco


# ── 有向状态机图 ──


class LoopGraph:
    """有向状态机图：声明节点间的转换边及条件。

    边由 add_edge 声明，条件函数从 LoopContext 读取信息做判断。
    run_loop 引擎在每步查图决定下一跳。
    后期可通过 set_router() 注入路由 Agent 替代默认策略。
    """

    def __init__(self):
        self._edges: dict[NodeName, dict[NodeName, ConditionFn | None]] = {}
        self._entry: dict[ActionKind, NodeName] = {}
        self._terminal: set[NodeName] = {
            NodeName.STREAM_COMPLETE,
            NodeName.STREAM_ERROR,
            NodeName.STOP,
        }
        self._router: RouterFn | None = None

    # ── 声明 API ──

    def set_entry(self, action: ActionKind, node: NodeName) -> None:
        """设置 action 对应的入口节点。"""
        self._entry[action] = node

    def add_edge(self, src: NodeName, dst: NodeName, condition: ConditionFn | None = None) -> None:
        """添加从 src 到 dst 的有向边。condition 为 None 表示无条件通过。"""
        self._edges.setdefault(src, {})[dst] = condition

    def set_router(self, fn: RouterFn) -> None:
        """注入自定义路由函数，替代默认的'取第一条候选'策略。"""
        self._router = fn

    # ── 查询 API ──

    def entry_node(self, action: ActionKind) -> NodeName:
        return self._entry[action]

    def next_nodes(self, src: NodeName, ctx: LoopContext) -> list[NodeName]:
        """从 src 出发，返回所有满足条件的候选 destination。"""
        candidates: list[NodeName] = []
        for dst, cond in self._edges.get(src, {}).items():
            if cond is None or cond(ctx):
                candidates.append(dst)
        return candidates

    def is_terminal(self, node: NodeName) -> bool:
        """判断是否为终止节点或无出边。"""
        return node in self._terminal or node not in self._edges

    async def route(self, ctx: LoopContext, candidates: list[NodeName]) -> NodeName:
        """从候选集中决定下一节点。

        默认策略: 取列表第一条。当 router 注入后，由路由 Agent 决定。
        """
        if self._router is not None:
            return await self._router(ctx, candidates)
        return candidates[0] if candidates else NodeName.STREAM_ERROR
