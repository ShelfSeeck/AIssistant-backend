# Loop Graph 重构设计

## 目标

将 `loop.py: _run_loop` 内的过程式 while 循环替换为声明式状态图 + 轻量执行引擎，使主循环读起来像一条清晰的流水线。

## 核心改动

### 状态图

每个步骤（加载历史、配额检查、调用模型、持久化消息……）封装为一个独立的状态节点。节点之间通过路由 key 连接，形成有向图：

```
加载历史 → 配额检查 ──[exhausted]──→ 注入结束提示 ──→ 调用模型
           └──[ok]──────────────────────────────────────→ 调用模型
调用模型 ──[ok]──→ 持久化消息 → 计数更新
         └─[error]→ 抛出502
计数更新 ──[force]───→ 注入FORCE提示 ──→ 加载历史
         ├─[final]───→ 结束
         └─[continue]→ 注入继续提示 ──→ 加载历史
```

节点声明方式（伪代码）：

```python
LOOP_GRAPH = {
    "加载历史":    Node(load_history,      {"ok": "配额检查"}),
    "配额检查":    Node(check_quota,       {"exhausted": "注入结束提示", "ok": "调用模型"}),
    ...
    "结束":        Node(finish,            {}),
}
```

### 执行引擎

一个 ~30 行的 `Graph` 类，循环执行：取当前节点名 → 执行 `node.run(ctx)` → 根据返回值查 `edges` → 跳到下一节点。

### 节点函数约定

所有节点函数签名统一为：

```python
async def xxx(ctx: LoopCtx) -> str:
    ...
    return "ok"   # 路由 key
```

ctx 在节点间传递，承载所有中间状态（详见下方）。

### LoopCtx 扩展

在现有字段基础上新增：

```python
@dataclass
class LoopCtx:
    # 现有字段不变
    sid: str
    user_uuid: str
    deps: ChatDeps
    request_id: str
    retry_of_request_id: str | None
    parent_msg_id: str | None = None
    version: int | None = None

    # 新增：节点间数据传递
    model_history: list[ModelMessage] | None = None
    result: AgentRunResult | None = None
    tracker: ToolCheck | None = None
    final_msg_id: str | None = None
```

## 文件结构

| 文件 | 职责 | 状态 |
|------|------|------|
| `graph.py` | Graph 引擎（Node + Graph 类） | 新建 |
| `loop_nodes.py` | 所有状态节点的 async 函数 | 新建 |
| `loop.py` | 删 `_run_loop`，`_chat` 和 `regenerate` 改为调用 graph.execute() | 修改 |
| `state.py` | ToolCheck 保留，去掉 `from loop import ToolMode` 的循环导入 | 微调 |

## 不变部分

- `_chat()` 的权限校验、消息保存、依赖构造逻辑不变
- `regenerate_message()` 的校验、版本计算逻辑不变
- `_call_model()` 的重试逻辑整个移到"调用模型"节点内部，不拆散
- `ToolCheck` 类的逻辑不动，只断开循环导入
- 所有 Pydantic 模型（ChatSendRequest/Response, AgentOutput 等）不变
- `_err`, `_to_history`, `_to_json` 工具函数不变
- `ChatDeps`, `LoopResult` 数据结构不变
- Agent 单例 `_CHAT_AGENT` 不变

## 不涉及

- 不对 `tool.py`, `db.py`, `auth.py`, `data.py`, `config.py`, `main.py`, `file.py` 做任何修改
- 不改变 API 响应格式
- 不改变数据库 schema
- 不新增任何依赖包
