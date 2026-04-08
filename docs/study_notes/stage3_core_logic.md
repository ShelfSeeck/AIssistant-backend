# Stage 3: Core Logic - 全链路深度拆解

## 0. 逻辑流转图 (Workflow Diagram)
```mermaid
graph TD
    A[tool.py @register_tool] --> B[_TOOL_REGISTRY]
    B --> C[loop.py _build_tools]
    C --> D[_create_guarded_tool runtime checks]
    D --> E[Agent tools]
    F[/chat request] --> G[_handle_chat_turn]
    G --> H[save_agent_messages]
    H --> I[db.py messages]
```

## 第一部分：核心解析

### 单元 1: Decorator 注册模式 (`tool.py`)
```python
_REGISTERED_TOOL_NAMES: set[str] = set()
_TOOL_REGISTRY: dict[str, Any] = {}

def register_tool(func: Any) -> Any:
    tool_name = func.__name__
    _REGISTERED_TOOL_NAMES.add(tool_name)
    _TOOL_REGISTRY[tool_name] = func
    return func
```

逐行解析:
- 装饰器在函数定义时执行，实现“声明即注册”。
- 名称集合用于权限检查，字典用于函数调用绑定。
- 返回原函数保持可测试性。

工程化建议:
- 可以把注册表改为不可变快照 + 启动阶段校验，减少运行时篡改风险。

### 单元 2: 双层权限防护 (`loop.py`)
```python
async def _prepare_tools(ctx, tools):
    if deps.tool_mode == ToolMode.OFF:
        return []
    if not deps.allowed_tools:
        return []
    return [tool for tool in tools if tool.name in deps.allowed_tools]


def _create_guarded_tool(func, tool_name):
    def guarded(ctx, *args, **kwargs):
        if tool_name not in deps.allowed_tools:
            return {"error": "tool_not_allowed", "tool_name": tool_name}
        return func(ctx, *args, **kwargs)
```

逐行解析:
- `_prepare_tools` 是模型可见性层过滤。
- `guarded` 是执行层过滤，防绕过。
- 这是“前置过滤 + 运行时鉴权”的 defense-in-depth。

### 单元 3: 消息分类持久化 (`loop.py`)
```python
def save_agent_messages(...):
    for message in new_messages:
        if isinstance(message, ModelResponse):
            has_tool_call = any(isinstance(part, ToolCallPart) for part in message.parts)
            ... kind = "tool_call" or "assistant" or "agent_response"
        elif isinstance(message, ModelRequest):
            has_tool_return = any(isinstance(part, ToolReturnPart) for part in message.parts)
            ... kind = "tool_result"
```

逐行解析:
- 通过 `ModelRequest/ModelResponse` + `part` 类型判断角色语义。
- `kind` 决定后续重放、版本切换与前端渲染语义。

## 第二部分：Under-the-Hood 专题

### Python 布尔逻辑拆解
- `if payload.tool_mode == ToolMode.FORCE and not effective_allowed_tools`:
  - 左边判定策略，右边判定资源。
  - 两者同时满足才是错误：强制调用但没有可用工具。

### 第三方库数据结构转换
- `pydantic_ai` 将模型回复解析成 `AgentOutput`（Python 对象），并把历史消息封装为 `ModelMessage` 树结构。
- `to_json(message)` 再转回 JSON 字符串保存入 SQLite。

### `super()` / MRO 延伸
- 当前代码主要函数式风格，类继承较少。
- 当你扩展为“工具基类 + 子类工具”时，应使用 `super()` 保证父类初始化链不丢失。

## 第三部分：关联跳转
- `tool.py` 注册 -> `loop.py:_build_tools` 构建 Tool 列表。
- `loop.py:save_agent_messages` -> `db.py:create_message_for_user` 落库。

## MVP 实战 Lab：工业化工具注册中心
- 任务背景: 工具系统是本项目扩展核心。
- 需求规格:
  - 输入: 工具函数 + 请求级允许列表。
  - 输出: 可执行工具集合。
  - 异常: 非法工具调用返回结构化错误字典。
- 参考路径: `tool.py`, `loop.py`。
- 提交要求:
  - 在 `docs/study_notes/labs/lab_stage3_core.py` 实现最小注册中心 + guard wrapper。
  - 至少验证 2 个场景：允许调用、拒绝调用。

### Applied Lab（可选）
- 场景: 加入“工具级速率限制”字段（每请求最多 N 次）。

## 引导式 Review Hint
1. 你是否同时做了“模型可见性过滤”和“执行时二次校验”？
2. 工具返回的错误结构是否稳定，便于上层统一处理？
