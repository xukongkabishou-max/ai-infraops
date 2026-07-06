# Frontend 初始化安装记录

本文记录 `ai-infraops` 前端基础框架的初始化步骤。目标是先搭一个现代 React 后台应用骨架，后续再接入后端 API、RBAC 权限、动态菜单，以及高质感登录/注册动效页。

## 技术选型

- Next.js + React + TypeScript：应用框架。
- Tailwind CSS：样式系统。
- shadcn/ui：高质感基础组件。
- Motion：登录页、注册页、侧边面板、按钮等动效。
- lucide-react：图标库。
- TanStack Query：后端 API 请求与缓存。
- React Hook Form + Zod：表单和校验。

## 1. 创建前端项目

在仓库根目录执行：

```bash
npx create-next-app@latest web --typescript --eslint --app --src-dir --import-alias "@/*"
```

建议选择：

```text
Use Tailwind CSS? Yes
Use Turbopack? Yes
```

完成后进入前端目录：

```bash
cd web
```

## 2. 初始化 shadcn/ui

```bash
npx shadcn@latest init
```

建议选择：

```text
Style: New York
Base color: Neutral 或 Zinc
CSS variables: Yes
```

安装常用组件：

```bash
npx shadcn@latest add button input label card form dialog dropdown-menu separator avatar badge table tabs sheet toast
```

## 3. 安装动效、图标和业务基础包

```bash
npm install motion lucide-react
npm install @tanstack/react-query axios
npm install react-hook-form zod @hookform/resolvers
```

用途：

```text
motion              登录/注册切换、侧边视觉区、页面转场动画
lucide-react        按钮、菜单、表格操作图标
@tanstack/react-query API 请求缓存、加载状态、重试
axios               HTTP 客户端
react-hook-form     表单状态管理
zod                 表单和接口数据校验
@hookform/resolvers React Hook Form 对接 Zod
```

## 4. 推荐目录结构

```text
web/
  src/
    app/
      (auth)/
        login/
          page.tsx
      dashboard/
        page.tsx
      layout.tsx
      page.tsx
    components/
      auth/
      layout/
      permissions/
      ui/
    lib/
      api.ts
      auth.ts
      permissions.ts
      utils.ts
    providers/
      query-provider.tsx
    types/
      auth.ts
      menu.ts
      permission.ts
```

## 5. 后端 API 预期

前端 RBAC 需要后端至少提供这些接口：

```http
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/menus
GET  /api/auth/permissions
```

登录响应示例：

```json
{
  "token": "access-token",
  "refreshToken": "refresh-token"
}
```

用户信息示例：

```json
{
  "id": 1,
  "username": "admin",
  "nickname": "管理员",
  "roles": ["admin"]
}
```

权限码示例：

```json
[
  "dashboard:view",
  "user:list",
  "user:create",
  "user:update",
  "user:delete",
  "role:list",
  "role:update"
]
```

菜单示例：

```json
[
  {
    "title": "系统管理",
    "path": "/dashboard/system",
    "icon": "settings",
    "permission": "system:view",
    "children": [
      {
        "title": "用户管理",
        "path": "/dashboard/system/users",
        "permission": "user:list"
      }
    ]
  }
]
```

## 6. 前端权限规则

前端只负责展示层权限：

```text
菜单权限：没有 permission，不显示菜单。
路由权限：没有 permission，跳转 403 页面。
按钮权限：没有 permission，不显示按钮。
接口权限：必须由后端再次校验，前端隐藏按钮不能替代后端鉴权。
```

## 7. 高质感登录页方向

登录页不直接使用普通后台模板，单独定制：

```text
左侧：动态品牌视觉区，支持粒子、光束、渐变、视差。
右侧：登录表单。
切换注册：视觉面板滑动，登录/注册表单淡入淡出。
输入框：focus 描边和微动效。
按钮：hover 光晕、loading 状态。
```

对应实现建议：

```text
shadcn/ui    表单、按钮、卡片、输入框
Motion       登录/注册状态切换、面板滑动、页面过渡
lucide-react 图标
Tailwind CSS 视觉风格和响应式布局
```

## 8. 启动开发服务

```bash
cd web

npm run dev
```

默认访问：

```text
http://localhost:3000
```

## 参考来源

- Next.js 官方安装文档：https://nextjs.org/docs/app/getting-started/installation
- shadcn/ui 官方安装文档：https://ui.shadcn.com/docs/installation
- Motion React 文档：https://motion.dev/docs/react
- Lucide React 文档：https://lucide.dev/guide/react
- Ui风格 参照： https://dribbble.com/shots/5879437-Jet-login-screen
