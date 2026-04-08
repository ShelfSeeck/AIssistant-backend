# Stage 7: Quality - 全链路深度拆解

## 0. 逻辑流转图 (Workflow Diagram)
```mermaid
graph TD
    A[testclient.py run_auth_flow_test] --> B[/auth/register]
    B --> C[/auth/login]
    C --> D[/auth/refresh]
    D --> E[/auth/logout]
    E --> F[/auth/refresh should fail]
    F --> G[PASS/FAIL assertion]
```

## 第一部分：核心解析

### 单元 1: 当前最小回归脚本 (`testclient.py`)
```python
def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_auth_flow_test() -> None:
    client = TestClient(app)
    email = f"test_{int(time.time())}@example.com"
    ...
    refresh_after_logout = client.post("/auth/refresh")
    _assert(refresh_after_logout.status_code == 401, "refresh should fail after logout")
```

逐行解析:
- 手写 `_assert` 直观，但缺少测试框架报告能力。
- `time.time()` 生成唯一邮箱避免冲突。
- 用同一个 `TestClient` 保持 cookie 会话上下文。

### 单元 2: 质量缺口识别
- 仅覆盖 happy path，缺少失败路径（错误密码、无 token、越权访问）。
- 没有 fixture 隔离数据库状态。
- 没有 CI 触发，回归依赖人工执行。

### 单元 3: 工程化测试方案（主流）
```python
# 示例结构（推荐）
# tests/
#   conftest.py
#   test_auth.py
#   test_loop_chat.py
#   test_regenerate.py
```

建议实践:
- 使用 pytest fixture 初始化临时数据库。
- 把认证流、聊天流、版本流拆分独立测试文件。
- 增加参数化测试覆盖边界输入。

## 第二部分：Under-the-Hood 专题

### 测试中的内存与隔离
- 每个测试应拥有隔离状态（至少逻辑隔离，最好数据库隔离）。
- 否则前一个测试的写入会污染后一个测试结果。

### 异常断言真实意图
- 不是只看状态码，要断言错误体结构与 `code` 字段，防止回归时语义漂移。

### `super()`/MRO 在测试基类中
- 若构建 `BaseApiTest`，子类测试初始化需 `super().setup_method()` 保留公共夹具行为。

## 第三部分：关联跳转
- `testclient.py` -> `main.py` app -> `auth.py`。
- 后续质量升级需覆盖 `loop.py` 的聊天和 regenerate 端点。

## MVP 实战 Lab：pytest 化最小回归套件
- 任务背景: 没有自动化测试就无法安全重构。
- 需求规格:
  - 输入: API 请求。
  - 输出: 状态码 + 错误体语义。
  - 异常: 失败用例应稳定复现。
- 参考路径: `testclient.py`, `auth.py`, `loop.py`。
- 提交要求:
  - 在 `docs/study_notes/labs/lab_stage7_core.py` 写 3 个 pytest 风格测试函数（可直接运行）。
  - 覆盖：登录成功、错误密码失败、登出后 refresh 失败。

### Applied Lab（可选）
- 场景: 为 `/chat/{sid}` 构建 mock 模型依赖，验证工具循环上限 429。

## 引导式 Review Hint
1. 你的测试是否验证了错误体 `code`，而不仅仅是 HTTP 状态码？
2. 你如何保证测试之间数据库状态互不污染？
