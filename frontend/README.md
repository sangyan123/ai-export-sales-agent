# Fastener AI 前端

紧固件 AI 外销助手的 Web 前端。当前为 MVP 骨架：认证、布局、权限菜单与工作台已接通真实后端 API，业务页面为占位骨架，按里程碑逐步替换。

## 技术栈

- Vue 3.5 + TypeScript 6 + Vite 8
- Element Plus（中文 locale）+ `@element-plus/icons-vue`
- Pinia 状态管理，Vue Router 5（路由级懒加载）
- Axios 统一客户端，自动解包后端 `{ data, meta }` 响应

## 本地运行

前置条件：后端 API 已启动（默认 `http://127.0.0.1:8000`），PostgreSQL / Redis / MinIO 已就绪。

```bash
# 1. 准备本地演示账号（幂等，可重复执行；会重置演示密码）
cd backend
uv run python scripts/seed_demo.py

# 2. 启动前端
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173 。

### 演示账号

| 企业标识 | 邮箱 | 密码 | 角色 |
|---|---|---|---|
| `demo` | `demo@example.com` | `Demo1234!` | OWNER（全部权限） |
| `demo` | `viewer@example.com` | `Demo1234!` | VIEWER（只读权限） |

演示账号仅用于本地开发，不要在生产环境执行该脚本。

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | API 基础路径，走 Vite 代理时保持默认 |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | 开发服务器 `/api` 代理目标 |

## 目录结构

```
src/
├── api/            # Axios 实例、令牌存取、认证接口
├── components/     # 通用组件（模块占位卡片等）
├── directives/     # v-permission 权限指令
├── layouts/        # 应用外壳：侧边菜单 + 顶栏
├── router/         # 路由表与登录/权限守卫
├── stores/         # Pinia 状态（auth）
├── styles/         # 全局样式
├── types/          # API 信封与业务类型
└── views/          # 页面（登录、工作台、各业务模块）
```

## 认证与令牌策略

后端登录要求同时提供企业标识（`tenant_slug` 或 `tenant_id`）与邮箱密码。

- access token 只保存在内存中，刷新页面即失效。
- refresh token 保存在 `localStorage` 的 `fastener.refresh_token`，用于页面重载后恢复会话。这是 MVP 阶段的权衡，后续可迁移到 HttpOnly Cookie。
- 请求返回 401 时，客户端单飞（single-flight）调用 `/auth/refresh` 并重试一次；刷新失败会清空令牌并跳转 `/login?expired=1`。
- 退出登录调用 `/auth/logout` 吊销 refresh token。

## 路由与权限

- 未登录访问受保护路由会跳转登录页，登录成功后回到原路径。
- 路由 `meta.permission` 与后端权限码一一对应（如 `customer:read`）；无权限时回工作台并提示缺失权限。
- 侧边菜单按当前用户权限过滤；按钮级控制使用 `v-permission="'quote:approve'"`。

## 构建与检查

```bash
npm run build   # vue-tsc 类型检查 + 生产构建
npm run preview # 预览构建产物
```

## 当前进度

已完成：登录/刷新/退出、权限守卫、应用布局、工作台统计（读取各模块 `meta.total`）、模块占位页。
待接入：询盘、报价、产品、客户/联系人、跟进任务、AI 工作台、企业设置的具体列表与表单。
