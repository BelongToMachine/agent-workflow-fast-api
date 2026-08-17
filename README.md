# Asianode FastAPI

Asianode Agent 的独立 FastAPI 后端项目。当前版本已经接管聊天生成链路，后续逐步加入认证、企业隔离、知识库和 AI Agent 能力。

## 技术栈

- Python 3.12+
- FastAPI
- Pydantic Settings
- Uvicorn
- Pytest
- Ruff

## 本地运行

推荐使用 [uv](https://docs.astral.sh/uv/) 管理环境和依赖：

```bash
make setup
make dev
```

后续日常启动直接执行：

```bash
make dev
```

服务启动后访问：

- API 根路径：http://127.0.0.1:8000/
- 健康检查：http://127.0.0.1:8000/api/v1/healthz
- 商品查询：`GET http://127.0.0.1:8000/api/v1/products?workspace_id={workspace_id}`
- 内容查询：`POST http://127.0.0.1:8000/api/v1/content/search`
- 当前用户：`GET http://127.0.0.1:8000/api/v1/me`
- 知识库数据源：`GET http://127.0.0.1:8000/api/v1/knowledge-sources?workspace_id={workspace_id}`
- 知识库列表：`GET http://127.0.0.1:8000/api/v1/knowledge-bases?workspace_id={workspace_id}`
- 知识库创建：`POST http://127.0.0.1:8000/api/v1/knowledge-bases?workspace_id={workspace_id}`
- 知识库重命名：`PATCH http://127.0.0.1:8000/api/v1/knowledge-bases/{knowledge_base_id}?workspace_id={workspace_id}`
- 知识库删除：`DELETE http://127.0.0.1:8000/api/v1/knowledge-bases/{knowledge_base_id}?workspace_id={workspace_id}`
- 成员列表：`GET http://127.0.0.1:8000/api/v1/admin/members?workspace_id={workspace_id}`
- 成员权限更新：`PATCH http://127.0.0.1:8000/api/v1/admin/members?workspace_id={workspace_id}`
- 聊天历史：`GET http://127.0.0.1:8000/api/v1/chats?workspace_id={workspace_id}`
- 删除当前 workspace 的聊天历史：`DELETE http://127.0.0.1:8000/api/v1/chats?workspace_id={workspace_id}`
- 聊天消息：`GET http://127.0.0.1:8000/api/v1/chats/{chat_id}/messages?workspace_id={workspace_id}`
- 知识库授权列表：`GET http://127.0.0.1:8000/api/v1/admin/knowledge-base-grants?workspace_id={workspace_id}`
- 知识库授权新增/更新：`PUT http://127.0.0.1:8000/api/v1/admin/knowledge-base-grants?workspace_id={workspace_id}`
- 知识库授权删除：`DELETE http://127.0.0.1:8000/api/v1/admin/knowledge-base-grants/{grant_id}?workspace_id={workspace_id}`
- 本地 Mock OIDC consent：`POST http://127.0.0.1:8000/api/v1/dev/oidc/consent`
- 聊天接口：`POST http://127.0.0.1:8000/api/v1/chat`
- Chat Stream 恢复：`GET http://127.0.0.1:8000/api/v1/chat/{chat_id}/stream?workspace_id={workspace_id}`
- 独立 Agent 查询：`POST http://127.0.0.1:8000/api/v1/agents/query?workspace_id={workspace_id}`
- 知识库迁移状态：`make migration-status`
- 知识库文件列表：`GET http://127.0.0.1:8000/api/v1/knowledge-bases/{knowledge_base_id}/files?workspace_id={workspace_id}`
- 知识库文件上传：`POST http://127.0.0.1:8000/api/v1/knowledge-bases/{knowledge_base_id}/files?workspace_id={workspace_id}`
- 知识库文件删除：`DELETE http://127.0.0.1:8000/api/v1/knowledge-bases/{knowledge_base_id}/files/{file_id}?workspace_id={workspace_id}`
- 知识库向量检索：`POST http://127.0.0.1:8000/api/v1/knowledge-bases/{knowledge_base_id}/search?workspace_id={workspace_id}`
- Swagger：http://127.0.0.1:8000/docs

本地运行时，FastAPI 会读取仓库根目录的 `.env.local`，因此可以复用现有的
`DEEPSEEK_API_KEY`。部署到其他环境时，请通过环境变量提供 API Key。

## 当前前端切换状态

当根目录 `.env.local` 中设置以下变量时，Web 端聊天请求会进入 FastAPI：

```env
USE_FASTAPI_BACKEND=1
NEXT_PUBLIC_USE_FASTAPI_BACKEND=1
FASTAPI_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FASTAPI_BASE_URL=http://127.0.0.1:8000
```

聊天请求会先发送到 Next.js `/api/chat` BFF，再由 BFF 通过签名的 NextAuth bridge 转发到
FastAPI `8000` 端口；FastAPI 负责 workspace 权限、消息持久化、模型调用和 SSE 返回。
这样浏览器不会直接提交 userId、role 或 workspaceId 作为可信身份。

设置 `REDIS_URL` 后，FastAPI 会按 chat 保存短期 SSE chunks，并提供
`GET /api/v1/chat/{chat_id}/stream` 给 AI SDK 自动断线重连。恢复接口会再次校验当前用户、
workspace 和 chat 归属；没有配置 Redis 时会退化为普通 SSE，不阻塞聊天请求。

独立 Agent 查询接口只接受预定义的只读工具名和工具参数，不接受调用方提交的 user、role、
permission 或 workspace 身份字段。FastAPI 会从 Bearer Token/NextAuth bridge 取得身份，
先检查 workspace 的 `knowledge.read` 权限，再执行产品、内容或指定知识库搜索。

当当前用户具备 `knowledge.read` 时，FastAPI 会向模型注册只读的
`searchProductsTool`、`searchContentTool`、`listKnowledgeBasesTool` 和
`listKnowledgeFilesTool`；知识库向量检索开关开启时再注册
`searchKnowledgeBaseTool`。模型应先通过 `listKnowledgeBasesTool` 发现当前用户可以读取的
知识库，再使用返回的 ID 查看文件状态或检索内容。模型产生 tool call 后由 FastAPI 服务端
执行，工具内部继续复用 workspace 和知识库授权过滤；客户端不能直接伪造工具结果。

## 安全防护

FastAPI 默认对 `/api/v1/*` 开启进程内滑动窗口限流：普通接口默认每分钟 120 次，聊天
每分钟 20 次，文件接口每分钟 30 次。健康检查和 OpenAPI 文档不计入限流。当前实现适合
单实例部署；部署多个实例前需要把限流状态迁移到 Redis，并在反向代理层配置可信客户端 IP。

## 当前认证行为

商品、内容和聊天接口都经过统一的 Bearer Token 依赖：

- `development` 环境且 `AUTH_REQUIRED=false` 时，未携带 Token 会使用明确标记的 `development-user`，方便本地开发。
- `staging` 和 `production` 环境默认要求 Token；即使没有显式设置 `AUTH_REQUIRED` 也不会允许匿名访问。
- 配置 `AUTH_ISSUER`、`AUTH_AUDIENCE` 和 `AUTH_JWKS_URL` 后，FastAPI 会校验 JWT 签名、`kid`、issuer、audience、过期时间和 `sub`。
- 当前 NextAuth 的服务端 cookie 不是 OIDC access token，不能直接交给 FastAPI 当作普通 JWT 解码。过渡阶段应由 Next.js BFF 或 Logto 登录流程提供 Bearer access token。

本地 Mock OIDC 目前也已经迁移了 consent/code 签发逻辑：`/dev/oidc` 页面仍通过
Next.js BFF 发起请求，Next.js 只验证当前 NextAuth session 并发送签名的临时 actor
context，FastAPI 负责校验 consent 参数、权限和 loopback redirect，并生成与原实现
兼容的 5 分钟 HMAC code。FastAPI 生成的 code 可以由现有 Next.js result 页面继续验证。

如果要使用单独的桥接密钥，在根目录 `.env.local` 和 FastAPI 运行环境中同时设置：

```env
DEV_OIDC_INTERNAL_SECRET=your-local-development-secret
```

未设置时，本地会回退到 `AUTH_SECRET`；生产/staging 环境会直接关闭该 dev endpoint。

成员管理迁移期间，Next.js BFF 使用签名的 NextAuth bridge 调用 FastAPI。可以通过
`NEXTAUTH_BRIDGE_SECRET` 配置独立的 bridge secret；未设置时使用 `AUTH_SECRET`。
FastAPI 会校验 bridge 的 HMAC 签名和 5 分钟有效期，不接受浏览器提交的 userId、role
或 workspaceId 作为可信身份。

聊天历史和 AI SDK 的 chat stream 恢复在 `USE_FASTAPI_BACKEND=1` 时也通过 Next.js BFF 转发到 FastAPI。FastAPI 会同时
校验 `chat.read`/`chat.delete`、当前用户和 workspace；分页 cursor 只能引用当前用户在
当前 workspace 的聊天。

## 知识库授权迁移

`migrations/0001_knowledge_base_grants.sql` 新增了过渡版
`KnowledgeBaseGrant` 表。当前每个 `KnowledgeSource` 暂时视为一个知识库，授权主体
可以是用户或角色。没有 grant 的旧知识库继续使用 workspace 权限；存在 grant 的知识库
只允许匹配的用户/角色访问。

应用迁移 SQL 后，再设置：

```env
KNOWLEDGE_GRANTS_ENABLED=1
```

可以先执行只读预检：

```bash
uv run python -m app.db.migrate_knowledge_grants
```

也可以一次性查看四个知识库迁移及其依赖是否完整：

```bash
make migration-status
```

确认连接的是本地开发数据库后，再显式执行：

```bash
make migrate-knowledge-grants
```

runner 在 staging/production 环境会拒绝执行；共享环境应通过正式部署迁移流程应用
`migrations/0001_knowledge_base_grants.sql`。

`--apply` 默认只允许 loopback 或 Unix-socket 数据库目标。即使 `ENVIRONMENT=development`，
远程 Supabase、云 PostgreSQL 等目标也会被拒绝；只有经过备份和人工复核后，才可以显式
增加 `--allow-remote`。

## 独立 KnowledgeBase 实体

`migrations/0004_knowledge_bases.sql` 会把现有 `KnowledgeSource` 以原 ID 回填到独立的
`KnowledgeBase` 表，并将 `KnowledgeBaseGrant`、`KnowledgeFile` 和 `KnowledgeChunk` 的
外键切换到新表。旧表会保留，方便旧 Next.js 路径回滚；FastAPI 通过开关选择查询边界：

```env
KNOWLEDGE_BASE_ENTITY_ENABLED=1
```

先执行只读预检：

```bash
uv run python -m app.db.migrate_knowledge_bases
```

`make migration-status` 会只读检查四个迁移、pgvector 和独立知识库外键是否完整。

确认连接的是本地开发数据库、完成数据核对后，再显式应用：

```bash
make migrate-knowledge-bases
```

迁移应用前不要打开 `KNOWLEDGE_BASE_ENTITY_ENABLED`；开关关闭时 FastAPI 继续使用
`KnowledgeSource` 兼容路径。runner 在 staging/production 环境会拒绝本地执行，正式环境
应通过部署系统审查并应用 SQL。

知识库删除是数据库优先的幂等流程：FastAPI 先验证知识库级 `manage` 权限，再删除知识库
记录，让数据库级联清理 grant、文件元数据和切片，最后按每个文件记录的 provider 清理本地
或 S3 对象。对象存储清理失败不会重新暴露已删除的知识库，接口会返回 `202` 和待清理数量，
并写入服务日志，便于后续接入持久化 cleanup worker。

## 知识库文件入库

文件入库默认关闭。确认本地数据库已经应用 `migrations/0002_knowledge_ingestion.sql` 后，设置：

```env
KNOWLEDGE_INGESTION_ENABLED=1
KNOWLEDGE_STORAGE_DIR=storage/knowledge
KNOWLEDGE_STORAGE_PROVIDER=local
KNOWLEDGE_MAX_FILE_BYTES=26214400
KNOWLEDGE_EMBEDDINGS_ENABLED=1
EMBEDDING_API_KEY=your-embedding-provider-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

可以先执行只读预检：

```bash
uv run python -m app.db.migrate_knowledge_ingestion
```

确认连接的是本地开发数据库后，再显式执行：

```bash
make migrate-knowledge-ingestion
make migrate-knowledge-embeddings
```

上传接口目前支持 PDF、Excel (`.xlsx`)、CSV、JSON、Markdown 和纯文本。接口先保存
文件元数据并返回 `pending`，再由 FastAPI background task 解析、按固定窗口切片并更新为
`ready` 或 `failed`。打开 Embedding 开关后，切片会调用 OpenAI-compatible `/embeddings`
接口并写入 pgvector；搜索接口会先验证 workspace/知识库权限，再执行 cosine search。
默认使用本地磁盘。生产环境可以设置 `KNOWLEDGE_STORAGE_PROVIDER=s3`，并提供
`KNOWLEDGE_S3_BUCKET`、可选的 `KNOWLEDGE_S3_ENDPOINT_URL`、region 和 credentials，
FastAPI 会让上传、后台解析读取和删除统一经过 S3-compatible storage；真实对象存储和数据库
验证仍待部署环境验证。

在知识库 grant 或独立实体开关关闭时，产品、内容和知识库列表保持原有 workspace 级行为，
避免数据库迁移尚未执行时导致现有接口不可用。

管理员 grant 管理接口同样受该开关保护，并要求 `members.manage` 权限。Next.js 的
`/api/admin/knowledge-base-grants` BFF 只负责 NextAuth actor 校验和签名 bridge，实际
授权读写由 FastAPI 完成；更新和删除操作会写入 `AuditLog`。

本地可以使用以下配置测试未登录请求是否被拒绝：

```env
AUTH_REQUIRED=true
```

## 测试和代码检查

```bash
make test
make lint
```

## 当前目录结构

```text
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
```

## 后续建设顺序

1. ✅ 迁移商品查询及高级过滤，并与 Next.js 查询结果做对比。
2. ✅ 迁移内容查询接口。
3. 🚧 完成认证配置，并接入 Logto Token 验证。
4. 🚧 基于现有 Workspace/WorkspaceMember 完成企业、成员、角色和知识库权限模型；独立 KnowledgeBase 实体代码、回填 SQL、统一 migration status 和远程目标安全门已完成，等待本地数据库迁移与真实数据验证。
5. 🚧 增加文件上传、解析、切片、Embedding 和带权限过滤的向量检索；默认关闭，等待本地 migration、真实对象存储和向量验证。
6. ✅ 增加 S3-compatible 对象存储和带知识库检索工具的 AI Agent 接口。

商品和内容查询当前已经迁移到 FastAPI，并完成了与 Next.js 查询结果的真实数据对比。

当前聊天接口由 FastAPI 负责 workspace 权限、模型调用、SSE、消息持久化、消息读取、只读工具调用和 Redis 可恢复流；真实 Redis 部署和浏览器断线恢复验证仍待完成。
