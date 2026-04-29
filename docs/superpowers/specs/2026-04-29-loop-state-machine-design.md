# Loop 状态机设计文档

> **目标**: 从零重建 loop.py，采用有向图状态机模式。每个逻辑节点封装在 node.py，loop.py 声明图边并驱动引擎。

**架构**: 三层分离 —— context.py（类型+注册表）→ node.py（节点函数）→ loop.py（图声明+引擎+路由）

**技术栈**: PydanticAI Agent、FastAPI SSE Streaming、SQLite via DatabaseFacade

---

## 1. 文件职责

```
context.py         零内部依赖。LoopContext, NodeOutput, LoopGraph, NodeName, ChatDeps, 节点注册表
node.py            import context/config/tool/db。全部节点函数，用 @register_node 注册
loop.py            import context/node/auth/config。LoopGraph 实例声明边、run_loop 引擎、FastAPI router
main.py             保持现状: from loop import router as loop_router（不改动）
```

依赖方向：`context.py ← node.py ← loop.py ← main.py`

---

## 2. 状态机图

```
SEND/REGENERATE entry ──→ VALIDATE ──→ LOAD_HISTORY ──→ BUILD_MESSAGES ──→ CALL_MODEL
STOP entry        ──→ VALIDATE ──→ STOP                                     ↑      │
                         ↓ (fail)                                             │      │
                    STREAM_ERROR                                              │      │
                                                                  重试 self-loop   │
                                                                              │      │
                                                                      ┌───────┘      │
                                                                      │ success       │ error (retries exhausted)
                                                                      ▼              ▼
                                                                   SAVE       STREAM_ERROR
                                                                      │
                                                                      ▼
                                                               STREAM_COMPLETE
```

### 边声明

| 起点 | 终点 | 条件 |
|------|------|------|
| VALIDATE | LOAD_HISTORY | `ctx.action in ("send","regenerate")` |
| VALIDATE | STOP | `ctx.action == "stop"` |
| LOAD_HISTORY | BUILD_MESSAGES | 无条件 |
| BUILD_MESSAGES | CALL_MODEL | 无条件 |
| CALL_MODEL | SAVE | `ctx.error is None` |
| CALL_MODEL | CALL_MODEL | `ctx.error is not None and ctx.retries < 3` |
| CALL_MODEL | STREAM_ERROR | `ctx.error is not None and ctx.retries >= 3` |
| SAVE | STREAM_COMPLETE | 无条件 |

### 两类环

| 环 | 路径 | 触发条件 |
|----|------|----------|
| 工具回环 | CALL_MODEL 内部（PydanticAI Agent 自动） | 模型产出 ToolCall |
| 重试环 | CALL_MODEL → CALL_MODEL | 模型调用异常且未超限 |

工具回环由 PydanticAI `Agent.run_stream()` 内部消化，不产生图层面跃迁。图只看得见"模型调完了，结果如何"。

---

## 3. 类型定义（context.py）

### 3.1 枚举

```python
class ActionKind(StrEnum):
    SEND = "send"
    REGENERATE = "regenerate"
    STOP = "stop"

class NodeName(StrEnum):
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
```

### 3.2 LoopContext

贯穿整个请求生命周期的可变上下文对象。节点读写 ctx，引擎只负责调度。

```python
@dataclass
class LoopContext:
    # 身份与权限
    user_uuid: str
    pid: str
    sid: str
    allowed_tools: set[str] = field(default_factory=set)

    # 入口动作
    action: ActionKind = ActionKind.SEND

    # 消息
    user_input: str = ""
    parent_msg_id: str | None = None
    history_messages: list[ModelMessage] = field(default_factory=list)
    messages: list[ModelMessage] = field(default_factory=list)

    # 模型控制
    retries: int = 0
    tool_rounds: int = 0

    # 响应
    response_text: str = ""
    response_msg_id: str | None = None

    # 错误
    error: str | None = None
    error_code: str | None = None

    # SSE
    sse_queue: asyncio.Queue | None = None
```

