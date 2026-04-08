# Stage 4: Integration - 全链路深度拆解

## 0. 逻辑流转图 (Workflow Diagram)
```mermaid
graph TD
    A[/chat request] --> B[_run_model_with_retry]
    B --> C{Model error?}
    C -- yes --> D[retry up to MAX_MODEL_RETRIES]
    D --> E[_raise_api_error 502/429]
    C -- no --> F[Agent output]
    G[/auth/login] --> H[create_access_token + create_refresh_token]
    H --> I[HttpOnly cookie set]
    J[/auth/refresh] --> K[decode refresh token + rotate]
```

## 第一部分：核心解析

### 单元 1: 模型重试和错误映射 (`loop.py`)
```python
def _run_model_with_retry(...):
    for attempt in range(1, MAX_MODEL_RETRIES + 1):
        try:
            return _CHAT_AGENT.run_sync(...)
        except UsageLimitExceeded as exc:
            _raise_api_error(status_code=429, code="TOOL_LOOP_LIMIT_EXCEEDED", ...)
        except (ModelAPIError, ModelHTTPError, AgentRunError) as exc:
            if attempt == MAX_MODEL_RETRIES:
                _raise_api_error(status_code=502, code="MODEL_UPSTREAM_ERROR", ...)
```

逐行解析:
- `range(1, N+1)` 让日志里的重试次数从 1 开始，便于观察。
- `UsageLimitExceeded` 归类为客户端侧配额问题（429）。
- 上游模型失败归类为网关问题（502）。

工程化建议:
- 增加指数退避和抖动，避免雪崩式重试。

### 单元 2: JWT 生命周期 (`auth.py`)
```python
def _build_token(user_uuid: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_uuid, "type": token_type, "iat": int(now.timestamp()), "exp": int((now + expires_delta).timestamp())}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
```

逐行解析:
- `iat/exp` 用 Unix 时间戳，跨语言兼容。
- `type` 区分 access/refresh，防止 token 混用。
- `jwt.encode` 依赖 `JWT_SECRET` 和算法签名。

### 单元 3: 刷新令牌轮换 (`auth.py`)
```python
@router.post("/refresh")
def refresh_access_token(request: Request, response: Response) -> AccessTokenOut:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    token_payload = decode_token(refresh_token, expected_type="refresh")
    access_token = create_access_token(user_uuid)
    new_refresh_token = create_refresh_token(user_uuid)
    _set_refresh_cookie(response, new_refresh_token)
```

逐行解析:
- 从 HttpOnly Cookie 读取 refresh，避免 JS 直接访问。
- refresh 成功后旋转新的 refresh token，降低泄漏窗口。

## 第二部分：Under-the-Hood 专题

### 库设计初衷
- `PyJWT`: 轻量 JWT 编解码，强调标准 claims（exp/iat/sub）。
- `pydantic-ai`: 把 LLM 交互封装为“结构化输入输出 + 工具调用协议”。

### 外部格式到内存对象
- JWT payload: `dict[str, Any]` -> JSON 字符串 -> Base64Url token。
- 模型消息: Python 对象 (`ModelMessage`) <-> JSON (`to_json/validate_json`)。

### 异常捕获真实意图
- 认证层捕获 token 解析错误并统一 401，避免泄漏内部签名细节。
- 编排层把模型异常降维为标准错误码，便于前端重试策略。

## 第三部分：关联跳转
- `loop.py:_run_model_with_retry` 失败时跳转 `_raise_api_error`。
- `auth.py:refresh_access_token` 会跳 `db.py:get_user_by_uuid` 做用户存在性校验。

## MVP 实战 Lab：统一重试策略 + 认证轮换增强
- 任务背景: 集成层是最常见故障入口。
- 需求规格:
  - 输入: 任意可失败上游调用函数。
  - 输出: 成功结果或标准错误对象。
  - 异常: 支持重试上限、错误分类。
- 参考路径: `loop.py`, `auth.py`。
- 提交要求:
  - 在 `docs/study_notes/labs/lab_stage4_core.py` 实现 `retry_call(func, retries, backoff)`。
  - 增加 `jti` 到 refresh token payload，并演示轮换前后 token 不同。

### Applied Lab（可选）
- 场景: 为第三方 HTTP 客户端封装 circuit breaker。

## 引导式 Review Hint
1. 你的重试是否区分“可重试错误”和“不可重试错误”？
2. refresh token 轮换后，旧 token 是否明确失效策略？
