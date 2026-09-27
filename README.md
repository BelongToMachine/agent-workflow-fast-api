# pallas

pallas is an enterprise knowledge collaboration product. This low-coupling monorepo keeps the FastAPI backend at the repository root and the React + Vite frontend in <code>frontend/</code>; each application retains its own dependency management, build, and release process.

pallas 是面向企业知识协作的产品。本 monorepo 采用低耦合结构：FastAPI 后端位于仓库根目录，React + Vite 前端位于 <code>frontend/</code>；两边继续使用各自的依赖管理、构建和发布流程。

## Monorepo layout and production boundaries / Monorepo 布局与生产边界

The Python backend runs from the repository root. Frontend commands can be run from the root with <code>make frontend-*</code>; the two applications do not share a lockfile or implicit workspace.

Python 后端仍从仓库根目录运行。前端命令可从根目录通过 <code>make frontend-*</code> 执行；两边没有共享锁文件或隐式工作区。

~~~text
.
├── app/                 # FastAPI application / FastAPI 应用
├── migrations/          # FastAPI database migrations / FastAPI 数据库迁移
├── deploy/              # FastAPI VPS deployment scripts / FastAPI VPS 部署脚本
├── frontend/            # React + Vite frontend and its deployment files / 前端及独立部署文件
│   ├── package.json     # Bun project manifest / Bun 项目清单
│   └── bun.lock         # Frontend lockfile / 前端锁文件
├── docs/                # Architecture, API, and operations docs / 架构、API 与运维文档
├── pyproject.toml       # Python/uv project manifest / Python/uv 项目清单
└── uv.lock              # Backend lockfile / 后端锁文件
~~~

- Adding the frontend to this repository does not switch the production deployment source. Cloudflare Pages and SG frontend releases still use the existing standalone frontend repository; SG FastAPI releases still use the existing backend checkout and deployment scripts.
- 将前端纳入本仓库并不会自动切换生产部署源。Cloudflare Pages 和 SG 前端发布仍使用现有独立前端仓库；SG FastAPI 发布仍由现有后端 checkout 和部署脚本负责。
- GitHub Actions in this repository run lint, tests, and builds only. They do not deploy and do not contain Cloudflare or VPS credentials.
- 本仓库的 GitHub Actions 仅运行 lint、测试和构建，不负责部署，也不包含 Cloudflare 或 VPS 凭据。
- Keep the standalone frontend repository. Consider switching production sources only after the Pages repository/root settings, SG deployment scripts, and rollback procedure have been adapted and verified.
- 请保留原独立前端仓库。只有在 Pages 仓库与根目录设置、SG 部署脚本和回滚流程完成适配与验证后，才考虑切换生产来源。

See [the monorepo architecture guide](docs/monorepo-architecture.md) for directory responsibilities, dependency boundaries, current release sources, and the future cutover checklist. Frontend development instructions are in [frontend/README.md](frontend/README.md).

目录职责、依赖边界、现行发布来源和后续切换检查表见 [monorepo 架构说明](docs/monorepo-architecture.md)。前端开发说明见 [frontend/README.md](frontend/README.md)。

## FastAPI backend / FastAPI 后端

This section covers local development, API routes, database migrations, and operations. The backend remains at the repository root.

本节介绍 FastAPI 本地开发、API 路由、数据库迁移和运维约定。后端仍位于仓库根目录。

### Technology stack / 技术栈

- Python 3.12+
- FastAPI
- Pydantic Settings
- Uvicorn
- Pytest
- Ruff

### Local development / 本地运行

