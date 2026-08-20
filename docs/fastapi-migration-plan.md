# Next.js 后端迁移到 FastAPI 计划

## 目标

在保留现有 Next.js 前端和后端代码的前提下，将业务后端能力逐步迁移到独立的 FastAPI 服务。本阶段只聚焦现有 Web 系统；移动端 API 和 Native App 暂不纳入当前迁移验收范围，作为后续扩展阶段保留。

## 当前范围

- 当前范围：Next.js Web、Next.js BFF、FastAPI、企业 workspace/role、知识库权限、文件入库和 Web AI Chat。
- 当前不做：移动端 UI、Logto Native App、移动端专用 API 契约和移动端 Token 流程。
- 移动端相关设计只保留兼容性，不为了移动端提前引入额外复杂度。

迁移原则：

- 保留旧的 Next.js 后端代码，逐个模块迁移。
- 每迁移一个模块，都可以独立验证和回滚。
- 先迁移低风险的只读接口，再迁移权限、文件处理和 AI 流式能力。
- 不让 Next.js 和 FastAPI 同时管理同一张数据库表的迁移。
- 在知识库查询和 AI Agent 工具调用阶段都执行权限检查。

## 目标架构

```text
当前：
Next.js 前端 → Next.js Route Handler → Drizzle / Redis / AI

迁移期间：
Next.js 前端 → Next.js BFF/代理 → FastAPI → PostgreSQL / Redis / AI

最终：
Next.js Web → Next.js BFF / Logto → FastAPI → 数据库 / 向量库 / AI Worker

```

后续移动端阶段再扩展为：

```text
移动端 → Logto Access Token → FastAPI
```

## 后端迁移计划表

