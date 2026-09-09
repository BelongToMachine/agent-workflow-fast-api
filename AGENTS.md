# Asianode Agent Frontend Development Guide

本文件适用于 `asianodeagent-front` 及其子目录。前端必须遵守 React/Vite + FastAPI 分离架构：
浏览器端功能放在本仓库，API、鉴权、权限和业务逻辑放在同级的 `asianode-fastapi` 仓库。

## 项目定位

这是 Asianode Agent 的独立 React + Vite 前端，不是 Next.js 应用。前端负责：

- 页面、路由、交互、浏览器端状态和响应式 UI；
- 通过 FastAPI API 合同发起聊天、历史、文档、知识库、成员权限和文件请求；
- 消费 AI SDK 的流式消息，并把数据流渲染成聊天消息或 Artifact；
- 在浏览器中提供文本、代码、图片和表格 Artifact 的预览与编辑体验。

FastAPI 后端位于同级目录 [`../asianode-fastapi`](../asianode-fastapi)，负责 API、鉴权、workspace
隔离、权限校验、Agent workflow、模型调用、SSE、持久化和数据访问。前端提交的用户 ID、角色、权限
或 workspace 所有权都不是可信身份信息；最终鉴权必须由 FastAPI 完成。

## 当前运行架构

### 启动与路由

- `src/main.jsx` 是浏览器入口，挂载 `src/App.jsx`。
- `src/App.jsx` 组装全局 Provider、开发环境认证守卫和 React Router 路由。
- 主要页面包括：新建聊天 `/`、聊天 `/chat/:id`、成员权限设置、知识库设置、知识库文件和
  FastAPI 连接检查页。
- `src/lib/router.tsx` 是对 `react-router-dom` 的轻量封装。新增导航优先使用其中的 `Link`、
  `useRouter`、`usePathname`，不要重新引入 Next.js router。
- 聊天布局由 `AppSidebar`、`DataStreamProvider`、`ChatPage` 和 Artifact 面板组成。

### 后端请求边界

- 浏览器端普通请求使用 `requestBackend`（`src/lib/backend/request.ts`）；React Query 请求使用
  `useBackendQuery`、`useBackendInfiniteQuery` 和 `useBackendMutation`。
- `src/lib/backend/directClient.ts` 的 `apiFetch` 负责 HttpOnly Session Cookie、CSRF、workspace
  query 参数、Vite `/api` proxy 和可选的 FastAPI direct mode，并把现有的 `/api/*` 调用映射到 FastAPI 的
  `/api/v1/*` 路由。
- 新增请求前先确认 FastAPI 的实际 route、method、payload 和 response；优先复用请求层和已有的
  legacy path mapping，不要在组件里重复实现鉴权头、workspace 参数或错误解析。
- FastAPI 变化需要同步更新前端类型、请求路径、流式数据类型和错误处理；不能通过前端伪造身份字段
  绕过后端权限。
- `src/components/fastapiConnectionTest.tsx` 中的直接 `fetch` 属于诊断特例。
  业务请求不要复制这种模式。

### 认证与权限

- `src/lib/auth.tsx` 提供当前浏览器会话状态；所有环境统一使用 FastAPI 的本地账号和 HttpOnly
  Session Cookie。
- 前端不再提供开发 OIDC 页面、direct token 或认证模式切换器；授权始终以 FastAPI 返回的结果为准。
- 前端的条件渲染和设置页入口只是 UX 层提示，不能视为安全边界；成员、知识库、聊天、文档等权限
  必须以 FastAPI 返回的结果为准。
- `src/lib/auth/authorization.ts`、`src/lib/auth/nextauthBridge.ts`、`src/lib/auth/devOidc.ts`
  和 `src/lib/auth/devDirectToken.ts` 中的 server-only/NextAuth bridge 代码属于迁移兼容遗留物。
  新的浏览器代码不能依赖它们，也不能把 NextAuth 作为独立前端的长期运行时依赖。

### 聊天、流式数据与 Artifact

- `src/hooks/useActiveChat.tsx` 负责当前 chat ID、消息加载、AI SDK `useChat`、模型选择、自动恢复、
  投票查询和聊天错误处理。
