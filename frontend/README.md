# Teachi 前端

Teachi AI 助教的前端应用，基于 Vue 3 + TypeScript + Vite + TailwindCSS 构建。

---

## 技术栈

- **Vue 3.4** - 渐进式 JavaScript 框架（Composition API）
- **TypeScript 5** - 类型安全的 JavaScript 超集
- **Vite 5** - 下一代前端构建工具
- **Vue Router 4** - 官方路由管理器
- **Pinia 2** - 状态管理方案
- **TailwindCSS 3.4** - 实用优先的 CSS 框架

---

## 项目结构

```
frontend/
├── public/                 # 静态资源
├── src/
│   ├── api/               # 数据层（门面模式）
│   │   ├── index.ts       # API 统一导出，控制 mock/real 切换
│   │   ├── types.ts       # API 接口类型定义
│   │   ├── mock/          # Mock 实现（演示模式）
│   │   └── real/          # 真实 API 实现（预留）
│   ├── components/        # 公共组件
│   │   ├── Sidebar.vue    # 侧边栏导航
│   │   └── ChatInput.vue  # 聊天输入框
│   ├── router/            # 路由配置
│   │   └── index.ts       # 三视图路由定义
│   ├── stores/            # Pinia 状态管理
│   │   ├── subject.ts     # 科目状态
│   │   └── chat.ts        # 对话状态
│   ├── views/             # 页面级组件
│   │   ├── Overview.vue       # 科目总览
│   │   ├── SubjectDetail.vue  # 科目详情
│   │   └── Chat.vue           # 对话界面
│   ├── types/             # 全局类型定义
│   │   └── index.ts
│   ├── App.vue            # 根组件
│   ├── main.ts            # 入口文件
│   └── style.css          # 全局样式
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── CONFIG.md              # 配置说明文档
```

---

## 架构设计

### 1. 门面模式（Facade Pattern）

数据层采用门面模式封装，对外提供统一接口：

```
┌─────────────────┐
│   组件/视图      │
└────────┬────────┘
         │
    ┌────▼────┐
    │  Store  │  ← Pinia 状态管理
    └────┬────┘
         │
    ┌────▼────┐
    │ API 门面 │  ← src/api/index.ts
    └────┬────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐  ┌──▼────┐
│ Mock  │  │ Real  │
└───────┘  └───────┘
```

**切换方式**：通过 `.env` 中的 `VITE_USE_MOCK` 环境变量控制：
- `true` → 使用 `src/api/mock/` 下的模拟数据
- `false` → 使用 `src/api/real/` 下的真实 API

### 2. 路由设计

三视图单页应用：

| 路由 | 视图 | 功能 |
|------|------|------|
| `/` | Overview | 科目总览，横向卡片展示 |
| `/subject/:id` | SubjectDetail | 科目详情 + 历史会话列表 |
| `/chat/:subjectId/:chatId` | Chat | 具体对话界面 |

### 3. 状态管理

使用 Pinia 组合式 API 风格：

- **subjectStore**：管理科目列表、当前科目
- **chatStore**：管理会话列表、消息、发送状态

状态流转：
```
用户操作 → Store Action → API 调用 → 更新 State → 视图响应
```

---

## 数据流说明

### 创建科目流程

```
Overview.vue
    │
    ▼
subjectStore.createSubject(name)
    │
    ▼
api.subjectApi.create() ──→ Mock: 内存中添加
    │                         Real: POST /api/subjects
    ▼
更新 subjectStore.subjects
    │
    ▼
Vue 响应式更新视图
```

### 发送消息流程

```
Chat.vue
    │
    ▼
chatStore.sendMessage(content)
    │
    ▼
api.chatApi.sendMessage() ──→ Mock: 延迟 1.5s 后返回模拟响应
    │                           Real: POST /api/chat/send
    ▼
更新 chatStore.messages
    │
    ▼
视图自动滚动到底部
```

---

## 核心功能

### 1. 科目管理
- 查看所有科目（横向滚动卡片）
- 创建新科目
- 侧边栏快速导航

### 2. 会话管理
- 查看科目下的历史会话
- 创建新会话
- 会话标题自动生成（取首条消息前 15 字）

### 3. 对话功能
- 发送/接收消息
- 消息重试（删除后重新生成）
- 输入状态指示器（跳动动画）
- 自动滚动到最新消息

### 4. 响应式布局
- 桌面端：固定侧边栏
- 移动端：抽屉式侧边栏 + 遮罩层

---

## 开发指南

### 安装依赖

```bash
cd frontend
npm install
```

### 启动开发服务器

```bash
npm run dev
```

默认访问 http://localhost:5173

### 构建生产版本

```bash
npm run build
```

输出目录：`dist/`

### 预览生产构建

```bash
npm run preview
```

---

## 配置说明

详见 `CONFIG.md`，包括：
- 环境变量（Mock/Real 模式切换）
- 主题颜色配置
- 开发服务器配置
- Mock 数据自定义

---

## 从原型迁移

本项目从 `prototype.html` 单文件原型重构而来：

| 原型 | 重构后 |
|------|--------|
| Vue 3 (CDN) | Vue 3 (ESM + 构建工具) |
| 单文件 | 模块化组件架构 |
| 内存数据 | Mock API（可切换真实 API） |
| 组件内状态 | Pinia 集中状态管理 |
| 选项式 API | 组合式 API + `<script setup>` |

---

## 扩展开发

### 接入真实后端 API

1. 修改 `.env`：
   ```
   VITE_USE_MOCK=false
   VITE_API_BASE_URL=http://your-api.com/api
   ```

2. 实现 `src/api/real/` 下的方法：
   - `subjects.ts`: getAll, getById, create
   - `chats.ts`: getBySubjectId, getById, create, sendMessage, retryMessage

### 添加新页面

1. 在 `src/views/` 创建 `.vue` 文件
2. 在 `src/router/index.ts` 添加路由
3. 如需新数据，在 `src/api/` 和 `src/stores/` 添加对应逻辑

---

## 浏览器支持

- Chrome / Edge 88+
- Firefox 78+
- Safari 14+

---

## 许可证

与主项目一致