| 阶段 | 优先级 | 主要任务 | 交付物 | 验收标准 | 状态 |
|---|---:|---|---|---|---|
| 0. 基础准备 | P0 | 创建 FastAPI 项目、配置 `uv`、添加测试和 Docker 基础 | `asianode-fastapi` 项目骨架 | FastAPI 能启动，`/docs` 可访问 | [x] ✅ 已完成：已提供本地 PostgreSQL/pgvector + Redis Compose 编排和 Makefile 快捷命令 |
| 1. 前后端联调 | P0 | 添加 `USE_FASTAPI_BACKEND`、Next.js 代理和 FastAPI 健康检查 | `/api/fastapi/health`、`/fastapi-test` | Next.js 可以请求 FastAPI | [x] ✅ 已完成 |
| 2. API 契约整理 | P0 | 梳理现有 API、参数、返回格式和错误格式 | API 清单、Pydantic Schema | 新旧接口响应结构明确 | [x] ✅ 已完成：`docs/fastapi-api-contracts.md` 已覆盖当前 FastAPI/BFF 迁移接口、权限、feature flag、输入输出和错误约定；OpenAPI 路由清单与 request model 测试已加入 |
| 3. 数据库接入 | P0 | FastAPI 只读连接现有 PostgreSQL | SQLAlchemy 数据访问层 | FastAPI 能读取现有业务数据 | [x] ✅ 已完成：SQLAlchemy/asyncpg 只读连接已验证 |
| 4. 迁移只读接口 | P0 | 迁移商品、内容、价格等查询能力 | `/api/v1/products`、`/api/v1/content` | 新旧接口返回结果一致 | [x] ✅ 已完成：商品和内容只读查询、筛选及真实数据对比已完成 |
| 5. 认证适配 | P0 | 临时适配 NextAuth，后续接入 Logto | `get_current_user()`、Token 验证 | FastAPI 能识别 Web 当前用户 | [x] ✅ 当前 Web 阶段已完成：Bearer/OIDC JWT 验证、`GET /api/v1/me`、本地 Mock OIDC consent、开发环境未登录时强制进入 Dev OIDC 用户确认页、NextAuth BFF bridge 和 staging/production 启动安全配置检查已完成；正式 Logto tenant 配置和移动端 Token 属于后续认证阶段 |
| 6. 企业和角色模型 | P1 | 增加企业、成员、角色和组织隔离 | `organizations`、`memberships`、`roles` | 不同企业数据互不可见 | [ ] 🚧 进行中：当前以 `Workspace`/`WorkspaceMember` 作为 Web 阶段企业边界，角色、权限覆盖、成员管理、token workspace binding 和可重复的跨 workspace/角色隔离回归测试已完成；[x] external/contractor role 的知识库授权解析已收紧为 grant-only，并同时匹配 workspace role 与 Token role；[x] 已增加只读 knowledge integrity 检查 workspace 归属；真实跨企业数据验证与独立组织模型评估待完成 |
| 7. 知识库权限 | P1 | 建立用户/角色与知识库的授权关系 | `knowledge_bases`、`knowledge_base_grants` | 用户只能访问授权知识库 | [ ] 🚧 进行中：过渡版 `KnowledgeBaseGrant` SQL、migration runner、[x] 有序全量 migration runner（单事务、默认本地目标、可重复执行）、[x] migration status 会校验必需列、索引、外键和 HNSW 索引有效性、安全目标检查、只读 knowledge integrity 数据检查、user/role 授权解析、产品/内容/数据源/文件/向量检索过滤、[x] FastAPI 知识库创建/重命名/删除和管理员 grant CRUD、[x] KnowledgeBase 生命周期路由事务、workspace 条件、审计与对象清理回归测试、[x] `/settings/knowledge-bases` 生命周期管理 UI、[x] 本地 PostgreSQL/pgvector Compose 已完成；真实数据库 migration 执行与数据验证待完成 |
| 8. 管理接口迁移 | P1 | 迁移成员管理、权限分配和管理员操作 | `/api/v1/admin/...` | 管理员可以分配角色和知识库权限 | [x] ✅ FastAPI 已完成成员列表、角色和权限覆盖的 GET/PATCH，以及知识库 grant 的 GET/PUT/DELETE；Next.js BFF、`/settings/members` 成员权限页和 `/settings/knowledge-bases` 知识库授权页均已接入 |
| 9. 文件和知识库入库 | P1 | 上传文件、解析、切片、向量化 | 文件上传 API、后台任务 | PDF/Excel/CSV 可以进入知识库 | [ ] 🚧 进行中：代码链路已完成（[x] FastAPI multipart 上传/解析/切片、[x] 上传路由权限、workspace/knowledge base 存储边界与冲突补偿回归、[x] 后台入库流水线 processing/ready 与 chunk 写入测试、[x] PDF/XLSX 内容签名校验、[x] local/S3-compatible storage、[x] 显式配置保护的 S3-compatible upload/read/presigned-download smoke test、[x] 可选 pgvector/Embedding provider、[x] 显式配置保护的 Embedding provider 1536 维向量 smoke test、[x] Embedding provider 超时和响应校验 mock 覆盖、[x] 有序全量 migration runner、[x] Next.js BFF、[x] 管理员 Web 文件管理页、[x] 向量检索路由 workspace/knowledge base 运行时隔离回归、[x] Chat 附件路由 workspace 权限与 workspace/user 存储隔离回归、[x] 本地 pgvector Compose）；真实数据库 migration、对象存储和向量验证待完成。Web Chat 图片上传已增加独立 FastAPI 管道、PNG/JPEG magic bytes 校验和旧 Vercel Blob 回滚开关，真实 provider 验证待完成 |
| 10. AI Agent 迁移 | P2 | 迁移模型调用、工具调用和会话逻辑 | `/api/v1/agents/...` | Agent 可以调用 FastAPI 业务接口 | [ ] 🚧 进行中：FastAPI 已迁移只读产品/内容搜索、权限检查后的知识库发现、文件状态查看与语义搜索工具、单知识库/单文件上下文工具、Web 图片附件转换，并提供独立 `POST /api/v1/agents/query` 和不持久化 Chat/Message 的有界 `POST /api/v1/agents/run`；真实 provider 验证待完成 |
| 11. 流式聊天迁移 | P2 | 迁移 SSE、消息保存和 Redis 状态 | `/api/v1/chat/.../stream` | Web 端聊天流式响应正常 | [ ] 🚧 进行中：FastAPI 聊天生成、SSE、Chat/Message 持久化、消息读取、多轮只读 tool loop、Redis chunks 存储、独立 stream 恢复路由、Redis-backed rate limit 和本地 Redis Compose 已完成；[x] 已增加聊天持久化新建/assistant 回写、跨 workspace Chat ID 冲突和跨用户归属回归；[x] 已增加 stream 恢复路由 workspace/Chat owner 校验、跨用户拒绝和跨 workspace 空响应回归；[x] 已增加 HTTP middleware 限流回归（正常响应头、429 错误码与 Retry-After）；[x] 已增加显式地址的 PostgreSQL/Redis 集成 smoke test；[x] 已增加真实 Redis capture/resume smoke test；[x] 已增加 Playwright 浏览器断线后 reload 并再次恢复 SSE 的端到端验证；真实 provider/Redis 部署环境验证待完成 |
| 12. 移动端 API | P2 | 完善公开 API、Logto Native App 和移动端 Token | Mobile API 契约 | 移动端可以直接访问 FastAPI | [ ] ⏸️ 暂缓：当前阶段只做 Web 系统，移动端待 Web 版本稳定后再启动 |
| 13. 切换和清理 | P3 | 开启正式开关、删除重复的 Next.js 后端代码 | 迁移完成版本 | 旧接口停止使用且无回归问题 | [ ] ⬜ 待开始 |