### 3.3 NodeOutput

```python
@dataclass
class NodeOutput:
    transition: str = ""       # 非空时引擎绕过图查询直接跳转到此节点
    extra: dict[str, Any] = field(default_factory=dict)
```

### 3.4 ChatDeps

注入 PydanticAI Agent 的依赖对象，桥接 LoopContext → RunContext.deps。

```python
@dataclass(frozen=True)
class ChatDeps:
    user_uuid: str
    pid: str
    sid: str
    allowed_tools: set[str]
    tool_mode: ToolMode = ToolMode.ON
```

### 3.5 节点注册表

```python
_registry: dict[NodeName, Callable] = {}

def register_node(name: NodeName):
    """装饰器将异步函数注册为图节点。同一 name 重复注册会覆盖。"""
    def deco(fn):
        _registry[name] = fn
        return fn
    return deco
```

---

## 4. 节点函数设计（node.py）

全部函数签名：`async def xxx_node(ctx: LoopContext) -> NodeOutput`

### 4.1 VALIDATE

| 项 | 内容 |
|------|------|
| 读取 | `ctx.user_uuid, ctx.pid, ctx.sid, ctx.action, ctx.parent_msg_id` |
| 写入 | `ctx.error, ctx.error_code` |
| 依赖 | `db.access.validate_project_session()`, `db.messages.get_for_user()` |

逻辑：
1. 所有 action 统一走 `validate_project_session(user_uuid, pid, sid)` 归属链校验
2. action=REGENERATE：额外校验 `parent_msg_id` 非空且属于该用户
3. action=SEND：校验 `user_input` 和 `pid` 非空
4. 失败设 `ctx.error_code` → `NodeOutput(transition="STREAM_ERROR")`

### 4.2 LOAD_HISTORY

| 项 | 内容 |
|------|------|
| 读取 | `ctx.sid, ctx.user_uuid, ctx.action, ctx.parent_msg_id` |
| 写入 | `ctx.history_messages` |
| 依赖 | `db.messages.list_latest_by_session_for_user()` |

逻辑：
1. 查询会话最新版消息列表
2. 反序列化每条 `raw_json` → `ModelMessage`
3. REGENERATE 模式：找到 `parent_msg_id` 在历史中的位置，截断只保留之前的消息
4. 写入 `ctx.history_messages`

### 4.3 BUILD_MESSAGES

| 项 | 内容 |
|------|------|
| 读取 | `ctx.history_messages, ctx.user_input, ctx.action` |
| 写入 | `ctx.messages` |
| 依赖 | 无（纯内存组装） |

逻辑：
- SEND：创建 `ModelRequest(user_text)` 追加到 `history_messages` 后
- REGENERATE：直接使用截断后的 `history_messages`
- 作为本轮传给模型的完整消息列表

### 4.4 CALL_MODEL

| 项 | 内容 |
|------|------|
| 读取 | `ctx.messages, ctx.allowed_tools, ctx.retries` |
| 写入 | `ctx.messages, ctx.retries, ctx.response_text, ctx.tool_rounds, ctx.error` |
| 依赖 | `config.create_chat_agent()`, `tool.build_tools()` |

逻辑：
1. 每请求新建 Agent：`create_chat_agent().with_tools(build_tools())`
2. 构建 `ChatDeps` 从 `LoopContext` 提取字段
3. 使用 `agent.run_stream(user_input, deps=ChatDeps(...))` 流式调用
4. 遍历 `stream.stream_events()`：TextPartDelta → SSE推送 + 拼接response_text；ToolCallPart/ToolReturnPart → SSE通知前端
5. PydanticAI 自动处理工具调用循环（Option A 黑盒模式）
6. 完成后读取 `stream.all_messages()` 和 `stream.usage().tool_calls`
7. 异常时：`ctx.error` 设值，不设 `transition`，交由图的 retry 边处理
8. 工具安全由 `tool.py` 的 `_create_guarded_tool` 在 Agent 内部保证

