"""测试 loop_nodes 模块的节点函数和图的正确性"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，确保能从 tests/ 目录导入顶层模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_nodes import (
    Node,
    _check_quota,
    _update_tracker,
)


class TestNode:
    """Node 数据类基本行为"""

    def test_node_holds_run_and_edges(self):
        async def dummy(ctx):
            return "next"

        node = Node(run=dummy, edges={"next": "终点"})
        assert node.run is dummy
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
        ctx = MagicMock()
        ctx.result.usage.return_value.tool_calls = 0
        ctx.output.tool_in_progress = 1
        ctx.tracker.should_force_continue.return_value = True

        result = await _update_tracker(ctx)
        assert result == "force"

    @pytest.mark.asyncio
    async def test_returns_final_when_tool_in_progress_is_zero(self):
        ctx = MagicMock()
        ctx.result.usage.return_value.tool_calls = 0
        ctx.output.tool_in_progress = 0
        ctx.tracker.should_force_continue.return_value = False

        result = await _update_tracker(ctx)
        ctx.tracker.update_usage.assert_called_once_with(0, True)
        assert result == "final"

    @pytest.mark.asyncio
    async def test_returns_continue_when_still_needs_tools(self):
        ctx = MagicMock()
        ctx.result.usage.return_value.tool_calls = 1
        ctx.output.tool_in_progress = 1
        ctx.tracker.should_force_continue.return_value = False

        result = await _update_tracker(ctx)
        ctx.tracker.update_usage.assert_called_once_with(1, False)
        assert result == "continue"
