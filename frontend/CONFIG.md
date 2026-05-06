# Teachi 前端配置说明

本文档列出项目中所有可修改的配置参数。

---

## 1. 项目基本信息

**文件**: `package.json`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `name` | `"teachi-frontend"` | 项目名称（npm 包名） |
| `version` | `"1.0.0"` | 版本号（语义化版本） |

---

## 2. 环境变量

**文件**: `.env` 或 `.env.local`（本地覆盖）

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `VITE_USE_MOCK` | `true` | `true` / `false` | 是否使用 Mock 数据模式 |
| `VITE_API_BASE_URL` | 未设置 | 如 `http://localhost:8000/api` | 真实 API 的基础地址（当 `VITE_USE_MOCK=false` 时生效） |
| `VITE_APP_TITLE` | `"Teachi - AI 助教"` | 任意字符串 | 页面标题 |

**使用示例**:
```bash
# .env
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://localhost:8000/api
```

---

## 3. 开发服务器配置

**文件**: `vite.config.ts`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `server.port` | `5173` | 开发服务器端口号 |
| `resolve.alias.@` | `"./src"` | 源码路径别名 |

**修改示例**:
```typescript
export default defineConfig({
  server: {
    port: 3000,  // 改为 3000 端口
    host: true,  // 允许外部访问
    open: true   // 自动打开浏览器
  },
  // ...
})
```

---

## 4. 主题样式配置

**文件**: `tailwind.config.js`

### 4.1 颜色主题

| 颜色名 | 默认值 | 用途 |
|--------|--------|------|
| `bgMain` | `#f3f4f6` | 主背景色（浅灰） |
| `bgSidebar` | `#ffffff` | 侧边栏背景 |
| `borderLight` | `#d1d5db` | 浅色边框 |
| `borderDark` | `#1f2937` | 深色边框 |
| `highlight` | `#e5e7eb` | 高亮/悬停色 |
| `highlightUser` | `#f9fafb` | 用户消息背景 |

### 4.2 字体配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `fontFamily.sans` | `['Inter', 'system-ui', 'sans-serif']` | 主字体栈 |

**自定义示例**:
```javascript
theme: {
  extend: {
    colors: {
      bgMain: '#fafafa',        // 改为纯白背景
      borderDark: '#000000',    // 改为纯黑边框
      primary: '#3b82f6',       // 添加主色
      secondary: '#10b981',     // 添加辅色
    },
    fontFamily: {
      sans: ['"Noto Sans SC"', 'system-ui', 'sans-serif'],  // 使用思源黑体
    }
  }
}
```

---

## 5. Mock 数据配置

**文件**: `src/api/mock/subjects.ts`

| 参数 | 说明 |
|------|------|
| `demoSubjects` | 初始演示科目数据数组 |
| 科目字段 `name` | 科目名称 |
| 科目字段 `desc` | 科目描述 |

**添加初始科目示例**:
```typescript
const demoSubjects: Subject[] = [
  {
    id: '1',
    name: '我的科目名',
    desc: '科目描述...',
    chats: [],
    createdAt: Date.now(),
    updatedAt: Date.now()
  },
  // ... 更多科目
]
```

---

## 6. 路由配置

**文件**: `src/router/index.ts`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 路由模式 | `createWebHistory` | HTML5 History 模式 |
| 基础路径 | `/` | 应用部署的基础路径 |

**修改基础路径**（如需部署到子目录）:
```typescript
const router = createRouter({
  history: createWebHistory('/teachi/'),  // 部署到 /teachi/ 子路径
  routes
})
```

---

## 7. TypeScript 编译配置

**文件**: `tsconfig.json`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `target` | `"ES2020"` | 编译目标版本 |
| `strict` | `true` | 严格类型检查 |
| `noUnusedLocals` | `true` | 禁止未使用的局部变量 |

---

## 8. 快速配置清单

### 切换到真实 API

1. 修改 `.env`:
   ```
   VITE_USE_MOCK=false
   VITE_API_BASE_URL=http://your-api-server.com/api
   ```

2. 实现 `src/api/real/` 下的 API 方法

### 修改主题颜色

编辑 `tailwind.config.js` 中的 `colors` 对象。

### 修改版本号

编辑 `package.json` 中的 `version` 字段。

### 添加新字体

1. 在 `index.html` 引入字体 CDN
2. 在 `tailwind.config.js` 中配置 `fontFamily`

---

## 9. 环境变量类型声明

如需在代码中使用类型化的环境变量，修改 `src/vite-env.d.ts`:

```typescript
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK: string
  readonly VITE_API_BASE_URL: string
  readonly VITE_APP_TITLE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
```