### 4.5 SAVE

| 项 | 内容 |
|------|------|
| 读取 | `ctx.sid, ctx.user_uuid, ctx.messages, ctx.action, ctx.parent_msg_id` |
| 写入 | `ctx.response_msg_id` |
| 依赖 | `db.messages.save_agent_messages()`, `db.sessions.touch_timestamp()` |

逻辑：
1. 调用 `save_agent_messages()` 落库本轮新消息
2. 记录最终 assistant 消息的 `msg_id`
3. 更新 session 时间戳

### 4.6 终止节点

- **STREAM_COMPLETE**：引擎遇此节点自然退出循环
- **STREAM_ERROR**：SSE 层读取 `ctx.error_code` 拼接错误事件
- **STOP**：用户中断，无额外逻辑

---

## 5. 图引擎（loop.py）

### 5.1 LoopGraph 类

```python
ConditionFn = Callable[[LoopContext], bool]
RouterFn = Callable[[LoopContext, list[NodeName]], Coroutine[Any, Any, NodeName]]
NodeFn = Callable[[LoopContext], Coroutine[Any, Any, NodeOutput]]

class LoopGraph:
    def __init__(self):
        self._edges: dict[NodeName, dict[NodeName, ConditionFn | None]] = {}
        self._entry: dict[ActionKind, NodeName] = {}
        self._terminal: set[NodeName] = {STREAM_COMPLETE, STREAM_ERROR, STOP}
        self._router: RouterFn | None = None

    def set_entry(self, action: ActionKind, node: NodeName) -> None: ...
    def add_edge(self, src: NodeName, dst: NodeName, condition: ConditionFn | None = None) -> None: ...
    def set_router(self, fn: RouterFn) -> None: ...
    def entry_node(self, action: ActionKind) -> NodeName: ...
    def next_nodes(self, src: NodeName, ctx: LoopContext) -> list[NodeName]: ...
    def is_terminal(self, node: NodeName) -> bool: ...
    async def route(self, ctx: LoopContext, candidates: list[NodeName]) -> NodeName: ...
```

路由策略：
- 默认：取 candidates 列表中第一条（按 `add_edge` 声明顺序）
- 当 `set_router()` 注入路由 Agent：由 Agent 根据 `ctx` 和候选集动态抉择
- 无候选时：回退到 STREAM_ERROR

### 5.2 run_loop 引擎

```python
MAX_RETRIES = 3

async def run_loop(ctx: LoopContext, entry: NodeName) -> None:
    current = entry
    while True:
        if _graph.is_terminal(current):
            break
        node_fn = _registry.get(current)
        if node_fn is None:
            ctx.error = f"Node not registered: {current}"
            current = NodeName.STREAM_ERROR
            continue
        try:
            output: NodeOutput = await node_fn(ctx)
        except Exception as exc:
            ctx.error = str(exc)
            ctx.error_code = "LOOP_EXECUTION_ERROR"
            current = NodeName.STREAM_ERROR
            continue
        # 节点主动跳转（优先级最高）
        if output.transition:
            current = NodeName(output.transition)
            continue
        # 查图路由
        candidates = _graph.next_nodes(current, ctx)
        if not candidates:
            break
        current = await _graph.route(ctx, candidates)
```

每轮迭代只执行一次 `await node_fn(ctx)`，节点执行时间长短与引擎层无关。CALL_MODEL 可能耗时 30s，VALIDATE 可能 1ms，引擎只负责串起它们。

### 5.3 FastAPI 路由

```python
router = APIRouter(prefix="/loop", tags=["chat"])

class ChatRequest(BaseModel):
    pid: str
    action: str = "send"
    message: str = ""
    parent_msg_id: str | None = None
    allowed_tools: list[str] | None = None

@router.post("/{sid}")
async def chat(sid, payload: ChatRequest, current_user=Depends(get_current_user),
               nonce_ok=Depends(verify_nonce)) -> StreamingResponse:
    ctx = LoopContext(
        user_uuid=current_user["uuid"],
        pid=payload.pid, sid=sid,
        action=ActionKind(payload.action),
        user_input=payload.message,
        parent_msg_id=payload.parent_msg_id,
        allowed_tools=effective_tools(payload.allowed_tools or []),
    )
    return StreamingResponse(
        stream_response(ctx),
        media_type="text/event-stream",
    )
```

