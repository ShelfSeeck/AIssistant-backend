"""
tool.py - AI 工具定义与组装模块

本模块职责：
1. 定义工具函数的执行逻辑（文件读取、目录遍历等）。
2. 维护工具注册表（register_tool / _TOOL_REGISTRY / _REGISTERED_TOOL_NAMES）。
3. 处理工具权限边界（ALLOWED_TOOLS_GLOBAL + effective_tools）。
4. 提供 build_tools，把注册函数包装为 Agent 可用的 Tool 列表。

与其他模块关系：
- loop.py：负责模型编排与重试，通过 build_tools 注入可调用工具。
- data.py / main.py：负责路由和应用挂载，不参与工具执行。
- db.py：不直接耦合；工具如需业务依赖，统一通过 RunContext.deps 获取。

如何新增一个可被 AI 调用的工具：
1. 在本文件新增函数，首参使用 ctx: RunContext[Any]。
2. 返回值约定为 dict[str, Any]（成功/错误都走结构化返回）。
3. 使用 @register_tool 装饰器注册，函数名即工具名。
4. 确认工具名在 ALLOWED_TOOLS_GLOBAL 和请求 allowed_tools 的交集内。
5. 无需改 loop.py，Agent 启动时会通过 build_tools 自动纳入。

调用链路：
register_tool -> build_tools -> Agent(tools=...) -> prepare_tools 过滤 -> guarded 校验 -> 工具函数执行
"""

from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from backend.config import BASE_DIR


# ============================================================
# 全局配置
# ============================================================

# 后端全局允许的工具白名单
# - None: 允许所有已注册的工具
# - set[str]: 只允许指定的工具（必须是已注册的）
# 这是安全边界，前端请求只能在此范围内进一步限制，不能扩展
ALLOWED_TOOLS_GLOBAL: set[str] | None = {
    "file_operation",
}

# ============================================================
# 工具注册表（内部状态）
# ============================================================

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



def _create_guarded_tool(func: Any, tool_name: str) -> Any:
    """为工具函数创建带安全检查的包装器。"""

    @wraps(func)
    def guarded(ctx: RunContext[Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        deps = ctx.deps
        registered_tools = get_registered_tool_names()

        if tool_name not in registered_tools:
            return {
                "error": "tool_invalid",
                "tool_name": tool_name,
            }

        if ALLOWED_TOOLS_GLOBAL is not None and tool_name not in ALLOWED_TOOLS_GLOBAL:
            return {
                "error": "tool_not_enabled",
                "tool_name": tool_name,
            }

        tool_mode = getattr(deps, "tool_mode", None)
        tool_mode_value = getattr(tool_mode, "value", tool_mode)
        if tool_mode_value == "off":
            return {
                "error": "tools_disabled",
                "tool_name": tool_name,
            }

        allowed_tools = getattr(deps, "allowed_tools", None)
        if not allowed_tools or tool_name not in allowed_tools:
            return {
                "error": "tool_not_allowed",
                "tool_name": tool_name,
            }

        return func(ctx, *args, **kwargs)

    return guarded


def build_tools() -> list[Tool[Any]]:
    """将注册表中的工具函数包装后构建为 Pydantic AI Tool 列表。"""
    tool_registry = get_tool_registry()
    tools: list[Tool[Any]] = []
    for tool_name, func in tool_registry.items():
        guarded_func = _create_guarded_tool(func, tool_name)
        tools.append(Tool(guarded_func))
    return tools


def effective_tools(request_allowed_tools: list[str] | None) -> set[str]:
    """
    计算本次请求实际可用的工具集合。

    规则：
    1. 先取已注册工具。
    2. 再应用后端全局白名单 ALLOWED_TOOLS_GLOBAL。
    3. 最后与请求级 allowed_tools 求交集。

    结论：前端只能缩小工具范围，不能突破后端白名单。
    """
    # 第一层：已注册的工具
    registered_tools = set(_REGISTERED_TOOL_NAMES)
    
    # 第二层：后端全局白名单过滤
    if ALLOWED_TOOLS_GLOBAL is None:
        global_allowed = registered_tools
    else:
        global_allowed = {name for name in ALLOWED_TOOLS_GLOBAL if name in registered_tools}

    # 第三层：前端请求级别过滤
    if request_allowed_tools is None:
        return global_allowed

    requested = {name.strip() for name in request_allowed_tools if name.strip()}
    return {name for name in requested if name in global_allowed}


def _resolve_workspace_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (BASE_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()

    base = BASE_DIR.resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError("Path is outside workspace root")

    return candidate


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
