# Project Learning Plan: AIssistant-backend

> 该计划结合了 repo-scan 的架构索引，优先关注项目核心代码，跳过辅助与构建产物。

## 教学要求
- 每个阶段都要额外讲解至少 1 个“新表达 / 新协议 / 新概念”，不能只停留在业务流程复述。
- 讲解时要给出它的名字、作用、生命周期或调用协议，以及它在本项目里的真实落点。
- 每个阶段的动手练习，最好都补一个“概念验证”小任务，确保学员不只是会改代码，也知道为什么这样写。

## 阶段 1：基础设施与环境 (Infrastructure)
- [ ] **启动装配与配置注入链路**
  - **描述**: 理解服务如何从环境变量装配 FastAPI 应用、数据库初始化与模型实例，解决“配置散落和启动不透明”的问题。
  - **涉及文件**: `main.py`, `config.py`, `pyproject.toml`, `scan-output/AIssistant-backend.md`
  - **资产类型**: Core Asset
  - **关键技术**: FastAPI lifespan, `@asynccontextmanager` 协议, 环境变量配置, 工厂函数 (Factory), 依赖注入思想
  - **动手练习**: 新增 `MODEL_TIMEOUT_SECONDS` 配置项并在 `config.py` 中做默认值与类型转换，启动服务验证不影响现有路由；再补一段 3 行以内的说明，解释 `lifespan` 为什么要写成 `asynccontextmanager`。

- [ ] **运行时配置硬化与安全基线**
  - **描述**: 识别关键配置（如 JWT 密钥）在开发/生产环境中的风险边界，解决“默认配置导致线上事故”的痛点。
  - **涉及文件**: `config.py`, `auth.py`, `ARCHITECTURE.md`
  - **资产类型**: Core Asset
  - **关键技术**: Fail-fast 配置校验, Secret 管理, Secure-by-default
  - **动手练习**: 在启动流程加入 `JWT_SECRET` 为空时的告警或阻断策略（开发态可放行、生产态阻断），并验证行为符合预期。

## 阶段 2：数据流与模型 (Data Focus)
- [ ] **SQLite Schema 与数据关系建模**
  - **描述**: 掌握 `users -> projects -> sessions -> messages` 的层级关系，理解消息版本化字段设计，解决“业务对象和表结构映射不清晰”的问题。
  - **涉及文件**: `db.py`, `ARCHITECTURE.md`, `scan-output/AIssistant-backend.md`
  - **资产类型**: Core Asset
  - **关键技术**: 关系建模, 外键约束, 版本链 (`parent_msg_id`, `version`, `is_latest`)
  - **动手练习**: 为 `messages` 新增一个可选字段（例如 `trace_id`），完成建表兼容更新并写一个最小插入/读取验证脚本。

- [ ] **仓储函数与权限边界查询**
  - **描述**: 理解“用户归属过滤”如何在数据层落地，解决“越权读取风险”。
  - **涉及文件**: `db.py`
  - **资产类型**: Core Asset
  - **关键技术**: Repository Pattern（轻量形态）, 参数化 SQL, Ownership Guard Query
  - **动手练习**: 新增一个 `list_projects_brief_by_user` 函数（只返回 id+name），并在本地调用验证查询结果与权限过滤逻辑一致。

## 阶段 3：核心算法与组件 (Core Logic)
- [ ] **工具系统注册机制与白名单裁剪**
  - **描述**: 理解工具如何注册、发现、请求级过滤，解决“工具扩展后权限失控”的问题。
  - **涉及文件**: `tool.py`, `loop.py`
  - **资产类型**: Core Asset
  - **关键技术**: Decorator 注册模式, Registry Pattern, 集合交集权限模型
  - **动手练习**: 新增一个只读工具（例如返回当前工作区根路径），并通过 `/tools/registry` 验证它是否受全局白名单与请求参数双重限制。

- [ ] **Agent 输出协议与消息序列化路径**
  - **描述**: 学会 `AgentOutput`、`ModelMessage` 在内存与数据库之间的往返转换，解决“AI 输出不可追踪”的问题。
  - **涉及文件**: `loop.py`, `db.py`, `ARCHITECTURE.md`
  - **资产类型**: Core Asset
  - **关键技术**: Pydantic 数据模型, Typed schema 输出约束, 序列化/反序列化适配器
  - **动手练习**: 在 `save_agent_messages` 里为每轮消息增加一个轻量调试字段（例如 `meta.round` 写入 `raw_json` 的附带信息），验证读取历史时不破坏反序列化。

