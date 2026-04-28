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