Use [uv](https://docs.astral.sh/uv/) to manage the Python environment and dependencies. Run setup once, then start the development server.

使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境和依赖。首次运行时执行初始化命令，之后启动开发服务器即可。

~~~bash
make setup
make dev
~~~

Start the server on later runs with:

后续日常启动执行：

~~~bash
make dev
~~~

### PostgreSQL, pgvector, and Redis / PostgreSQL、pgvector 和 Redis

Knowledge-base migrations and resumable chat streams require local PostgreSQL/pgvector and Redis. Start the services with the provided Docker Compose configuration:

知识库迁移和可恢复聊天流需要本地 PostgreSQL/pgvector 与 Redis。使用项目提供的 Docker Compose 配置启动服务：

~~~bash
make infra-up
make infra-status
~~~

The default local connection settings are:

默认本地连接配置：

~~~env
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode
REDIS_URL=redis://127.0.0.1:6379/0
~~~

Before applying knowledge-base migrations, confirm that the base business tables exist in the database. Apply the new FastAPI tables from this repository; do not write local settings back to the current remote Supabase configuration.

应用知识库迁移前，先确认数据库中的基础业务表已经存在，再从本仓库应用 FastAPI 新增的表。不要把本地配置写回当前远程 Supabase。

~~~bash
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make migration-status
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make knowledge-integrity
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make migrate-knowledge
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make migrate-knowledge-grants
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make migrate-knowledge-ingestion
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make migrate-knowledge-embeddings
POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode make migrate-knowledge-bases
~~~

Enable <code>KNOWLEDGE_GRANTS_ENABLED</code>, <code>KNOWLEDGE_INGESTION_ENABLED</code>, and <code>KNOWLEDGE_EMBEDDINGS_ENABLED</code> locally only after all four migrations succeed. FastAPI always uses the <code>KnowledgeBase</code> entity. <code>make infra-down</code> removes containers without <code>-v</code>, so database and Redis volumes remain.

四项迁移全部成功后，才在本地开启 <code>KNOWLEDGE_GRANTS_ENABLED</code>、<code>KNOWLEDGE_INGESTION_ENABLED</code> 和 <code>KNOWLEDGE_EMBEDDINGS_ENABLED</code>。FastAPI 固定使用 <code>KnowledgeBase</code> 实体。<code>make infra-down</code> 不带 <code>-v</code>，只移除容器，不会删除数据库或 Redis volume。

Before releasing a version that removes chat feedback, run <code>migrations/0011_remove_vote_v2.sql</code> through the formal deployment migration process. It irreversibly drops the deprecated <code>Vote_v2</code> table; back up the database first.

发布移除聊天反馈功能的版本前，应由正式部署迁移流程执行 <code>migrations/0011_remove_vote_v2.sql</code>。该迁移会不可逆地删除废弃的 <code>Vote_v2</code> 表，执行前先备份数据库。

<code>make knowledge-integrity</code> is a read-only safety check. It requires all four migrations and verifies that grants, files, and chunks have no orphaned records and that workspace, knowledge-base, and file ownership is consistent. It exits non-zero on failure and does not repair data or replace verification against the real database and object store.

<code>make knowledge-integrity</code> 是只读安全检查，要求四项迁移均已完成，并验证授权、文件和切片没有孤儿记录，以及 workspace、knowledge base、file 的归属一致。检查失败会返回非零退出码；它不会自动修复数据，也不能替代对真实数据库和对象存储的验证。

<code>make migrate-knowledge</code> applies pending migrations in dependency order: <code>0001</code> grants, <code>0002</code> ingestion, <code>0003</code> embeddings, and <code>0004</code> independent knowledge bases. It runs them in one database transaction and skips completed migrations on repeat runs. By default, it only permits a local development database and always rejects staging/production. For a remote development database, run the migration runner directly with <code>--allow-remote</code> after a backup and manual review.

<code>make migrate-knowledge</code> 按依赖顺序执行待处理迁移：<code>0001</code> grants、<code>0002</code> ingestion、<code>0003</code> embeddings 和 <code>0004</code> 独立 knowledge base。所有迁移在一个数据库事务中执行，重复运行会跳过已完成项。默认只允许本地开发数据库，并始终拒绝 staging/production。迁移远程开发数据库时，需先备份和人工审查，再直接运行 runner 并显式传入 <code>--allow-remote</code>。

### API routes / API 路由

After starting the server, the API is available at <code>http://127.0.0.1:8000</code>. The main routes are listed below.

服务启动后，API 地址为 <code>http://127.0.0.1:8000</code>。常用路由如下。

| Purpose / 用途 | Route |
| --- | --- |
| API root / API 根路径 | <code>GET /</code> |
| Health check / 健康检查 | <code>GET /api/v1/healthz</code> |
| Products / 商品查询 | <code>GET /api/v1/products?workspace_id={workspace_id}</code> |
| Content search / 内容查询 | <code>POST /api/v1/content/search</code> |
| Current user / 当前用户 | <code>GET /api/v1/me</code> |
| Knowledge sources / 知识库数据源 | <code>GET /api/v1/knowledge-sources?workspace_id={workspace_id}</code> |
| Knowledge bases / 知识库列表 | <code>GET /api/v1/knowledge-bases?workspace_id={workspace_id}</code> |
| Create knowledge base / 创建知识库 | <code>POST /api/v1/knowledge-bases?workspace_id={workspace_id}</code> |
| Rename knowledge base / 重命名知识库 | <code>PATCH /api/v1/knowledge-bases/{knowledge_base_id}?workspace_id={workspace_id}</code> |
| Delete knowledge base / 删除知识库 | <code>DELETE /api/v1/knowledge-bases/{knowledge_base_id}?workspace_id={workspace_id}</code> |
| Workspace members / 成员列表 | <code>GET /api/v1/admin/members?workspace_id={workspace_id}</code> |
| Update member permissions / 更新成员权限 | <code>PATCH /api/v1/admin/members?workspace_id={workspace_id}</code> |
| Chat history / 聊天历史 | <code>GET /api/v1/chats?workspace_id={workspace_id}</code> |
| Delete workspace chat history / 删除 workspace 聊天历史 | <code>DELETE /api/v1/chats?workspace_id={workspace_id}</code> |
| Chat messages / 聊天消息 | <code>GET /api/v1/chats/{chat_id}/messages?workspace_id={workspace_id}</code> |
| Suggestions / 文档建议 | <code>GET /api/v1/suggestions?documentId={document_id}&workspace_id={workspace_id}</code> |
| Model capabilities / 模型能力 | <code>GET /api/v1/models</code> |
| Knowledge-base grants / 知识库授权列表 | <code>GET /api/v1/admin/knowledge-base-grants?workspace_id={workspace_id}</code> |
| Add or update a grant / 新增或更新知识库授权 | <code>PUT /api/v1/admin/knowledge-base-grants?workspace_id={workspace_id}</code> |
| Delete a grant / 删除知识库授权 | <code>DELETE /api/v1/admin/knowledge-base-grants/{grant_id}?workspace_id={workspace_id}</code> |
| Legacy local Mock OIDC consent / 旧本地 Mock OIDC consent | <code>POST /api/v1/dev/oidc/consent</code> (backend migration compatibility only; disabled in the browser / 仅后端迁移兼容，浏览器端已停用) |
| Chat / 聊天 | <code>POST /api/v1/chat</code> |
| Resume a chat stream / 恢复聊天流 | <code>GET /api/v1/chat/{chat_id}/stream?workspace_id={workspace_id}</code> |
| Standalone Agent query / 独立 Agent 查询 | <code>POST /api/v1/agents/query?workspace_id={workspace_id}</code> |
| Standalone Agent workflow / 独立 Agent workflow | <code>POST /api/v1/agents/run?workspace_id={workspace_id}</code> |
| Knowledge migration status / 知识库迁移状态 | <code>make migration-status</code> |
| Knowledge integrity check / 知识库数据完整性 | <code>make knowledge-integrity</code> |
| Knowledge-base files / 知识库文件列表 | <code>GET /api/v1/knowledge-bases/{knowledge_base_id}/files?workspace_id={workspace_id}</code> |
| Upload a knowledge file / 上传知识库文件 | <code>POST /api/v1/knowledge-bases/{knowledge_base_id}/files?workspace_id={workspace_id}</code> |
| Delete a knowledge file / 删除知识库文件 | <code>DELETE /api/v1/knowledge-bases/{knowledge_base_id}/files/{file_id}?workspace_id={workspace_id}</code> |
| Knowledge search / 知识库向量检索 | <code>POST /api/v1/knowledge-bases/{knowledge_base_id}/search?workspace_id={workspace_id}</code> |
| Web Chat image upload / Web Chat 图片上传 | <code>POST /api/v1/files/upload?workspace_id={workspace_id}</code> |
| Swagger UI / Swagger 文档 | <code>http://127.0.0.1:8000/docs</code> |

### SQLAdmin local preview / SQLAdmin 本地预览

FastAPI does not include Django Admin. This repository provides a read-only SQLAdmin preview, disabled by default, which does not modify business tables. Enable it when starting FastAPI:

FastAPI 本身不带 Django Admin。本项目提供一个只读的 SQLAdmin 本地预览，默认关闭且不会修改业务表。启动 FastAPI 时设置：

~~~bash
make dev \
  SQLADMIN_ENABLED=true \
  SQLADMIN_USERNAME=admin \
  SQLADMIN_PASSWORD=change-me-locally \
  SQLADMIN_SECRET_KEY=use-a-long-random-local-secret
~~~

Then visit <code>http://127.0.0.1:8000/admin</code> to inspect User, Workspace, and WorkspaceMember. This separate local login is for database/UI inspection; it does not replace OIDC/Bearer authentication. Production rejects this preview.

然后访问 <code>http://127.0.0.1:8000/admin</code> 查看 User、Workspace 和 WorkspaceMember。该独立本地登录仅用于检查数据库和 SQLAdmin 界面，不替代正式 OIDC/Bearer 认证；生产环境会拒绝启用此预览。

FastAPI reads <code>.env.local</code> from the monorepo root, so local runs can reuse <code>DEEPSEEK_API_KEY</code>. Model-provider requests time out after 60 seconds by default; set <code>CHAT_PROVIDER_TIMEOUT_SECONDS</code> to a value from 1 to 300 seconds. Supply API keys through environment variables in other environments.

FastAPI 本地运行时会读取 monorepo 根目录的 <code>.env.local</code>，因此可以复用 <code>DEEPSEEK_API_KEY</code>。模型 provider 请求默认在 60 秒后超时，可用 <code>CHAT_PROVIDER_TIMEOUT_SECONDS</code> 调整到 1–300 秒。其他环境请通过环境变量提供 API Key。

The request field <code>selectedChatModel</code> must use a model ID returned by <code>/api/v1/models</code>. Unknown IDs fall back to <code>deepseek-chat</code> inside FastAPI; arbitrary provider/model strings from the client are never forwarded.

请求中的 <code>selectedChatModel</code> 必须是 <code>/api/v1/models</code> 返回的模型 ID。未知模型会在 FastAPI 内部回退到 <code>deepseek-chat</code>，不会转发客户端提交的任意 provider/model 字符串。

## Frontend and FastAPI integration / 前端与 FastAPI 集成

Set the following variables in <code>frontend/.env.local</code> to route Web Chat requests to FastAPI:

在 <code>frontend/.env.local</code> 中设置以下变量，可让 Web Chat 请求进入 FastAPI：

~~~env
USE_FASTAPI_BACKEND=1
NEXT_PUBLIC_USE_FASTAPI_BACKEND=1
FASTAPI_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FASTAPI_BASE_URL=http://127.0.0.1:8000
# Optional local browser direct mode:
NEXT_PUBLIC_API_MODE=fastapi-direct
~~~

The standalone Vite frontend can call FastAPI on port 8000 directly with a Bearer access token. FastAPI enforces workspace permissions, persists messages, calls models, and returns SSE. Development also supports <code>NEXT_PUBLIC_API_MODE=fastapi-direct</code>, which uses a five-minute development direct token so real HTTP and SSE requests can be inspected in browser DevTools. This token is accepted only when <code>ENVIRONMENT=development</code>; production requires an OIDC Bearer token.

独立 Vite 前端通过 Bearer access token 直接请求 FastAPI 的 8000 端口。FastAPI 负责 workspace 权限、消息持久化、模型调用和 SSE 返回。开发环境也支持 <code>NEXT_PUBLIC_API_MODE=fastapi-direct</code>，使用有效期五分钟的开发 direct token，便于在 DevTools Network 中查看真实 HTTP/SSE 请求。该 token 仅在 <code>ENVIRONMENT=development</code> 时接受；生产环境必须使用正式 OIDC Bearer Token。

FastAPI preserves JPEG/PNG attachments in Web Chat messages: text remains a normal string and images are converted to OpenAI-compatible <code>image_url</code> content. Only <code>http://</code>, <code>https://</code>, and <code>data:image/...</code> URLs are accepted. PDFs, other file types, and local paths are not forwarded to the model.

FastAPI 会保留 Web Chat 消息中的 JPEG/PNG 图片附件：文字部分仍为普通字符串，图片转换成 OpenAI-compatible <code>image_url</code> content。仅允许 <code>http://</code>、<code>https://</code> 和 <code>data:image/...</code> URL；PDF、其他文件类型和本地路径不会转发给模型。

Web Chat image upload is disabled by default. To use the FastAPI upload pipeline, configure FastAPI and <code>frontend/.env.local</code> separately:

Web Chat 图片上传默认关闭。要使用 FastAPI 上传管道，需分别配置 FastAPI 和 <code>frontend/.env.local</code>：

~~~env
# FastAPI
CHAT_ATTACHMENTS_ENABLED=true
ATTACHMENT_STORAGE_PROVIDER=local
ATTACHMENT_STORAGE_DIR=storage/attachments
ATTACHMENT_URL_TTL_SECONDS=3600

# Frontend BFF
USE_FASTAPI_ATTACHMENT_UPLOAD=1
~~~

The local provider returns FastAPI URLs signed with HMAC and an expiry. The S3-compatible provider returns short-lived presigned URLs and reuses <code>KNOWLEDGE_S3_*</code> settings. With the local provider in production, set <code>ATTACHMENT_PUBLIC_BASE_URL</code> to a browser-accessible API URL. Turning off <code>USE_FASTAPI_ATTACHMENT_UPLOAD</code> keeps the existing Vercel Blob <code>/api/files/upload</code> route available for rollback. FastAPI checks PNG/JPEG magic bytes in addition to the multipart <code>Content-Type</code> and rejects mismatches.

local provider 返回带 HMAC 签名和过期时间的 FastAPI URL；S3-compatible provider 返回短期 presigned URL，并复用 <code>KNOWLEDGE_S3_*</code> 配置。生产环境使用 local provider 时，需设置浏览器可访问的 <code>ATTACHMENT_PUBLIC_BASE_URL</code>。关闭 <code>USE_FASTAPI_ATTACHMENT_UPLOAD</code> 后，原有 Vercel Blob <code>/api/files/upload</code> 可作为回滚路径。FastAPI 除检查 multipart <code>Content-Type</code> 外，还会校验 PNG/JPEG magic bytes，不匹配时拒绝上传。

With <code>REDIS_URL</code>, FastAPI stores short-lived SSE chunks by chat and exposes <code>GET /api/v1/chat/{chat_id}/stream</code> for AI SDK reconnection. The resume route rechecks the user, workspace, and chat ownership. Without Redis, chat falls back to ordinary SSE.

配置 <code>REDIS_URL</code> 后，FastAPI 会按 chat 保存短期 SSE chunks，并提供 <code>GET /api/v1/chat/{chat_id}/stream</code> 供 AI SDK 断线重连。恢复接口会重新校验用户、workspace 和 chat 归属。未配置 Redis 时会回退到普通 SSE。

## Agent behavior / Agent 行为

Standalone Agent query accepts only predefined read-only tool names and arguments. It does not accept user, role, permission, or workspace identity from callers. FastAPI derives identity from the Bearer token, checks <code>knowledge.read</code>, then searches products, content, or selected knowledge bases.

独立 Agent 查询只接受预定义的只读工具名和参数，不接受调用方提交的 user、role、permission 或 workspace 身份。FastAPI 从 Bearer Token 获取身份，检查 <code>knowledge.read</code> 后，再搜索商品、内容或指定知识库。

The standalone workflow runs a bounded number of model/tool steps and adds one final summary after the tool limit. It does not create Chat/Message records and accepts only a prompt plus up to 10 <code>maxSteps</code>.

独立 Agent workflow 执行有限轮次的模型和工具调用，并在达到工具上限后追加一次最终总结。它不会创建 Chat/Message，只接受 prompt 和最多 10 轮的 <code>maxSteps</code>。

With <code>knowledge.read</code>, FastAPI registers read-only <code>searchProductsTool</code>, <code>searchContentTool</code>, <code>listKnowledgeBasesTool</code>, <code>listKnowledgeFilesTool</code>, <code>getKnowledgeBaseTool</code>, and <code>getKnowledgeFileTool</code>. When vector search is enabled, it also registers <code>searchKnowledgeBaseTool</code>. The model must list readable knowledge bases before opening a base, checking file status, or searching. FastAPI executes tool calls and reapplies workspace and grant filters; clients cannot forge tool results.

用户具备 <code>knowledge.read</code> 时，FastAPI 会注册只读的 <code>searchProductsTool</code>、<code>searchContentTool</code>、<code>listKnowledgeBasesTool</code>、<code>listKnowledgeFilesTool</code>、<code>getKnowledgeBaseTool</code> 和 <code>getKnowledgeFileTool</code>。开启向量检索后还会注册 <code>searchKnowledgeBaseTool</code>。模型应先列出可读知识库，再查看知识库、文件状态或检索内容。工具调用由 FastAPI 执行，并再次应用 workspace 和 grant 过滤；客户端不能伪造工具结果。

## Security and authentication / 安全与认证

FastAPI rate-limits <code>/api/v1/*</code> by default: 120 requests per minute for ordinary routes, 20 for chat, and 30 for file routes. With <code>REDIS_URL</code> and <code>RATE_LIMIT_REDIS_ENABLED=true</code>, fixed-window counters are shared across instances. If Redis is unavailable, limits fall back to process-local counters. Health checks and OpenAPI are excluded; production should configure trusted client IP handling at the reverse proxy.

FastAPI 默认对 <code>/api/v1/*</code> 限流：普通接口每分钟 120 次、聊天每分钟 20 次、文件接口每分钟 30 次。配置 <code>REDIS_URL</code> 和 <code>RATE_LIMIT_REDIS_ENABLED=true</code> 后，多实例共享 fixed-window counter；Redis 不可用时回退到进程内计数。健康检查和 OpenAPI 不计入限流；生产环境应在反向代理层配置可信客户端 IP。

Product, content, and chat routes use FastAPI local-session authentication:

商品、内容和聊天接口统一使用 FastAPI 本地 Session 认证：

- Browser authentication in all environments uses local FastAPI accounts, an HttpOnly <code>__Host-asianode_session</code> cookie, and a CSRF token.
- 所有环境的浏览器端认证都使用 FastAPI 本地账号、HttpOnly <code>__Host-asianode_session</code> Cookie 和 CSRF Token。
- <code>AUTH_MODE=local_session</code> is the default. <code>dual</code> and <code>logto</code> are explicit migration/rollback options.
- <code>AUTH_MODE=local_session</code> 是默认模式；<code>dual</code> 和 <code>logto</code> 仅作为显式迁移或回滚选项。
- Passwords are verified with Argon2id. Administrators create employee accounts through one-time invitation links; users can change passwords after signing in.
- 本地账号密码使用 Argon2id 校验。管理员通过一次性邀请链接创建员工账号，用户登录后可以修改密码。
- FastAPI ignores browser-submitted user, role, and workspace identity fields. Final authorization uses server-side User, WorkspaceMember, and permission overrides.
- FastAPI 不接受浏览器提交的 user、role 或 workspace 身份字段；最终权限由服务端的 User、WorkspaceMember 和 permission override 决定。

Authentication routes use the separate <code>AUTH_RATE_LIMIT_REQUESTS</code> limit. Old Logto users are not migrated; new accounts start from a clean state.

认证路由使用独立的 <code>AUTH_RATE_LIMIT_REQUESTS</code> 限额。旧 Logto 用户不迁移，新账号从零创建。

To create a local development administrator, confirm <code>AUTH_MODE=local_session</code> first, then run:

本地开发首次创建管理员前，先确认 <code>AUTH_MODE=local_session</code>，再运行：

~~~bash
make provision-local-admin EMAIL=owner@example.com NAME="Workspace Owner"
~~~

The command checks the workspace and email, then prompts for the password. It is allowed only in <code>ENVIRONMENT=development</code> and never places the password in command-line arguments.

命令会先检查 workspace 和邮箱，再交互式读取密码；仅允许 <code>ENVIRONMENT=development</code>，不会把密码放在命令行参数中。

The old <code>/api/v1/dev/oidc/*</code> routes and <code>DEV_OIDC_INTERNAL_SECRET</code> remain only for backend migration rollback. The frontend no longer calls them and does not store or send direct tokens in the browser.

旧的 <code>/api/v1/dev/oidc/*</code> 接口和 <code>DEV_OIDC_INTERNAL_SECRET</code> 仅为后端迁移回滚保留；前端不再调用它们，也不会在浏览器中保存或发送 direct token。

When <code>USE_FASTAPI_BACKEND=1</code>, chat history and AI SDK stream recovery also pass through the Next.js BFF to FastAPI. FastAPI checks <code>chat.read</code>/<code>chat.delete</code>, the current user, and workspace ownership. A page cursor can reference only chats belonging to that user and workspace.

设置 <code>USE_FASTAPI_BACKEND=1</code> 时，聊天历史和 AI SDK stream 恢复也通过 Next.js BFF 转发到 FastAPI。FastAPI 同时校验 <code>chat.read</code>/<code>chat.delete</code>、当前用户和 workspace；分页 cursor 只能引用当前用户在当前 workspace 的聊天。

## Knowledge-base migrations and grants / 知识库迁移与授权

<code>migrations/0001_knowledge_base_grants.sql</code> adds the transitional <code>KnowledgeBaseGrant</code> table. Each <code>KnowledgeSource</code> temporarily represents a knowledge base, and grants can target users or roles. Legacy knowledge bases without grants continue to use workspace permissions; granted bases are limited to matching users/roles.

<code>migrations/0001_knowledge_base_grants.sql</code> 新增过渡版 <code>KnowledgeBaseGrant</code> 表。当前每个 <code>KnowledgeSource</code> 暂时视为一个知识库，授权主体可以是用户或角色。没有 grant 的旧知识库继续使用 workspace 权限；存在 grant 的知识库只允许匹配的用户或角色访问。

After applying the migration, enable grants with:

应用迁移 SQL 后，通过以下配置开启授权：

~~~env
KNOWLEDGE_GRANTS_ENABLED=1
~~~

Run a read-only preflight:

执行只读预检：

~~~bash
uv run python -m app.db.migrate_knowledge_grants
~~~

Use <code>make migration-status</code> to check all four knowledge migrations and their dependencies together. After confirming that the target is a local development database, apply the migration:

使用 <code>make migration-status</code> 一次性检查四项知识库迁移及依赖。确认连接的是本地开发数据库后，再应用迁移：

~~~bash
make migration-status
make migrate-knowledge-grants
~~~

The runner refuses to apply migrations in staging/production. Shared environments must use the formal deployment migration process. <code>--apply</code> permits only loopback or Unix-socket database targets by default. Remote Supabase or cloud PostgreSQL is rejected even in development unless <code>--allow-remote</code> is explicitly supplied after backup and review.

runner 在 staging/production 环境会拒绝执行。共享环境必须走正式部署迁移流程。<code>--apply</code> 默认只允许 loopback 或 Unix-socket 数据库目标。即使在开发环境，远程 Supabase 或云 PostgreSQL 也会被拒绝；备份和人工复核后才可显式传入 <code>--allow-remote</code>。

## Independent KnowledgeBase entity / 独立 KnowledgeBase 实体

<code>migrations/0004_knowledge_bases.sql</code> backfills existing <code>KnowledgeSource</code> IDs into the independent <code>KnowledgeBase</code> table and redirects foreign keys from <code>KnowledgeBaseGrant</code>, <code>KnowledgeFile</code>, and <code>KnowledgeChunk</code>. The old table remains for rollback of legacy Next.js paths. FastAPI always uses <code>KnowledgeBase</code>, so this migration is required before using knowledge-base APIs.

<code>migrations/0004_knowledge_bases.sql</code> 会把现有 <code>KnowledgeSource</code> 的 ID 回填到独立 <code>KnowledgeBase</code> 表，并将 <code>KnowledgeBaseGrant</code>、<code>KnowledgeFile</code> 和 <code>KnowledgeChunk</code> 的外键切换到新表。旧表保留以便回滚旧 Next.js 路径。FastAPI 始终使用 <code>KnowledgeBase</code>，因此调用知识库 API 前必须完成此迁移。

Run the read-only preflight first:

先执行只读预检：

~~~bash
uv run python -m app.db.migrate_knowledge_bases
~~~

<code>make migration-status</code> checks required tables, columns, indexes, foreign keys, pgvector, HNSW validity, and backfilled foreign-key consistency. After confirming a local development target and reviewing the data, apply:

<code>make migration-status</code> 会检查必需表、列、索引、外键、pgvector、HNSW 索引有效性及回填后的外键完整性。确认连接的是本地开发数据库并完成人工核对后，应用迁移：

~~~bash
make migrate-knowledge-bases
~~~

Staging/production runners refuse local application. Use the reviewed deployment process in those environments.

staging/production 环境拒绝本地执行；正式环境应通过部署系统审查并应用 SQL。

Knowledge-base deletion is an idempotent database-first flow. FastAPI checks knowledge-base management permission, deletes the database record (cascading grants, file metadata, and chunks), then removes local/S3 objects using each file's provider. Object cleanup failures do not expose the deleted base again; the API returns <code>202</code> with the pending cleanup count and logs the error.

知识库删除采用数据库优先的幂等流程。FastAPI 先验证 knowledge-base 管理权限，再删除记录并由数据库级联清理 grant、文件元数据和切片，最后按文件对应的 provider 清理本地或 S3 对象。对象清理失败不会重新暴露已删除的知识库；接口返回 <code>202</code> 和待清理数量，并写入服务日志。

## Knowledge-file ingestion / 知识库文件入库

File ingestion is disabled by default. After applying <code>migrations/0002_knowledge_ingestion.sql</code> locally, configure:

文件入库默认关闭。本地应用 <code>migrations/0002_knowledge_ingestion.sql</code> 后，再设置：

~~~env
KNOWLEDGE_INGESTION_ENABLED=1
KNOWLEDGE_PROCESSING_STALE_SECONDS=900
KNOWLEDGE_STORAGE_DIR=storage/knowledge
KNOWLEDGE_STORAGE_PROVIDER=local
KNOWLEDGE_MAX_FILE_BYTES=104857600
KNOWLEDGE_EMBEDDINGS_ENABLED=1
EMBEDDING_API_KEY=your-embedding-provider-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_PROVIDER_TIMEOUT_SECONDS=60
~~~

Run the read-only preflight, then apply migrations only after confirming a local development database:

执行只读预检，确认连接的是本地开发数据库后再应用迁移：

~~~bash
uv run python -m app.db.migrate_knowledge_ingestion
make migrate-knowledge-ingestion
make migrate-knowledge-embeddings
~~~

Uploads support PDF, PowerPoint (<code>.pptx</code>), Excel (<code>.xlsx</code>), CSV, JSON, Markdown, and plain text. The API stores metadata and returns <code>pending</code>; a FastAPI background task parses, chunks with a fixed window, and sets <code>ready</code> or <code>failed</code>. With embeddings enabled, chunks are sent to an OpenAI-compatible <code>/embeddings</code> endpoint and stored in pgvector. Search checks workspace and knowledge-base permissions before cosine search. PDF, PPTX, and XLSX signatures are checked before object storage so a spoofed extension cannot trigger parsing.

上传支持 PDF、PowerPoint (<code>.pptx</code>)、Excel (<code>.xlsx</code>)、CSV、JSON、Markdown 和纯文本。API 先保存元数据并返回 <code>pending</code>，再由 FastAPI 后台任务解析、按固定窗口切片并更新为 <code>ready</code> 或 <code>failed</code>。开启 Embedding 后，切片会调用 OpenAI-compatible <code>/embeddings</code> 接口并写入 pgvector。搜索前会检查 workspace 和知识库权限，再执行 cosine search。PDF、PPTX 和 XLSX 在写入对象存储前校验文件签名，避免伪造扩展名进入解析。

The ingestion unit tests cover object reads, <code>processing</code>/<code>ready</code> state transitions, and chunk writes. Background processing uses in-process tasks. If the service restarts or a task exceeds <code>KNOWLEDGE_PROCESSING_STALE_SECONDS</code>, the file is marked <code>failed</code> and can be retried rather than remaining in <code>processing</code> forever.

入库流水线单测覆盖对象读取、<code>processing</code>/<code>ready</code> 状态流转和 chunk 写入。后台处理使用进程内任务；服务重启或任务超过 <code>KNOWLEDGE_PROCESSING_STALE_SECONDS</code> 后，文件会标记为 <code>failed</code>，用户可重新解析，避免永久停留在 <code>processing</code>。

Embedding requests time out after 60 seconds by default; set <code>EMBEDDING_PROVIDER_TIMEOUT_SECONDS</code> to 1–300 seconds. Local disk is the default storage provider. Production can use <code>KNOWLEDGE_STORAGE_PROVIDER=s3</code> with <code>KNOWLEDGE_S3_BUCKET</code>, optional endpoint, region, and credentials. Upload, background reads, and deletion then use the S3-compatible provider. Real object-store and database verification remains environment-specific.

Embedding 请求默认在 60 秒后超时；可将 <code>EMBEDDING_PROVIDER_TIMEOUT_SECONDS</code> 调整到 1–300 秒。默认使用本地磁盘。生产环境可设置 <code>KNOWLEDGE_STORAGE_PROVIDER=s3</code>，并提供 <code>KNOWLEDGE_S3_BUCKET</code>、可选 endpoint、region 和 credentials，让上传、后台读取及删除统一使用 S3-compatible storage。真实对象存储和数据库验证仍需在部署环境完成。

When grant or independent-entity flags are disabled, product, content, and knowledge-base lists keep their existing workspace-level behavior so pending migrations do not break existing routes. Grant-management routes also require <code>members.manage</code>; authorization changes are written to <code>AuditLog</code>.

grant 或独立实体开关关闭时，商品、内容和知识库列表保持原有 workspace 级行为，避免未执行数据库迁移时影响现有接口。grant 管理接口还要求 <code>members.manage</code>；授权变更会写入 <code>AuditLog</code>。

## Verification / 测试和代码检查

Run the backend checks with:

运行后端检查：

~~~bash
make test
make lint
~~~

PostgreSQL/Redis integration tests do not read the regular <code>POSTGRES_URL</code> or <code>REDIS_URL</code>. Provide dedicated test endpoints to avoid shared databases:

PostgreSQL/Redis 集成测试不会读取普通的 <code>POSTGRES_URL</code> 或 <code>REDIS_URL</code>。必须显式提供专用测试地址，避免误连共享数据库：

~~~bash
FASTAPI_TEST_POSTGRES_URL=postgresql://asianode:asianode@127.0.0.1:5432/asianode \
FASTAPI_TEST_REDIS_URL=redis://127.0.0.1:6379/0 \
make test-integration
~~~

For S3-compatible storage, provide a dedicated test bucket:

验证 S3-compatible storage 时，显式指定专用测试 bucket：

~~~bash
FASTAPI_TEST_S3_ENDPOINT_URL=http://127.0.0.1:9000 \
FASTAPI_TEST_S3_BUCKET=asianode-test \
FASTAPI_TEST_S3_ACCESS_KEY_ID=minio \
FASTAPI_TEST_S3_SECRET_ACCESS_KEY=minio-secret \
make test-integration
~~~

To test a real embedding provider, provide a dedicated API key and endpoint:

验证真实 Embedding provider 时，显式指定 provider 地址和专用 API Key：

~~~bash
FASTAPI_TEST_EMBEDDING_BASE_URL=https://api.openai.com/v1 \
FASTAPI_TEST_EMBEDDING_API_KEY=your-test-key \
FASTAPI_TEST_EMBEDDING_MODEL=text-embedding-3-small \
make test-integration
~~~

A real Agent-provider smoke test can also run a controlled workflow:

真实 Agent provider 的 smoke test 也可验证受控 workflow：

~~~bash
FASTAPI_TEST_AGENT_BASE_URL=https://api.deepseek.com/v1 \
FASTAPI_TEST_AGENT_API_KEY=your-test-key \
FASTAPI_TEST_AGENT_MODEL=deepseek-chat \
make test-integration
~~~

Provider integration checks make real requests and may incur charges. Use dedicated test keys. Remote providers are rejected unless <code>FASTAPI_ALLOW_REMOTE_INTEGRATION=1</code> is set. The Agent smoke test makes one direct response request without knowledge tools and limits the run to one step.

Provider 集成检查会发出真实请求并可能产生费用，应使用专用测试 key。默认拒绝远程 provider；只有设置 <code>FASTAPI_ALLOW_REMOTE_INTEGRATION=1</code> 后才允许执行。Agent smoke test 只发起一次不带知识库工具的直接回答，并将最大步数限制为 1。

The integration command checks all four migrations, performs a temporary Redis key round-trip and SSE capture/resume, and, when configured, uploads/reads/deletes a temporary object, creates an embedding, or runs a controlled <code>/chat/completions</code> request. Without <code>FASTAPI_TEST_*</code> values, external integration checks are explicitly skipped. Never use a production bucket.

集成命令只读检查四项知识库迁移，执行带过期时间的 Redis 临时 key 往返和真实 SSE capture/resume；配置对应变量后，还会上传/读取/删除临时对象、生成 embedding 或执行受控的 <code>/chat/completions</code> 请求。未提供 <code>FASTAPI_TEST_*</code> 时，外部集成检查会明确跳过。不要使用生产 bucket。

## Backend structure / 后端目录结构

~~~text
app/
├── api/
│   ├── routes/
│   │   ├── chats.py
│   │   ├── admin_knowledge_grants.py
│   │   ├── admin_members.py
│   │   ├── chat.py
│   │   ├── content.py
│   │   ├── dev_oidc.py
│   │   ├── health.py
│   │   ├── knowledge_bases.py
│   │   ├── knowledge_files.py
│   │   ├── knowledge_search.py
│   │   ├── knowledge_sources.py
│   │   ├── me.py
│   │   └── products.py
│   ├── core/
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── knowledge_access.py
│   │   ├── permissions.py
│   │   └── workspace_access.py
│   └── router.py
└── main.py
tests/
├── test_auth.py
├── test_content.py
└── test_health.py
~~~

## Roadmap / 后续建设顺序

- Completed: product queries and advanced filters were migrated and compared with Next.js results.
- 已完成：商品查询及高级过滤已迁移，并与 Next.js 查询结果完成对比。
- Completed: content search routes were migrated.
- 已完成：内容查询接口迁移。
- In progress: authentication configuration and Logto token verification.
- 进行中：认证配置与 Logto Token 验证。
- In progress: workspace/member/role/knowledge-base permissions. The independent KnowledgeBase entity, backfill SQL, migration status, and remote-target safety gate are implemented; local migration and real-data validation remain.
- 进行中：workspace、成员、角色和知识库权限模型。独立 KnowledgeBase 实体、回填 SQL、统一迁移状态及远程目标安全门已完成；本地数据库迁移和真实数据验证待完成。
- In progress: file upload, parsing, chunking, embeddings, and permission-filtered vector search. These features are disabled by default pending local migration and real storage/vector verification.
- 进行中：文件上传、解析、切片、Embedding 和带权限过滤的向量检索。功能默认关闭，等待本地迁移、真实对象存储和向量验证。
- Completed: S3-compatible storage and AI Agent routes with knowledge-search tools.
- 已完成：S3-compatible 对象存储和带知识库检索工具的 AI Agent 接口。

Product and content queries now run through FastAPI and have been compared with real Next.js query results.

商品和内容查询已迁移至 FastAPI，并完成与 Next.js 查询结果的真实数据对比。

FastAPI handles workspace authorization, model calls, SSE, message persistence and reads, read-only tools, and resumable Redis streams. Real Redis deployment and browser disconnect/recovery verification remain outstanding.

当前聊天由 FastAPI 负责 workspace 权限、模型调用、SSE、消息持久化与读取、只读工具调用和 Redis 可恢复流；真实 Redis 部署和浏览器断线恢复验证仍待完成。
