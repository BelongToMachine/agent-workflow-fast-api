# Asianode Copilot

Asianode Copilot（项目内部名称：Asianode Agent）是一个面向中小型企业的本地知识库 AI Agent 助手。
它把企业的产品资料、内部文档、FAQ、操作手册和业务知识集中到可管理的知识库中，再通过具备权限边界的 AI 对话和 Agent 查询能力，让员工和客户能够更快地找到可信、可追溯的答案。

项目采用前后端分离架构：本仓库负责浏览器端体验；同级的 [`asianode-fastapi`](../asianode-fastapi) 仓库负责认证、权限、知识库处理、Agent 工作流、模型调用和数据持久化。

## 产品定位

Asianode Copilot 不只是“上传文件后聊天”的机器人，而是企业知识的使用与治理入口：

```text
导入知识 → 解析与检索 → 按权限回答 → 引用来源 → 收集反馈 → 持续更新知识
```

它适合以下团队和场景：

- 10–200 人左右的 SaaS、技术服务和数字化团队；
- 产品文档、内部 Wiki、FAQ、SOP 或客服资料分散且难以维护的企业；
- 希望使用 AI，同时要求企业数据隔离、权限控制和本地化部署的团队；
- 产品文档驱动的 AI 客服、员工 onboarding、技术支持、项目和运维助手。

“本地知识库”强调本地部署优先：开发环境默认使用本地 PostgreSQL/pgvector、Redis 和文件存储，生产环境也可以接入 S3-compatible 对象存储。模型和 Embedding 服务通过后端配置接入兼容 OpenAI API 的 Provider。

## 核心能力

### 企业知识库

- 创建、重命名和删除独立知识库；
- 上传 PDF、Excel（`.xlsx`）、CSV、JSON、Markdown 和纯文本文件；
- 后端异步完成文件保存、解析、切片和状态更新；
- 可选使用 Embedding + pgvector 进行语义检索；
- 支持知识库、文件和切片的 workspace 归属校验；
- Agent 回答可以携带知识来源引用，便于核对和追溯。

### AI 对话与 Agent

- 流式聊天体验，支持聊天历史、消息加载和断线后的流恢复；
- 使用 FastAPI 统一调用模型并持久化聊天消息；
- 提供独立 Agent 查询和有限轮次 Agent workflow；
- Agent 工具由服务端注册和执行，当前以只读的产品、内容和知识库查询为主；
- Agent 不能创建 Chat/Message，也不能依赖客户端提交的用户、角色或 workspace 身份字段；
- 当检索不到答案时，可以明确说明未知，而不是把未经授权或未检索到的内容当作事实。

### Workspace 与权限管理

Workspace 是企业数据隔离边界。权限在 FastAPI 数据访问层执行，前端的按钮隐藏和路由保护只是 UX 辅助，不能替代后端鉴权。

- 本地账号、HttpOnly Session Cookie 和 CSRF 防护；
- Owner、Admin、Member 等 workspace 角色；
- 成员邀请、添加、状态切换和密码管理；
- 成员级权限和权限 override；
- `knowledge.read` / `knowledge.manage` 控制知识库使用和管理；
- `members.read` / `members.manage` 控制成员与授权配置；
- `chat.read` / `chat.delete` 控制聊天历史读取和删除；
- 用户级或角色级知识库授权；
- 关键管理操作写入审计日志；
- 每次知识库、文件、Agent 和聊天请求都重新验证当前用户与 workspace 归属。

## 系统架构

```text
┌──────────────────────────────┐
│ React + Vite 前端             │
│ 页面、路由、交互、缓存、Artifact │
└──────────────┬───────────────┘
               │ requestBackend / apiFetch
               │ HTTP + SSE
┌──────────────▼───────────────┐
│ FastAPI 后端                  │
│ 认证、权限、Workspace 隔离     │
│ Chat、Agent、知识库与文件入库   │
└───────┬───────────┬──────────┘
        │           │
 PostgreSQL       Redis       Model / Embedding Provider
 + pgvector       （可选）     （OpenAI-compatible API）
        │
 本地文件或 S3-compatible 存储
```

### 前端：本仓库

前端是独立的 React 19 + Vite 应用，主要负责：

- 聊天首页、聊天历史和消息流式渲染；
- 文本、代码、图片和表格 Artifact 的预览与编辑；
- 知识库列表、知识库文件和成员权限设置页面；
- React Query 管理 FastAPI server state，SWR 管理 Artifact 等局部状态；
- 通过 `src/lib/backend/request.ts`、`src/lib/backend/directClient.ts` 统一发起后端请求；
- 通过 AI SDK 消费 SSE，将文本、工具调用、引用和 Artifact 数据渲染到界面。

前端不会把 `userId`、`role`、`permissions` 或 workspace 所有权当作可信身份，也不会新增 Next.js API route、Server Action 或 BFF 业务逻辑。

### 后端：[`../asianode-fastapi`](../asianode-fastapi)

FastAPI 后端负责所有需要信任边界的工作：

- 本地账号认证、Session、CSRF、密码修改和邀请；
- workspace、成员、角色、权限和知识库授权；
- 聊天生成、消息持久化、SSE 和 Redis 流恢复；
- 文件上传、解析、切片、Embedding 和带权限过滤的向量检索；
- Agent 工具白名单、工具参数校验、有限轮次 workflow 和最终回答；
- PostgreSQL/pgvector、Redis 及本地或 S3-compatible 存储访问；
- 限流、错误标准化和审计日志。