### 5.4 SSE 流式响应

```python
async def stream_response(ctx: LoopContext):
    queue: asyncio.Queue = asyncio.Queue()
    ctx.sse_queue = queue
    entry = _graph.entry_node(ctx.action)
    run_task = asyncio.create_task(run_loop(ctx, entry))

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15)
            yield f"data: {json.dumps(event)}\n\n"
        except asyncio.TimeoutError:
            if run_task.done():
                break

    await run_task  # 传播异常
    yield f"data: {json.dumps({'type': 'done', 'msg_id': ctx.response_msg_id})}\n\n"
```

---

## 6. 加载顺序

```
main.py
  ├→ import loop
  │     ├→ import context       # _registry = {}, 类型定义就绪
  │     ├→ import node          # 执行 @register_node → _registry 填充
  │     └→ 声明 _graph          # 图声明，此时 _registry 完整
  └→ app.include_router(loop.router)
```

关键：`node.py` 在 `_graph` 声明前被 import，确保注册表先于图。

---

## 7. 错误码协议

| 错误码 | HTTP 状态码 | 触发场景 |
|--------|-------------|----------|
| AUTH_TOKEN_INVALID | 401 | 无效令牌 |
| NONCE_REPLAY | 409 | 防重放检测 |
| FORBIDDEN | 403 | 归属校验失败 |
| RESOURCE_NOT_FOUND | 404 | 项目/会话/消息不存在 |
| MODEL_CALL_FAILED | 502 | 模型调用重试耗尽 |
| LOOP_EXECUTION_ERROR | 500 | 节点执行异常 |

错误码在 VALIDATE 和 CALL_MODEL 节点写入 `ctx.error_code`，SSE 层读取并组帧。

---

## 8. 对外接口不变清单

以下模块不做任何改动：

| 文件 | 原因 |
|------|------|
| `config.py` | `create_chat_agent()` 等函数被 CALL_MODEL 直接使用 |
| `tool.py` | `build_tools()`, `effective_tools()`, `_create_guarded_tool()` 保持现有逻辑 |
| `db.py` | `save_agent_messages()`, `list_latest_by_session_for_user()`, `validate_project_session()` 保持 |
| `auth.py` | `get_current_user`, `verify_nonce`, JWT 逻辑保持 |
| `data.py` | 数据查询路由保持 |
| `file.py` | 文件操作保持 |
| `main.py` | 只改 import 路径（`from loop import router`），其余不变 |

---

## 9. 后期扩展路径

### 9.1 路由 Agent

```python
async def router_agent(ctx: LoopContext, candidates: list[NodeName]) -> NodeName:
    agent = Agent('openai:gpt-4.1', instructions='你是一个流程路由决策者...')
    result = await agent.run(f"当前状态: {ctx}，可选路径: {candidates}")
    return NodeName(result.output)

_graph.set_router(router_agent)
```

路由 Agent 可以产生任意回环（例如回到 BUILD_MESSAGES 重新组织上下文），图只需增加对应的边声明。

### 9.2 添加新节点

1. `NodeName` 枚举追加值
2. `node.py` 写节点函数并用 `@register_node` 注册
3. `loop.py` 的 `_graph` 加边声明
4. 可能加新的终止节点名

### 9.3 PydanticAI 工具能力扩展

工具特性（审批、重试、校验）在 Agent 层消化，不污染图结构：
- `requires_approval=True` → 危险操作人工确认
- `ModelRetry` → 工具自我纠错
- `args_validator` → 参数预检
- `Capabilities` → 标准能力包注入
