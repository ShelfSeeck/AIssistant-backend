"""
tool.py - AI 工具定义与组装模块

本模块职责：
1. 定义工具函数的执行逻辑（文件读取、目录遍历等）。
2. 维护工具注册表（register_tool / _TOOL_REGISTRY / _REGISTERED_TOOL_NAMES）。
3. 提供 build_tools，根据 allowed 参数过滤并构建 Agent 可用的 Tool 列表。

与其他模块关系：
- loop.py：负责模型编排与重试，通过 build_tools 注入可调用工具。
- data.py / main.py：负责路由和应用挂载，不参与工具执行。
- db.py：不直接耦合；工具如需业务依赖，统一通过 RunContext.deps 获取。

如何新增一个可被 AI 调用的工具：
1. 在本文件新增函数，首参使用 ctx: RunContext[Any]。
2. 返回值约定为 dict[str, Any]（成功/错误都走结构化返回）。
3. 使用 @register_tool 装饰器注册，函数名即工具名。
4. 无需改 loop.py，Agent 启动时会通过 build_tools 自动纳入。

调用链路：
register_tool -> build_tools(allowed=...) -> Agent(tools=...) -> 工具函数执行
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

# 已注册工具名称集合，用于快速查找和权限校验
_REGISTERED_TOOL_NAMES: set[str] = set()

# 工具函数注册表：name → function，由 build_tools 读取并包装为 Tool 对象
_TOOL_REGISTRY: dict[str, Any] = {}


def register_tool(func: Any) -> Any:
    """
    工具注册装饰器。

    行为：
    1. 使用函数名作为工具名写入 _REGISTERED_TOOL_NAMES。
    2. 将函数对象写入 _TOOL_REGISTRY。
    3. 返回原函数，不改变调用方式。

    约定：工具函数签名应为 (ctx: RunContext[Any], ...params) -> dict[str, Any]。
    """
    tool_name = func.__name__
    _REGISTERED_TOOL_NAMES.add(tool_name)
    _TOOL_REGISTRY[tool_name] = func
    return func


def get_registered_tool_names() -> set[str]:
    """
    返回已注册工具名集合的副本。

    返回副本而非原集合，避免外部代码误改内部注册状态。
    """
    return set(_REGISTERED_TOOL_NAMES)


def get_tool_registry() -> dict[str, Any]:
    """
    返回工具注册表副本。

    键为工具名，值为函数对象，供 build_tools 进行统一包装。
    """
    return dict(_TOOL_REGISTRY)


def build_tools(allowed: list[str] | None = None) -> list[Tool[Any]]:
    """根据注册表和 allowed 过滤，构建 Pydantic AI Tool 列表。

    参数:
        allowed: 允许的工具名列表。None 表示返回所有已注册工具。

    返回:
        只包含已注册且在 allowed 范围内的 Tool 对象列表。
    """
    tool_registry = get_tool_registry()
    allowed_set = set(allowed) if allowed else None
    tools: list[Tool[Any]] = []
    for tool_name, func in tool_registry.items():
        if allowed_set is not None and tool_name not in allowed_set:
            continue
        tools.append(Tool(func))
    return tools



# ============================================================
# 工具函数定义区域
# 在此处添加新的工具函数，使用 @register_tool 装饰器注册
# 
# 注意：
# 1. 工具函数的第一个参数必须是 RunContext（Pydantic AI 要求）
# 2. 这里使用 RunContext[Any] 避免循环导入，实际类型是 RunContext[ChatDeps]
# 3. 运行时权限与安全校验由本模块的 _create_guarded_tool 保证
# 4. 工具必须带有说明，只要在修饰器修饰的那个函数做好""""""的注释即可，可以把参数和目的写好点
# ============================================================

@register_tool
def file_operation(
    ctx: RunContext[Any],
    scope: str,
    method: str,
    args: dict
) -> dict[str, Any]:
    """
    执行文件系统操作（项目文件或个人用户文件）。
    
    参数:
    - scope: 操作范围。可选值为 "project" (操作当前项目文件夹内容) 或 "user" (操作用户个人空间内容)
    - method: 操作方法名 (create_file, delete_file, create_dir, delete_dir, read_file, search_dir)
    - args: 传给该方法的字典参数。例如 {"path": "test.txt", "content": "hello"}
    """
    from backend.file import filesystem_tool_handler
    
    deps = ctx.deps
    pid = getattr(deps, "pid", None) if scope == "project" else None
    user_uuid = getattr(deps, "user_uuid", None)
    
    return filesystem_tool_handler(ctx, method, args, pid=pid, user_uuid=user_uuid)