详细的 API、数据库迁移、Feature Flag 和后端测试命令请参考 [`asianode-fastapi/README.md`](../asianode-fastapi/README.md)。

## 目录概览

```text
asianode-agent/
├── asianodeagent-front/         # 当前仓库：React + Vite 前端
│   ├── src/components/chat/     # 聊天壳层、消息、侧边栏和 Artifact
│   ├── src/components/settings/ # 成员与知识库管理页面
│   ├── src/hooks/               # 聊天、Artifact、滚动等浏览器 hooks
│   ├── src/lib/backend/         # FastAPI 请求、路由映射和 React Query
│   ├── src/lib/auth/             # 前端会话状态与认证页面
│   └── src/artifacts/            # 文本、代码、图片、表格 Artifact
└── asianode-fastapi/             # 同级仓库：API、Agent、权限和数据层
    ├── app/api/routes/            # HTTP API 路由
    ├── app/core/                 # 认证、权限、workspace 和安全逻辑
    ├── app/services/             # Agent、Embedding、存储和流恢复服务
    ├── migrations/               # 知识库、权限和认证相关迁移
    └── tests/                    # 后端单元及集成测试
```

## 本地开发

### 前置条件

- Bun 1.3+；
- Python 3.12+ 和 uv；
- PostgreSQL（知识库场景需要 pgvector）；
- Redis（流恢复、跨进程限流等能力需要，非聊天基础链路可选）；
- 一个兼容 OpenAI API 的 Chat Model；
- 如需语义检索，再准备 Embedding Provider 和 API Key。

### 启动后端

进入同级 FastAPI 项目：

```bash
cd ../asianode-fastapi
make setup
make infra-up
make dev
```

FastAPI 默认地址为 `http://127.0.0.1:8000`，健康检查为 `http://127.0.0.1:8000/api/v1/healthz`，Swagger 文档为 `http://127.0.0.1:8000/docs`。

首次本地开发可以按后端 README 的说明创建管理员账号：

```bash
make provision-local-admin EMAIL=owner@example.com NAME="Workspace Owner"
```

知识库文件入库、Embedding、知识库授权和独立 KnowledgeBase 实体都依赖后端 migration 与对应开关。请先阅读后端 README，再执行 migration；不要把本地数据库配置或密钥提交到仓库。

### 启动前端

回到当前目录：

```bash
bun install
cp .env.example .env.local
bun run dev
```

前端默认运行在 Vite 开发服务器，通常为 `http://localhost:5173`，并将 `/api` 请求代理到 `http://127.0.0.1:8000`。

`.env.local` 的最小配置示例：

```env
VITE_FASTAPI_URL=http://127.0.0.1:8000
VITE_WORKSPACE_ID=00000000-0000-0000-0000-000000000001
VITE_SINGLE_WORKSPACE_MODE=true
```

当前 MVP 默认使用一个配置好的 workspace。`VITE_WORKSPACE_ID` 只是开发上下文，不是安全身份；最终用户、成员和 workspace 权限始终以 FastAPI 返回的结果为准。

如需在浏览器中直接访问 FastAPI，可使用：

```env
NEXT_PUBLIC_API_MODE=fastapi-direct
NEXT_PUBLIC_USE_FASTAPI_BACKEND=1
```

日常开发推荐先使用默认的 `fastapi-proxy` 模式，以复用 Vite `/api` proxy。

## 常用页面

| 页面 | 用途 |
| --- | --- |
| `/` | 新建聊天与工作区入口 |
| `/chat/:id` | 查看指定聊天、消息流和 Artifact |
| `/settings/members` | 成员、角色、权限和成员状态管理 |
| `/settings/knowledge-bases` | 知识库及知识库授权管理 |
| `/settings/knowledge-bases/files` | 知识库文件上传、状态和删除 |
| `/settings/password` | 当前账号修改密码 |
| `/fastapi-test` | FastAPI 连接诊断 |

## 请求与安全边界

浏览器业务请求应使用前端现有的 `requestBackend`、`useBackendQuery` 或 `useBackendMutation`，不要在组件中重新实现鉴权头、CSRF、workspace 参数和错误解析。

安全边界位于 FastAPI：

1. 从 HttpOnly Session Cookie 取得当前用户；
2. 查询当前用户在目标 workspace 中的 active membership；
3. 计算角色权限与成员级 override；
4. 对知识库、文件、聊天或 Agent 工具执行资源级归属与授权校验；
5. 通过统一 API 错误返回拒绝未授权请求。

因此，前端传入的 workspace 参数只用于定位请求上下文，不能用来切换到用户无权访问的 workspace；客户端也不能通过伪造身份字段扩大权限。

## 检查命令

```bash
bun run lint
bun run build
```

后端检查请在 `../asianode-fastapi` 中执行：

```bash
make lint
make test
```

涉及聊天、知识库或权限变更时，还应验证登录、聊天发送与 SSE、历史读取/删除、Artifact 流式打开与保存、移动端布局，以及不同权限下的前端入口和后端拒绝行为。

## 当前边界与后续方向

当前系统优先完成 ToB Web MVP：企业 workspace、知识库生命周期、权限治理、可引用的 AI 问答和受控 Agent 工具调用。未来可以继续扩展知识版本与发布、知识质量反馈、Agent 评测与运行分析、Web Chat Widget、REST API 以及第三方数据源和协作渠道集成。

无论功能如何扩展，都应保持三条原则：知识访问必须可追溯，权限必须在数据层执行，高风险写操作必须经过明确的人工确认。