## 具体接口迁移顺序

| Next.js 现有能力 | FastAPI 目标接口 | 建议 |
|---|---|---|
| 商品查询 | `GET /api/v1/products` | [x] ✅ 基础查询、高级过滤、价格/运营/文档字段及新旧结果对比已完成 |
| 内容查询 | `POST /api/v1/content/search` | [x] ✅ JSON body、筛选参数、来源文件过滤及新旧结果对比已完成 |
| 当前用户 | `GET /api/v1/me` | [x] ✅ 已迁移身份、Workspace membership、role 和权限覆盖的只读查询 |
| 知识库列表 | `GET /api/v1/knowledge-sources`、`GET /api/v1/knowledge-bases` | [x] ✅ 已迁移只读数据源查询，并增加过渡版知识库列表、创建和重命名 API；列表和 Agent 发现工具均接入 workspace membership 与知识库授权过滤 |
| 知识库授权过滤 | 商品、内容、知识库列表 | [x] ✅ 已增加 `KnowledgeBaseGrant` 过渡表和 user/role 过滤；由 `KNOWLEDGE_GRANTS_ENABLED` 控制渐进启用 |
| 知识库授权管理 | `/api/v1/admin/knowledge-base-grants` | [x] ✅ 管理员可按 workspace 查询、添加/更新、删除用户或角色授权；写操作记录 `AuditLog`，Next.js BFF 和 `/settings/knowledge-bases` Web 管理页已接入 |
| 知识库迁移状态与安全检查 | `make migration-status`、`make knowledge-integrity`、各 `migrate_knowledge_*` runner | [x] ✅ 已增加四个 migration、必需列/索引/外键、pgvector/HNSW 有效性和跨 workspace/knowledge base/file 的数据完整性检查、本地 PostgreSQL/pgvector Compose 和 Makefile 命令；`--apply` 默认拒绝远程数据库目标，当前远程 Supabase 仅完成 preflight，未执行 schema 写入 |
| 本地 Mock OIDC consent | `POST /api/v1/dev/oidc/consent` | [x] ✅ consent 参数、权限、loopback redirect 和 HMAC code 已迁移；开发环境无 session 时由 Next.js 入口强制跳转到 Dev OIDC 用户确认页，确认完成后可返回原始 Web 路径；Next.js BFF 保留 session 桥接 |
| 历史记录 | `GET/DELETE /api/v1/chats` | [x] ✅ 已迁移聊天历史查询和清空能力；Next.js BFF 保留原路径，FastAPI 增加 workspace 和 cursor 归属校验 |
| 聊天消息读取 | `GET /api/v1/chats/{id}/messages` | [x] ✅ 已迁移消息读取、当前用户/workspace 归属校验和 Next.js BFF 转发 |
| 成员管理 | `/api/v1/admin/members` | [x] ✅ GET/PATCH、成员权限校验、owner 保护和 AuditLog 已迁移；Next.js BFF 保留 session 桥接 |
| 跨 workspace/角色隔离测试 | workspace membership、permission override、知识库列表 | [x] ✅ 已增加运行时模拟测试：无目标 workspace membership 返回 403、deny override 生效、external/contractor role 必须通过显式 grant、role grant 同时匹配 workspace role 和 Token role、知识库列表始终携带授权 ID（包括空授权列表），不能回退为 workspace 全量结果 |
| 文件上传 | `/api/v1/knowledge-bases/{id}/files` | [ ] 🚧 代码迁移已完成：FastAPI 已支持 multipart 上传、权限检查、大小/类型与 PDF/XLSX 内容签名校验、local/S3-compatible storage、后台解析和切片；[x] 路由测试覆盖 workspace/knowledge base 存储边界、数据库参数、后台任务调度和数据库冲突后的对象清理；processing/ready 与 chunk 写入已有 service-level 测试；显式 `FASTAPI_TEST_S3_*` 集成 smoke test 已覆盖真实对象上传、读取和 presigned 下载；Next.js BFF 与 `/settings/knowledge-bases/files` 管理页已接入；迁移 SQL 应用、真实上传和处理状态验证待完成 |
| 知识库向量检索 | `POST /api/v1/knowledge-bases/{id}/search` | [ ] 🚧 已实现 Embedding provider、pgvector cosine search 和 workspace/知识库权限过滤；[x] 路由级回归测试确认权限检查与最终 SQL 查询同时携带 workspace/knowledge base 条件；[x] provider 超时、乱序响应、向量维度和传输失败已有 mock 覆盖；[x] 已提供显式 `FASTAPI_TEST_EMBEDDING_*` 真实 provider smoke test；默认关闭，等待本地 migration 验证 |
| 知识库管理 | `POST/PATCH/DELETE /api/v1/knowledge-bases` | [ ] 🚧 代码迁移已完成：FastAPI 已支持通过 feature flag 切换到独立 `KnowledgeBase` 创建/重命名/删除路径，并保留 `KnowledgeSource` 兼容路径；[x] 路由回归覆盖写入/更新 workspace 条件、审计调用、数据库级联和 local/S3 对象清理；Next.js BFF 与 `/settings/knowledge-bases` 已接入创建、重命名、删除和授权管理；数据库应用与真实数据验证待完成 |
| 文档管理 | `/api/v1/documents` | [x] ✅ FastAPI 已迁移文档详情、版本保存/手动编辑、按时间删除；Next.js `/api/document` BFF 已接入 |
| AI Chat | `/api/v1/chat` | [ ] 🚧 FastAPI 已调用 DeepSeek、返回 AI SDK SSE、保存 user/assistant message，保留 Web JPEG/PNG 图片附件并转换为模型 `image_url`，并执行带权限检查的产品/内容/知识库发现与只读 tool loop；[x] 聊天持久化回归覆盖新建 Chat/用户消息与 assistant 回写的 workspace 参数、跨 workspace Chat ID 冲突和跨用户归属拒绝；[x] 模型选择已在 FastAPI 边界执行公开 capability allowlist 和安全 fallback；[x] provider timeout 已配置化并有 SSE/tool-loop mock 覆盖；Web 图片上传已支持独立 FastAPI 管道，默认关闭并保留 Vercel Blob 回滚；真实 storage/provider 和独立 Agent workflow provider 验证待完成 |
| Chat Stream | `/api/v1/chat/{id}/stream` | [ ] 🚧 FastAPI Redis 可恢复流和 Next.js BFF 已接入；[x] 恢复路由回归覆盖 chat.read、workspace/Chat owner 校验、跨用户 403 和跨 workspace 204；[x] HTTP middleware 限流回归已覆盖正常响应头、429 和 Retry-After；provider timeout、SSE/tool-loop mock 已覆盖；显式 `FASTAPI_TEST_REDIS_URL` 已支持真实 capture/resume smoke test；[x] 已增加 Playwright 浏览器断线后 reload 并再次恢复 SSE 的端到端验证 |
| Agent Query | `POST /api/v1/agents/query` | [x] ✅ 仅允许预定义只读工具（含知识库发现、单知识库/单文件上下文、文件状态查看和语义搜索），FastAPI 从认证上下文取得 workspace/user，并执行权限检查 |
| Agent Workflow | `POST /api/v1/agents/run` | [x] ✅ 使用服务端模型配置执行最多 5 轮只读 tool loop，不创建 Chat/Message；workspace、用户和知识库权限由 FastAPI 取得并校验；[x] 已提供显式 `FASTAPI_TEST_AGENT_*` 真实 provider smoke test（单次、单步、禁用知识库工具，默认跳过），部署环境中的实际执行待完成 |
| Chat 图片附件上传 | `POST /api/v1/files/upload` | [ ] 🚧 FastAPI 已支持 `document.write` 权限、JPEG/PNG MIME 与 magic bytes 和大小校验、local HMAC 签名 URL、S3 预签名 URL；[x] 路由回归测试确认 workspace 进入权限检查，存储 key 按 workspace/user 隔离；Next.js `/api/files/upload` 通过 `USE_FASTAPI_ATTACHMENT_UPLOAD` 可切换转发，旧 Vercel Blob 路径保留；真实对象存储和浏览器访问验证待完成 |
| Chat 消息评价 | `GET/PATCH /api/v1/votes` | [x] ✅ FastAPI 已迁移投票查询和 upsert，校验 `chat.read/chat.write`、workspace、chat owner 和 message 归属；Next.js `/api/vote` 在 `USE_FASTAPI_BACKEND=1` 时转发，旧 Drizzle 路径保留 |
| 文档建议读取 | `GET /api/v1/suggestions` | [x] ✅ FastAPI 已迁移建议查询和 camelCase 返回结构，校验 `document.read`、workspace 和文档 owner；Next.js `/api/suggestions` 与实际使用的 `artifacts/actions.ts` Server Action 在 `USE_FASTAPI_BACKEND=1` 时均转发，旧 Drizzle 路径保留 |
| 模型能力 | `GET /api/v1/models` | [x] ✅ FastAPI 已迁移公开模型能力查询，保持 `/api/models` 的返回结构；模型选择器和图片附件按钮在 `USE_FASTAPI_BACKEND=1` 时通过 Next.js BFF 读取 FastAPI，聊天请求只接受公开 capability model ID，旧静态实现保留 |

