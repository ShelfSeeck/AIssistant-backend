"""
tool.py - 工具函数定义模块

本模块专门用于定义供 AI Agent 调用的工具函数。
所有工具函数通过 register_tool 装饰器注册到全局工具注册表，
然后由 loop.py 在创建 Agent 时通过 Tool(...) 包装后传入。

架构设计：
- tool.py: 定义工具函数的纯实现 + 工具注册表 + 全局工具权限配置
- loop.py: Agent 创建、工具绑定（使用 tools=[Tool(...)]）、路由逻辑

这种分离避免了循环导入问题，同时让工具的添加/修改更加清晰。

数据流概览：
┌─────────────────────────────────────────────────────────────────────┐
│                          工具调用数据流                               │
├─────────────────────────────────────────────────────────────────────┤
│  1. 注册阶段 (启动时)                                                 │
│     @register_tool 装饰器                                            │
│         ↓                                                           │
│     函数名 → _REGISTERED_TOOL_NAMES (集合)                           │
│     函数对象 → _TOOL_REGISTRY (字典)                                  │
│         ↓                                                           │
│     loop.py 调用 get_tool_registry() 获取并包装为 Tool 对象           │
│                                                                     │
│  2. 权限过滤阶段 (每次请求)                                           │
│     ALLOWED_TOOLS_GLOBAL (后端全局配置)                               │
│         ∩                                                           │
│     request.allowed_tools (前端请求指定)                              │
│         ↓                                                           │
│     effective_tools() → 最终可用工具集合                              │
│                                                                     │
│  3. 调用阶段 (AI 决定调用工具时)                                       │
│     AI 模型生成参数 (path, encoding 等)                               │
│         +                                                           │
│     RunContext.deps (开发者注入的依赖: user_id, db 等)                │
│         ↓                                                           │
│     工具函数执行 → 返回 dict 结果 → AI 模型接收并继续对话              │
└─────────────────────────────────────────────────────────────────────┘

参考 Pydantic AI 文档：
- 工具定义在独立模块时，使用 tools=[Tool(fn)] 在 Agent 构造函数中传入
- Tool 包装器支持 prepare 参数用于动态过滤工具
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from config import BASE_DIR


# ============================================================
# 全局配置
# ============================================================

# 后端全局允许的工具白名单
# - None: 允许所有已注册的工具
# - set[str]: 只允许指定的工具（必须是已注册的）
# 这是安全边界，前端请求只能在此范围内进一步限制，不能扩展
ALLOWED_TOOLS_GLOBAL: set[str] | None = {
    "read_workspace_file",
    "list_workspace_dir",
}

# ============================================================
# 工具注册表（内部状态）
# ============================================================

# 已注册工具名称集合，用于快速查找和权限校验
_REGISTERED_TOOL_NAMES: set[str] = set()

# 工具函数注册表：name → function，由 loop.py 读取并包装为 Tool 对象
_TOOL_REGISTRY: dict[str, Any] = {}


def register_tool(func: Any) -> Any:
    """
    工具注册装饰器 - 将函数注册到全局工具表
    
    数据流：
    ┌─────────────────────────────────────────────────────────┐
    │  @register_tool                                         │
    │  def my_tool(ctx, param): ...                           │
    │       ↓                                                 │
    │  func.__name__ ("my_tool")                              │
    │       ↓                                                 │
    │  _REGISTERED_TOOL_NAMES.add("my_tool")  # 名称注册      │
    │  _TOOL_REGISTRY["my_tool"] = func       # 函数存储      │
    │       ↓                                                 │
    │  返回原函数（不修改）                                    │
    └─────────────────────────────────────────────────────────┘
    
    输入：被装饰的函数
    输出：原函数（装饰器透传）
    副作用：填充 _REGISTERED_TOOL_NAMES 和 _TOOL_REGISTRY
    
    注意：工具函数签名必须为 (ctx: RunContext[Any], ...params) -> dict
    """
    tool_name = func.__name__
    _REGISTERED_TOOL_NAMES.add(tool_name)
    _TOOL_REGISTRY[tool_name] = func
    return func


def get_registered_tool_names() -> set[str]:
    """
    获取所有已注册工具名称
    
    输入：无
    输出：工具名称集合的副本（防止外部修改内部状态）
    调用方：loop.py 中的权限校验逻辑
    """
    return set(_REGISTERED_TOOL_NAMES)


def get_tool_registry() -> dict[str, Any]:
    """
    获取工具注册表
    
    输入：无
    输出：{工具名: 函数对象} 字典的副本
    调用方：loop.py._build_tools() 用于构建 Agent 的工具列表
    """
    return dict(_TOOL_REGISTRY)


def effective_tools(request_allowed_tools: list[str] | None) -> set[str]:
    """
    计算本次请求的有效工具集合（权限交集）
    
    数据流：
    ┌─────────────────────────────────────────────────────────┐
    │  _REGISTERED_TOOL_NAMES          (所有已注册的工具)      │
    │       ∩                                                 │
    │  ALLOWED_TOOLS_GLOBAL            (后端白名单)            │
    │       ↓                                                 │
    │  global_allowed                  (后端允许的工具)        │
    │       ∩                                                 │
    │  request_allowed_tools           (前端请求指定)          │
    │       ↓                                                 │
    │  返回最终可用工具集合                                    │
    └─────────────────────────────────────────────────────────┘
    
    输入：request_allowed_tools - 前端请求中指定的工具列表（可选）
    输出：本次请求实际可用的工具名称集合
    
    安全设计：
    - 后端 ALLOWED_TOOLS_GLOBAL 是硬边界，前端无法突破
    - 前端只能在后端允许范围内进一步限制
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
# 3. 运行时的类型安全由 loop.py 中的 guarded wrapper 保证
# ============================================================


@register_tool
def read_workspace_file(ctx: RunContext[Any], path: str) -> dict[str, Any]:
    """读取工作区内的文件内容。"""
    try:
        target = _resolve_workspace_path(path)
    except ValueError as exc:
        return {"error": "invalid_path", "message": str(exc)}

    if not target.exists():
        return {"error": "file_not_found", "path": path}
    if target.is_dir():
        return {"error": "path_is_directory", "path": path}

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": "binary_file_not_supported", "path": path}

    relative = target.relative_to(BASE_DIR)
    return {
        "path": str(relative).replace("\\", "/"),
        "content": content,
    }


@register_tool
def list_workspace_dir(ctx: RunContext[Any], path: str = ".") -> dict[str, Any]:
    """列出工作区内的目录内容。"""
    try:
        target = _resolve_workspace_path(path)
    except ValueError as exc:
        return {"error": "invalid_path", "message": str(exc)}

    if not target.exists():
        return {"error": "directory_not_found", "path": path}
    if not target.is_dir():
        return {"error": "path_is_not_directory", "path": path}

    items: list[str] = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
        suffix = "/" if child.is_dir() else ""
        items.append(f"{child.name}{suffix}")

    relative = target.relative_to(BASE_DIR)
    return {
        "path": str(relative).replace("\\", "/"),
        "items": items,
    }
