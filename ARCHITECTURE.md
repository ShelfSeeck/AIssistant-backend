# AI Assistant 架构文档

## 概述

本项目是一个基于 Pydantic AI 的智能助手后端，核心功能是处理用户对话请求并管理工具调用循环。

---

## 模块职责

| 模块 | 职责 |
|------|------|
| `db.py` | `DatabaseFacade` 门面对象与领域数据访问（users/projects/sessions/messages/access） |
| `loop.py` | Agent 循环编排与聊天主路由（`/chat/{sid}`、`/chat/{sid}/regenerate`） |
| `data.py` | 数据查询路由、工具注册表路由、消息版本路由，以及基础健康检查路由 |
| `tool.py` | 工具定义与注册 |
| `auth.py` | JWT 认证 |
| `main.py` | 应用生命周期与路由挂载（不承载业务端点） |
| `config.py` | 配置管理 |

---

## 数据库结构

```
users (用户表)
  └── projects (项目表)
        └── sessions (会话表)
              └── messages (消息表)
```

### messages 表字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `msg_id` | TEXT | 主键 |
| `sid` | TEXT | 所属会话 ID |
| `kind` | TEXT | 消息类型 |
| `raw_json` | TEXT | Pydantic AI ModelMessage 的原始 JSON |
| `timestamp` | REAL | 排序与上下文构建使用的机器时间戳 |
| `created_at` | REAL | 创建时间（机器时间戳） |
| `parent_msg_id` | TEXT | 父消息 ID，用于版本管理 |
| `version` | INTEGER | 版本号（默认 1） |
| `is_latest` | INTEGER | 是否最新版本（1=是，0=否） |

### kind 字段语义

| kind | 对应类型 | 说明 |
|------|----------|------|
| `user` | ModelRequest | 用户输入 |
| `route_user` | ModelRequest | 系统注入的提示（强制工具调用等） |
| `agent_response` | ModelResponse | AI 中间回复（非最终答案） |
| `tool_call` | ModelResponse | AI 调用工具的请求 |
| `tool_result` | ModelRequest | 工具执行返回的结果 |
| `assistant` | ModelResponse | AI 最终回复 |

---

## API 端点

| 方法 | 路径 | 说明 | JWT |
|------|------|------|-----|
| GET | `/users/{user_id}/projects` | 查询用户的项目列表 | ✅ |
| GET | `/projects/{pid}/sessions` | 查询项目的会话列表 | ✅ |
| GET | `/sessions/{sid}/messages` | 查询会话的消息列表（含所有版本） | ✅ |
| POST | `/chat/{sid}` | 发送聊天消息 | ✅ |
| POST | `/chat/{sid}/regenerate` | 重新生成 AI 回复 | ✅ |
| GET | `/messages/{msg_id}/versions` | 查询消息的所有版本 | ✅ |
| POST | `/messages/{msg_id}/switch-version` | 切换消息版本 | ✅ |
| GET | `/tools/registry` | 查询工具注册表 | ❌ |

---

## 聊天请求处理流程

1. `POST /chat/{sid}` 进入 `async post_chat_message()`。
2. 校验 JWT，提取 user_uuid，并校验 path sid 与 body sid 一致。
3. 调用 `async _chat()`：
        - 权限校验：`db.access.validate_project_session`
        - 保存用户消息
        - 计算有效工具集合（后端白名单与请求 allowed_tools 交集）
        - 构造 `LoopCtx` 循环上下文
        - 调用统一的 `_run_loop(ctx)` 进入 Agent Loop
4. Agent Loop 每轮执行（在 `_run_loop` 内）：
        - 加载历史消息（仅 `is_latest=1`）
        - 异步调用 AI 模型（`await _call_model()`）
        - 持久化本轮新消息
        - 按工具状态与上限判断是否继续
5. 结束后返回 `ChatSendResponse`。

---

## Regenerate（重新生成）流程

1. `POST /chat/{sid}/regenerate` 进入 `async regenerate_message()`。
2. 验证 JWT 和资源权限。
3. 获取目标用户消息 `target_msg_id`，并校验目标类型必须是 `user`。
4. 将目标之后消息标记为 `is_latest=0`。
5. 计算新版本号：`max(version) + 1`。
6. 构造 `LoopCtx` 循环上下文（带 `parent_msg_id` 和 `version`）。
7. 调用统一的 `_run_loop(ctx)` 进入与正常聊天一致的 Agent Loop：
   - 新消息 `parent_msg_id = target_msg_id`
   - 新消息 `version = new_version`
8. 返回 `RegenerateResponse`（包含 version）。

### 版本管理说明

- 每条用户消息后的 AI 回复可以有多个版本
- `parent_msg_id` 指向触发生成的用户消息
- `version` 从 1 开始递增
- `is_latest = 1` 的消息会被加载到 AI 对话历史
- 前端可通过 `/messages/{msg_id}/versions` 查询所有版本
- 前端可通过 `/messages/{msg_id}/switch-version` 切换展示版本

---

## Agent Loop 详解

### 统一循环函数：`_run_loop(ctx: LoopCtx) -> LoopResult`

重构后，chat 和 regenerate 两个场景共享同一个异步循环函数。

**输入**：`LoopCtx` 数据类
- `sid`: 会话 ID
- `user_uuid`: 用户 UUID
- `deps`: ChatDeps（工具模式 + 允许工具列表）
- `request_id`: 请求 ID
- `retry_of_request_id`: 重试关联的请求 ID
- `parent_msg_id`: regenerate 场景专用（None = chat 模式）
- `version`: regenerate 场景专用版本号