## 当前项目模块映射

| Next.js 位置或能力 | FastAPI 后续模块 |
|---|---|
| `app/(chat)/api/chat/route.ts` | `app/api/v1/chat` |
| `app/(chat)/api/chat/[id]/stream/route.ts` | `app/api/v1/chat/{id}/stream` |
| `app/(chat)/api/files/upload/route.ts` | `app/api/v1/files/upload`（feature-gated；Vercel Blob fallback） |
| `app/(chat)/api/history/route.ts` | `app/api/v1/chats` |
| `app/(chat)/api/messages/route.ts` | `app/api/v1/chats/{id}/messages` |
| `app/(chat)/api/vote/route.ts` | `app/api/v1/votes` |
| `app/(chat)/api/suggestions/route.ts`、`artifacts/actions.ts` | `app/api/v1/suggestions` |
| `app/(chat)/api/models/route.ts` | `app/api/v1/models` |
| `app/(chat)/api/knowledge-bases/[knowledgeBaseId]/files/route.ts` | `app/api/v1/knowledge-bases/{id}/files` |
| `app/(chat)/api/knowledge-bases/[knowledgeBaseId]/files/[fileId]/route.ts` | `app/api/v1/knowledge-bases/{id}/files/{fileId}` |
| `app/(chat)/settings/knowledge-bases/files/page.tsx`、`components/settings/knowledge-base-files.tsx` | FastAPI 文件入库管理 Web UI；上传、刷新、状态和删除均通过 Next.js BFF 转发 |
| `app/(chat)/settings/knowledge-bases/page.tsx`、`components/settings/knowledge-base-grants.tsx` | FastAPI 知识库生命周期和授权管理 Web UI；创建、重命名、删除和 grant 操作均通过 Next.js BFF 转发 |
| `app/(chat)/api/knowledge-bases/route.ts` | `app/api/v1/knowledge-bases` |
| `app/(chat)/api/knowledge-bases/[knowledgeBaseId]/route.ts` | `app/api/v1/knowledge-bases/{id}` |
| `app/(chat)/api/admin/members/route.ts` | `app/api/v1/admin/members` |
| `app/(chat)/api/admin/knowledge-base-grants/route.ts` | `app/api/v1/admin/knowledge-base-grants` |
| `lib/db/trade-queries.ts` | `app/services/products` |
| `lib/db/content-queries.ts` | `app/services/content` |
| `lib/ratelimit.ts` | FastAPI Redis-backed rate-limit middleware；Redis 不可用时回退 process-local，保留跨实例安全降级 |
| NextAuth | Logto + FastAPI Token 验证 |
| Vercel AI SDK | FastAPI Agent / SSE 接口 |