## 阶段 4：通信与外部集成 (Integration)
- [ ] **模型调用与重试边界管理**
  - **描述**: 理解 `_run_model_with_retry` 如何处理上游模型异常并转为标准 API 错误，解决“外部 API 抖动导致链路不稳定”。
  - **涉及文件**: `loop.py`, `config.py`
  - **资产类型**: Core Asset
  - **关键技术**: Retry Pattern, 错误映射（Error Mapping）, Usage 限额控制
  - **动手练习**: 为模型重试增加指数退避（例如 200ms/400ms/800ms），并通过 mock 异常场景观察最终状态码和错误体。

- [ ] **认证链路与 Token 生命周期**
  - **描述**: 理解访问令牌 + HttpOnly 刷新令牌的组合策略，解决“会话续期与安全性平衡”的问题。
  - **涉及文件**: `auth.py`, `db.py`, `testclient.py`
  - **资产类型**: Core Asset
  - **关键技术**: JWT, PBKDF2-HMAC, HttpOnly Cookie, Token Rotation
  - **动手练习**: 添加刷新令牌 `jti` 字段并设计最小内存黑名单机制（开发态），验证登出后刷新立即失效。

## 阶段 5：健壮性与稳定性 (Reliability)
- [ ] **循环终止条件与防无限调用控制**
  - **描述**: 深入 `MAX_TOOL_LOOPS`、`tool_in_progress`、FORCE 模式强制提示，解决“工具链路死循环”风险。
  - **涉及文件**: `loop.py`, `ARCHITECTURE.md`
  - **资产类型**: Core Asset
  - **关键技术**: 状态机思维, Guard Rail, 循环不变量
  - **动手练习**: 人工构造 `tool_in_progress=1` 连续返回场景，验证服务在超限后返回 429 且错误码稳定。

- [ ] **消息版本切换一致性**
  - **描述**: 掌握 `regenerate` 与 `switch-version` 的版本一致性规则，解决“历史分叉后展示错乱”的问题。
  - **涉及文件**: `loop.py`, `db.py`, `ARCHITECTURE.md`
  - **资产类型**: Core Asset
  - **关键技术**: 版本控制（Version Graph 简化形态）, 幂等切换, 数据一致性
  - **动手练习**: 连续两次对同一用户消息 `regenerate`，再切换不同版本并验证 `is_latest` 只有一条为 1。

## 阶段 6：生命周期与控制流程 (Orchestration)
- [ ] **端到端请求编排全景**
  - **描述**: 从 `/chat/{sid}` 入口追踪到权限校验、落库、模型调用、继续提示注入、响应返回，解决“系统行为难以心智建模”的问题。
  - **涉及文件**: `main.py`, `loop.py`, `auth.py`, `db.py`
  - **资产类型**: Core Asset
  - **关键技术**: Orchestrator Pattern, FastAPI `Depends` 依赖解析, 请求作用域对象, 分层职责协作, 统一错误协议
  - **动手练习**: 给主链路增加 `request_id` 贯穿日志（最小 print/structured log 即可），手动发起一次 chat 请求并对齐完整执行轨迹；同时补充一条说明，解释 `Depends(get_current_user)` 属于什么调用协议。

## 阶段 7：质量保证与调试 (Quality)
- [ ] **从脚本验证升级到可回归测试**
  - **描述**: 将当前 `testclient.py` 的 happy path 迁移到标准测试结构，解决“改动后回归不可持续”的问题。
  - **涉及文件**: `testclient.py`, `main.py`, `auth.py`, `loop.py`
  - **资产类型**: Supporting Asset（高价值支撑）
  - **关键技术**: TestClient, pytest 夹具（Fixture）, 场景化断言
  - **动手练习**: 拆分出 3 个测试用例（注册登录成功、错误密码登录失败、登出后刷新失败），并确保可一键执行。

- [ ] **面向重构的热点识别与拆分草图**
  - **描述**: 基于审计结论定位 `loop.py` 与 `db.py` 的高复杂度区域，先做“学习型重构设计”再动刀，降低行为回归风险。
  - **涉及文件**: `scan-output/AIssistant-backend.md`, `loop.py`, `db.py`
  - **资产类型**: Core Asset
  - **关键技术**: 模块提纯（Extract Module）, 复杂度控制, 变更风险评估
  - **动手练习**: 先仅抽取 `_handle_chat_turn` 内一个子步骤为独立私有函数（不改业务行为），跑通现有联调脚本确认行为一致。

## 非核心资产处理建议（简述）
- [ ] **第三方与构建资产认知**
  - **描述**: 对第三方依赖做“会用+会评估”即可，无需深入源码细节。
  - **涉及文件**: `uv.lock`, `.venv/`, `pyproject.toml`
  - **资产类型**: Third-party
  - **关键技术**: 依赖锁定, 版本审计
  - **动手练习**: 盘点直接依赖与实际 import 的差异，标记可疑未使用依赖。