- `src/components/chat/dataStreamProvider.tsx` 保存流式 UI data；
  `dataStreamHandler.tsx` 消费数据并更新 Artifact、React Query 缓存和 waiting status。
- `src/lib/types.ts` 中的 `CustomUIDataTypes`、`ChatMessage` 和 `ChatTools` 是前后端流式消息的共享
  约定。新增或修改 `data-*` part 时，要同步更新类型、FastAPI 输出和对应的消费逻辑。
- Artifact 注册表在 `src/components/chat/artifact.tsx`；各 Artifact 的浏览器实现位于：
  `src/artifacts/text/client.tsx`、`code/client.tsx`、`image/client.tsx`、`sheet/client.tsx`。
  `Artifact` 抽象和编辑/保存流程位于 `src/components/chat/createArtifact.tsx` 及相关 chat 组件。
- Artifact 的初始化、版本切换、保存、diff 和流式 delta 处理必须保持一致；修改 kind 或 delta 时，
  同时检查 `artifactDefinitions`、`useArtifact`、`DataStreamHandler` 和对应编辑器。
- 代码 Artifact 的 Python 执行在浏览器端通过 Pyodide 完成。不要把不可信代码执行迁移到前端以外，
  也不要把它误认为 FastAPI 的 Agent 执行能力。

### 状态管理

- React Query 用于 FastAPI server state、缓存、失效和 mutation；query key 应包含当前身份作用域和
  资源 ID，参考 `src/lib/backend/reactQuery.ts` 的 `backendQueryKeys`。
- SWR 当前用于 Artifact 本地状态、Artifact metadata 和部分文档版本缓存。修改 Artifact 相关代码时，
  延续该模块已有的 SWR 约定，不要无目的地把局部编辑状态提升到全局。
- React context 只承载跨多个子组件共享的交互状态，例如当前聊天和数据流。简单的局部 UI 状态使用
  组件自身的 `useState`。

## 目录约定

- `src/components/chat/`：聊天壳层、消息、输入框、侧边栏、Artifact 面板和编辑器 UI。
- `src/components/ai-elements/`：AI 消息、reasoning、tool、markdown/code block 等可复用 AI 展示组件。
- `src/components/settings/`：workspace 成员、权限和知识库管理页面。
- `src/components/ui/`：基于 Radix/shadcn 风格的基础组件；优先组合现有组件，不要为单个页面重复
  创建按钮、弹窗、输入框或布局 primitives。
- `src/hooks/`：跨组件复用的浏览器 hooks；领域特定的数据请求仍应通过 backend request/query 层。
- `src/lib/backend/`：FastAPI 请求、模式切换、错误标准化和 React Query 封装。
- `src/lib/auth/`：认证开发桥接和迁移兼容代码；新增浏览器认证逻辑先确认是否应放在独立前端或 FastAPI。
- `src/lib/editor/`：ProseMirror 文本编辑器、diff 和 suggestion 支持。
- `src/lib/db/`、`src/lib/ai/`、`src/lib/artifacts/server.ts` 以及 `src/artifacts/*/server.ts`：从旧
  Next.js 应用保留的 server-side/数据访问/AI 实现。新业务逻辑、数据库查询、migration、Agent workflow
  和模型调用应放到 `../asianode-fastapi`；除迁移、兼容或清理外，不要继续扩大这些目录的依赖。
- `src/globals.css`、`src/index.css` 和现有组件 class：当前样式入口。项目使用 Tailwind CSS 4，新增样式
  优先使用现有 design token 和 utility class。
- `public/`：静态资源和字体；`dist/` 是构建产物，不要手工编辑或提交生成内容。

### 文件命名

- 前端源码文件统一使用 camelCase（驼峰命名），例如 `useActiveChat.tsx`、`dataStreamHandler.tsx`、`chatHistoryCache.ts`。
- 禁止新增或保留 kebab-case 源码文件名；新增文件名中不要使用 `-` 连接单词。
- 第三方 vendor 资源文件名（例如 `public/fonts/` 中由上游提供的字体文件）如需保持兼容可以例外，但业务源码必须遵守 camelCase。