## 数据库迁移原则

当前项目已经使用 Drizzle 和 PostgreSQL，迁移期间遵循以下规则：

1. 现有表先继续由 Drizzle 维护。
2. FastAPI 初期只读现有表。
3. 不让 Drizzle 和 Alembic 同时管理同一张表。
4. 新增的权限和知识库表，等 FastAPI 接管后再使用 Alembic。
5. 暂时避免 Next.js 和 FastAPI 同时写同一业务数据。
6. 数据库 schema 变更必须先在本地测试，再进入共享环境。

## 认证迁移路线

### 过渡阶段

```text
NextAuth 验证 Session
        ↓
Next.js 服务端请求 FastAPI
        ↓
FastAPI 验证内部 Token
```

浏览器不能直接提交 `userId`、`role` 或 `organizationId` 作为可信身份信息。FastAPI 必须从经过签名验证的 Token 中取得当前用户信息。

### 最终阶段

```text
Logto 登录（后续 Web/移动端统一认证阶段）
    ↓
Web / 移动端获得 Access Token
    ↓
FastAPI 验证 Token
    ↓
FastAPI 查询企业和知识库权限
```

## 知识库权限模型

建议建立以下核心关系：

```text
用户 → 企业组织 → 组织角色
用户/角色 → 知识库 → 文件 → 文档切片 → 向量数据
```