**输出**：`LoopResult` 数据类
- `answer`: AI 最终回复
- `msg_id`: 消息 ID
- `version`: 版本号（仅 regenerate 有值）

### 循环控制变量

- `total_tool_calls`: 累计工具调用次数，通过 `result.usage().tool_calls` 获取（Pydantic AI 内置）
- `orchestration_round`: 编排轮次，防止无限循环
- `saw_tool_call`: FORCE 模式下是否已调用过工具

### 循环退出条件

1. `tool_in_progress == 0`: AI 表示已完成，正常退出
2. `orchestration_round > MAX_TOOL_LOOPS`: 超限，抛出 429 错误

### FORCE 模式逻辑

当 `tool_mode == FORCE` 且 AI 未调用工具时：
1. 保存 AI 的回复（kind=agent_response）
2. 注入 TOOL_FORCE_PROMPT 提示（kind=route_user，写入数据库）
3. 继续循环

---

## 消息历史结构

Pydantic AI 要求 ModelRequest 和 ModelResponse 交替出现：

### 场景1：简单对话

```
1. user (ModelRequest)
2. assistant (ModelResponse)
```

### 场景2：有工具调用

```
1. user (ModelRequest)
2. tool_call (ModelResponse)      ← AI 决定调用工具
3. tool_result (ModelRequest)     ← 工具返回结果
4. assistant (ModelResponse)      ← 最终回复
```

### 场景3：FORCE 模式，首次未调用工具

```
1. user (ModelRequest)
2. agent_response (ModelResponse) ← 中间回复
3. route_user (ModelRequest)      ← 强制提示
4. tool_call (ModelResponse)
5. tool_result (ModelRequest)
6. assistant (ModelResponse)
```

---

## 消息序列化

使用 Pydantic AI 官方方案：

```python
# 序列化（使用简化函数 _to_json）
from pydantic_core import to_json
raw_json = to_json(message).decode("utf-8")

# 反序列化（使用简化函数 _to_history）
from pydantic_ai import ModelMessagesTypeAdapter
messages = ModelMessagesTypeAdapter.validate_json(f"[{raw_json}]")
```

保留完整元数据：timestamp、usage、model_name、run_id 等。

### 内部辅助函数

| 函数 | 说明 |
|------|------|
| `_err()` | 构造并抛出标准化 API 错误 |
| `_to_history()` | 将数据库记录反序列化为 ModelMessage 列表 |
| `_to_json()` | 将 ModelMessage 序列化为 JSON 字符串 |
| `async _call_model()` | 异步调用 AI 模型（带重试机制） |
| `async _chat()` | 处理聊天请求核心逻辑 |
| `async _run_loop()` | 统一的 Agent Loop 循环函数 |

---

## 工具调用数据流

```
AI 模型决定调用工具
        │
        ▼
_prepare_tools() 过滤可用工具
        │
        ▼
guarded_func 运行时权限校验
        │
        ▼
实际工具函数执行 (tool.py)
        │
        ▼
结果返回 AI 模型
```

---

## 错误处理

### HTTP 状态码

| 状态码 | 场景 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 资源不存在（含权限不足，防枚举） |
| 429 | 工具调用超限 |
| 502 | 模型 API 错误 |

### 错误响应格式

```json
{
  "code": "TOOL_LOOP_LIMIT_EXCEEDED",
  "message": "Tool loop limit exceeded",
  "request_id": "xxx",
  "retryable": true,
  "detail": {}
}
```

---

## 安全设计

1. **权限校验**: 所有操作先验证用户对资源的所有权
2. **统一 404**: 无论资源不存在还是权限不足，都返回 404，防止资源枚举
3. **工具白名单**: 后端白名单 ∩ 前端请求 = 实际可用工具

---

## 配置项

| 配置 | 说明 |
|------|------|
| `MAX_TOOL_LOOPS` | 单次请求最大工具调用次数（默认 20） |
| `MAX_MODEL_RETRIES` | 模型 API 调用重试次数（默认 3） |
| `ALLOWED_TOOLS_GLOBAL` | 后端工具白名单 |

---

## 架构重构历史

### 2026-04-07 重构

**目标**：消除重复代码，简化函数命名，全面异步化

**主要变化**：
1. **提取统一循环**：`_chat()` 和 `regenerate_message()` 中的 ~200 行重复 Agent Loop 代码提取为统一的 `_run_loop()` 函数
2. **新增数据结构**：`LoopCtx` 和 `LoopResult` dataclass 封装循环参数和返回值
3. **函数重命名**：简化 5 个内部函数名（`_raise_api_error` → `_err`，`_build_model_history` → `_to_history` 等）
4. **全面异步化**：所有核心函数改为 `async/await`，使用 `await _CHAT_AGENT.run()` 替代 `run_sync()`
5. **保留可追溯性**：route_user 消息继续作为 kind 存储在数据库中
6. **使用 Pydantic AI 内置特性**：工具调用次数通过 `result.usage().tool_calls` 获取，而非自建计数逻辑

**效果**：
- 代码重复：2 处 → 1 处
- 维护成本：降低 50%（只需维护一处循环逻辑）
- 类型安全：增强（dataclass 明确参数类型）
- 未来扩展：为流式响应打下基础