## 开发约定

- 新增代码优先使用 TypeScript/TSX；现有 `.jsx` 入口和迁移代码无需为了本次修改而整体改写。
- 使用 `@/` alias 引用 `src` 下模块；相对路径仅用于同一小模块内的紧邻文件。
- 优先使用函数组件和 hooks，遵守 React hooks 规则；不要在渲染期间发起副作用或直接修改 props。
- 复用 `src/lib/utils.ts` 的 `cn`、`fetcher`、UUID 和错误处理能力；避免在每个组件里重新定义相同工具。
- 异步请求必须处理 loading、空数据、错误和取消/卸载场景；mutation 成功后要按资源关系失效或更新相关
  React Query/SWR cache。
- 用户可见错误沿用现有 toast 和 `BackendRequestError` 语义；开发日志可以包含 request ID，但不要输出
  access token、完整用户凭据或敏感业务数据。
- API query 参数、路径片段和用户输入必须正确编码；上传使用 `FormData` 时不要手工覆盖浏览器的
  `Content-Type` boundary。
- 保持现有响应式行为和无障碍属性，尤其是聊天滚动、移动端 Artifact、键盘操作、dialog/tooltip 和表格。

## 环境与常用命令

包管理器由 `package.json` 固定为 Bun，依赖锁文件是 `bun.lock`：

```bash
bun install
bun run dev
bun run lint
bun run build
bun run preview
```

本地前端默认把 `/api` proxy 到 `http://127.0.0.1:8000`。常用环境变量见 `.env.example`：

- `VITE_FASTAPI_URL`：Vite dev proxy 的 FastAPI 地址；
- `VITE_WORKSPACE_ID`：本地开发的默认 workspace ID，只是开发上下文，不是安全身份；
- `NEXT_PUBLIC_FASTAPI_BASE_URL`：direct mode 使用的浏览器可访问 FastAPI 地址；
- `NEXT_PUBLIC_API_MODE=fastapi-proxy|fastapi-direct`：开发环境请求模式，默认 proxy；
- `NEXT_PUBLIC_USE_FASTAPI_BACKEND=1`：启用 FastAPI chat 兼容路径，Vite 配置默认注入为 `1`。

启动完整本地链路时，另行在 `../asianode-fastapi` 按其 README 启动 FastAPI 和所需 PostgreSQL/Redis。
不要把密钥写入仓库或提交 `.env`、`.env.local`。

## 验证要求

每次修改至少运行与变更范围匹配的检查；涉及组件、路由或 API 的改动通常应运行：

```bash
bun run lint
bun run build
```

如果改动聊天或后端合同，还应手动验证：开发 OIDC 登录、聊天发送与 SSE、历史/删除、投票、Artifact
流式打开与保存、移动端布局，以及 FastAPI 错误/未授权响应。涉及成员或知识库设置时，验证不同权限下
的入口、加载、mutation 和后端拒绝行为。

当前 `package.json` 没有配置独立的前端 test script；不要把未配置的测试命令写成项目必需步骤。AI/旧
Next.js 目录中的测试或 server-side 代码不等同于 Vite 浏览器端测试。

## 迁移边界与禁止事项

- 不要在本项目新增 Next.js page、API route、server action、React Server Component、NextAuth 业务依赖
  或新的 BFF 逻辑。
- 不要在前端新增数据库表、Drizzle migration、业务查询、模型 provider、Agent workflow 或权限判定；
  这些应在 FastAPI 中实现，并由前端消费稳定 API 合同。
- 不要把 `src/lib/db`、`src/lib/ai` 或带 `server-only`/`use server` 的遗留模块当作新的浏览器层。
- 不要绕过 `requestBackend`/`apiFetch`，也不要从客户端传入并信任 `userId`、`role`、`permissions`、
  `workspace_owner` 等身份字段。
- 不要手工修改 `dist/` 或提交构建产物；不要覆盖其他未相关的工作区改动。
- 如果必须保留迁移兼容代码，请将其隔离、注明原因，并确保独立 React/Vite 应用不会形成新的长期依赖。