建议的表：

```text
organizations
memberships
roles
knowledge_bases
knowledge_base_grants
documents
document_chunks
embedding_jobs
```

向量数据必须携带至少以下过滤字段：

```text
organization_id
knowledge_base_id
document_id
visibility
```

检索流程必须是：

```text
验证 Token
  ↓
确定 organization_id
  ↓
查询允许访问的 knowledge_base_id
  ↓
带权限条件执行向量检索
  ↓
将授权内容交给 AI Agent
```

## 文件和知识库入库流程

文件处理不要长时间阻塞上传请求，建议使用后台任务：

```text
上传文件
  ↓
创建处理任务
  ↓
后台 Worker 解析文件
  ↓
文本切片
  ↓
生成 Embedding
  ↓
写入向量库
  ↓
更新处理状态
```

## 测试要求

每迁移一个接口，都需要至少覆盖：

```text
200：正常访问
400：参数错误
401：未登录
403：无权限
404：资源不存在
跨企业访问测试
未授权知识库访问测试
```

知识库系统还需要重点测试：

- external 用户不能访问内部知识库。
- contractor 不能访问未授权知识库，且只能通过显式 user/role grant 获取知识库。
- 员工不能跨企业查询。
- 向量检索不能返回其他企业的文档。
- AI Agent 工具调用不能绕过权限。

## 当前第一阶段任务

下一步按以下顺序实现：

1. ✅ FastAPI 接入现有 PostgreSQL。
2. ✅ 建立 SQLAlchemy 数据访问层。
3. ✅ 迁移一个只读查询接口（`GET /api/v1/products` 基础查询）。
4. ✅ Web 前端通过 Next.js BFF 调用 FastAPI（健康检查、CORS、签名身份桥接和聊天 SSE 已验证）。
5. ✅ 对比新旧只读接口结果，并补齐商品高级过滤。
6. 🚧 增加 Pytest 和数据库测试（基础路由测试已完成；[x] 已增加显式 `FASTAPI_TEST_*` 地址的 PostgreSQL migration 与 Redis smoke test；[x] 已增加 migration 后只读 knowledge integrity 检查；实际本地服务运行验证待完成）。

本地 Mock OIDC 已完成第一步迁移：Next.js `/dev/oidc` 页面保持不变，consent 请求在
`USE_FASTAPI_BACKEND=1` 时由 Next.js BFF 转发到 FastAPI；FastAPI 生成的 code 与旧
Next.js verifier 保持兼容。由于该 endpoint 只用于本地开发，staging/production 会返回 404。

管理员成员管理已完成第一步迁移：Next.js `/api/admin/members` 在开关开启时只负责
NextAuth session 和 actor 校验，再通过签名的 NextAuth bridge 调用 FastAPI；FastAPI
负责 workspace 权限、成员角色、权限覆盖、owner 保护和审计日志。

聊天主链路已先完成第一步，当前请求路径为：

```text
Web useChat → FastAPI `/api/v1/chat` → DeepSeek
```

商品和内容两个只读接口已经验证 FastAPI 路由、Pydantic Schema、SQLAlchemy、PostgreSQL 和 Pytest 的完整链路。

聊天持久化、只读 Agent tools、知识库发现、知识库文件入库、独立 `KnowledgeBase` 和知识库删除代码迁移第一步已经完成；数据库迁移已增加统一只读 status、只读 knowledge integrity 检查和远程目标安全门，本地 PostgreSQL/pgvector/Redis Compose 也已提供，并增加了显式测试地址的集成 smoke test、Redis-backed rate limit 和 Playwright 浏览器断线恢复测试。当前连接目标是远程 Supabase，未执行 schema 写入；当前开发环境尚未安装 Docker，因此真实本地 migration、Redis、限流跨实例和真实 provider 验证仍待有 Docker 的开发环境执行。下一步应启动本地 Compose 后运行
`make migrate-knowledge`、`make migration-status` 和 `make knowledge-integrity`，开启对应开关做真实数据验证，再继续迁移更多知识库工具、Redis 可恢复流和 Web 端剩余接口。移动端 Token API 暂不安排在当前迭代。
