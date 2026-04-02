# AI Assistant 架构文档

## 概述

本项目是一个基于 Pydantic AI 的智能助手后端，核心功能是处理用户对话请求并管理工具调用循环。

---

## 模块职责

| 模块 | 职责 |
|------|------|
| `db.py` | 数据库 CRUD 操作，管理用户、项目、会话、消息 |
| `loop.py` | Agent 循环编排，HTTP 路由，消息持久化 |
| `tool.py` | 工具定义与注册 |
| `auth.py` | JWT 认证 |
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
| `msg_timestamp` | REAL | 排序用时间戳 |
| `msg_time` | TEXT | 人类可读时间 |
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

```
POST /chat/{sid}
         │
         ▼
post_chat_message()
    - 验证 JWT，提取 user_uuid
    - 校验 URL 的 sid 与 body 一致
         │
         ▼
_handle_chat_turn()
    1. 权限校验 (_validate_resource_access)
    2. 保存用户消息到 DB
    3. 计算有效工具集 (后端白名单 ∩ 前端请求)
    4. 进入 Agent Loop
         │
         ▼
    ┌─── Agent Loop ───┐
    │                  │
    │  a. 加载历史消息  │ ← 只加载 is_latest=1 的消息
    │  b. 调用 AI 模型  │
    │  c. 保存新消息    │
    │  d. 检查循环条件  │
    │                  │
    └──────────────────┘
         │
         ▼
返回 ChatSendResponse
```

---

## Regenerate（重新生成）流程

```
POST /chat/{sid}/regenerate
         │
         ▼
regenerate_message()
    1. 验证 JWT 和权限
    2. 获取目标用户消息 (target_msg_id)
    3. 校验消息类型必须是 user
         │
         ▼
    4. 将 target 之后的消息标记为 is_latest=0
    5. 计算新版本号 = max(version) + 1
         │
         ▼
    6. 进入 Agent Loop (同正常聊天)
       新消息的 parent_msg_id = target_msg_id
       新消息的 version = 新版本号
         │
         ▼
返回 RegenerateResponse (含 version)
```

### 版本管理说明

- 每条用户消息后的 AI 回复可以有多个版本
- `parent_msg_id` 指向触发生成的用户消息
- `version` 从 1 开始递增
- `is_latest = 1` 的消息会被加载到 AI 对话历史
- 前端可通过 `/messages/{msg_id}/versions` 查询所有版本
- 前端可通过 `/messages/{msg_id}/switch-version` 切换展示版本

---

## Agent Loop 详解

### 循环控制变量

- `total_tool_calls`: 累计工具调用次数，用于限制
- `orchestration_round`: 编排轮次，防止无限循环
- `saw_tool_call`: FORCE 模式下是否已调用过工具

### 循环退出条件

1. `tool_in_progress == 0`: AI 表示已完成，正常退出
2. `orchestration_round > MAX_TOOL_LOOPS`: 超限，抛出 429 错误

### FORCE 模式逻辑

当 `tool_mode == FORCE` 且 AI 未调用工具时：
1. 保存 AI 的回复（kind=agent_response）
2. 注入 TOOL_FORCE_PROMPT 提示
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
# 序列化
from pydantic_core import to_json
raw_json = to_json(message).decode("utf-8")

# 反序列化
from pydantic_ai import ModelMessagesTypeAdapter
messages = ModelMessagesTypeAdapter.validate_json(f"[{raw_json}]")
```

保留完整元数据：timestamp、usage、model_name、run_id 等。

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
| `MAX_TOOL_LOOPS` | 单次请求最大工具调用次数 |
| `MAX_MODEL_RETRIES` | 模型 API 调用重试次数 |
| `ALLOWED_TOOLS_GLOBAL` | 后端工具白名单 |
