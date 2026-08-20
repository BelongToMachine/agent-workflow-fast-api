# Asianode FastAPI API Contracts

这份文档以当前 FastAPI 路由和 `/openapi.json` 为准，记录 Web 迁移阶段的稳定接口边界。
具体字段定义由各路由中的 Pydantic model 生成；接口变更时需要同步更新本文件和 OpenAPI
契约测试。

## 基本约定

- Base URL：`http://127.0.0.1:8000`
- API 前缀：`/api/v1`
- Web 请求由 Next.js BFF 转发；BFF 使用签名的 NextAuth bridge context。独立客户端使用
  `Authorization: Bearer <access-token>`。
- 本地开发可设置 `NEXT_PUBLIC_API_MODE=fastapi-direct`，浏览器会通过 NextAuth 的
  `/api/auth/fastapi-token` 获取 5 分钟有效的开发 direct token，并直接请求 `/api/v1/*`；该
  模式只允许 development 环境，生产环境仍使用 BFF 或正式 OIDC Bearer Token。
- 除 `/`、`/api/v1/healthz` 和 development-only 的 `/api/v1/dev/oidc/consent` 外，接口都需要
  认证上下文。
- `workspace_id` 使用 query parameter 时必须是 UUID。content search 使用 body 中的
  `workspaceId`；chat 可以从 token/workspace query 解析 workspace。
- 服务端从认证上下文取得 user、role、permission 和 workspace，不接受调用方在 body 中提交
  这些字段作为可信身份。
- `ENVIRONMENT=staging` 或 `production` 时，应用启动会拒绝缺失/非 HTTPS 的 OIDC issuer、缺失
  audience、弱 bridge/auth secret、通配符 CORS 或关闭全局限流的配置。
- JSON 字段使用 camelCase；query parameter 保持现有 BFF 兼容命名，例如 `workspace_id`、
  `starting_after` 和 `sourceFileNames`。

## 错误约定

| HTTP 状态 | 典型响应 | 适用场景 |
|---:|---|---|
| 400 | `{"code":"bad_request:api","message":"..."}` 或 `{"detail":"..."}` | 参数组合、业务输入或时间戳错误 |
| 401 | `detail` + `WWW-Authenticate: Bearer` | 未认证或 development 身份不能执行写操作 |
| 403 | `detail` 或 `message` | workspace、成员、知识库或 chat 无权限 |
| 404 | `detail` 或 `message` | 资源不存在，或不属于当前 workspace |
| 409 | `code` + `message` | feature migration 尚未启用、文件重复或 grant 功能关闭 |
| 413/415 | `detail` | 文件超过大小限制或扩展名不支持 |
| 422 | FastAPI validation envelope | UUID、query、body 或 multipart 参数未通过 Pydantic 校验 |
| 502 | `detail` 或 `code` + `cause` | 上游模型/Embedding provider 失败 |
| 503 | `code` + `cause` | 数据库、对象存储或 provider 配置不可用 |

validation error 的标准结构由 FastAPI 生成：

```json
{
  "detail": [
    {"loc": ["body", "displayName"], "msg": "...", "type": "..."}
  ]
}
```

## Endpoint matrix

| Method | Path | 权限/feature flag | 输入 | 成功响应 |
|---|---|---|---|---|
| GET | `/` | public | — | `{service,status,docs}` |
| GET | `/api/v1/healthz` | public | — | `{status,service,environment}` |
| GET | `/api/v1/models` | public | — | `{modelId:{tools,vision,reasoning}}` |
| GET | `/api/v1/me` | authenticated | token/bridge context | `CurrentUserResponse`：用户、active memberships、role、effective permissions、overrides |
| GET | `/api/v1/products` | `knowledge.read` | query：`workspace_id`、`query`、`category`、`maxPriceUsd`、`maxLeadDays`、`maxMoqUnits`、`operationStatus`、`targetChannel`、`proposer`、`logistics`、`qualification`、`hasDocument`、`missingField`、`limit`、`sourceFileNames` | `ProductSearchResponse` |
| POST | `/api/v1/content/search` | `knowledge.read` | body：`workspaceId`、`query`、`account`、`language`、`product`、`recordType`、`status`、`submitter`、`sourceFileNames`、`limit` | `ContentSearchResponse` |
| GET | `/api/v1/knowledge-sources` | `knowledge.read` | query：`workspace_id` | `KnowledgeSourceListResponse`，包含授权过滤后的 sources |
| GET | `/api/v1/knowledge-bases` | `knowledge.read` | query：`workspace_id` | `{knowledgeBases:[KnowledgeBaseSummary]}` |
| POST | `/api/v1/knowledge-bases` | `knowledge.manage` | query：`workspace_id`；body：`{displayName,sourceType?}` | `201 KnowledgeBaseSummary` |
| PATCH | `/api/v1/knowledge-bases/{knowledge_base_id}` | `knowledge.manage` | query：`workspace_id`；body：`{displayName,sourceType?}` | `KnowledgeBaseSummary` |
| DELETE | `/api/v1/knowledge-bases/{knowledge_base_id}` | knowledge-base `manage` | query：`workspace_id` | `{deleted:true,storageCleanup}`；对象清理失败时返回 `202` 和 `failedFileCount` |
| GET | `/api/v1/knowledge-bases/{knowledge_base_id}/files` | knowledge-base `read` + `KNOWLEDGE_INGESTION_ENABLED` | query：`workspace_id` | `{files:[KnowledgeFileSummary]}` |
| POST | `/api/v1/knowledge-bases/{knowledge_base_id}/files` | knowledge-base `manage` + `KNOWLEDGE_INGESTION_ENABLED` | multipart `file`；query：`workspace_id` | `202 {file:KnowledgeFileSummary}`，PDF/XLSX 会先校验 magic bytes，后台处理为 `ready`/`failed` |
| DELETE | `/api/v1/knowledge-bases/{knowledge_base_id}/files/{file_id}` | knowledge-base `manage` + `KNOWLEDGE_INGESTION_ENABLED` | query：`workspace_id` | `{deleted:true}` |
| POST | `/api/v1/knowledge-bases/{knowledge_base_id}/search` | knowledge-base `read` + `KNOWLEDGE_EMBEDDINGS_ENABLED` | query：`workspace_id`；body：`{query,limit?}` | `{results:[{chunkId,content,fileId,fileName,score}]}`；Embedding provider 请求受 `EMBEDDING_PROVIDER_TIMEOUT_SECONDS`（1–300 秒）限制 |
| GET | `/api/v1/admin/members` | `members.read` | query：`workspace_id` | `MembersResponse` |
| PATCH | `/api/v1/admin/members` | `members.manage` | query：`workspace_id`；body：`{memberId,role,permissions}` | `{member:WorkspaceMemberView|null}` |
| GET | `/api/v1/admin/knowledge-base-grants` | `members.manage` + `KNOWLEDGE_GRANTS_ENABLED` | query：`workspace_id`、`knowledge_base_id?` | `{grants:[KnowledgeBaseGrantView]}` |
| PUT | `/api/v1/admin/knowledge-base-grants` | `members.manage` + `KNOWLEDGE_GRANTS_ENABLED` | query：`workspace_id`；body：`{knowledgeBaseId,subjectType,subjectId,accessLevel}` | `{grant:KnowledgeBaseGrantView|null}` |
| DELETE | `/api/v1/admin/knowledge-base-grants/{grant_id}` | `members.manage` + `KNOWLEDGE_GRANTS_ENABLED` | query：`workspace_id` | `{deleted:true}` |
| POST | `/api/v1/agents/query` | `knowledge.read` | query：`workspace_id`；body：`{tool,arguments}` | `{tool,result}` |
| POST | `/api/v1/agents/run` | `knowledge.read` | query：`workspace_id`；body：`{prompt,maxSteps?}` | `{answer,steps,toolCalls}`；不写入 Chat/Message |
| POST | `/api/v1/files/upload` | `document.write` + `CHAT_ATTACHMENTS_ENABLED` | multipart `file`；query：`workspace_id` | `{url,pathname,contentType}`；只接受匹配 PNG/JPEG magic bytes 的内容 |
| GET | `/api/v1/files/attachments/{token}` | signed local URL；不需要 Bearer | path：`token` | JPEG/PNG bytes |
| POST | `/api/v1/chat` | `chat.write` | query：`workspace_id?`；body：`ChatRequest` | AI SDK-compatible `text/event-stream` |
| GET | `/api/v1/chat/{chat_id}/stream` | `chat.read` + owner/workspace check | query：`workspace_id` | resumable AI SDK `text/event-stream`，无活动流为 `204` |
| GET | `/api/v1/chats` | `chat.read` | query：`workspace_id`、`limit`、`starting_after?`、`ending_before?` | `ChatHistoryResponse` |
| DELETE | `/api/v1/chats` | `chat.delete` | query：`workspace_id` | `{deletedCount}` |
| DELETE | `/api/v1/chats/{chat_id}` | `chat.delete` + owner/workspace check | query：`workspace_id` | `{id}` |
| GET | `/api/v1/chats/{chat_id}/messages` | `chat.read` + owner/workspace check | query：`workspace_id` | `ChatMessagesResponse` |
| GET | `/api/v1/votes` | `chat.read` + chat owner/workspace check | query：`chatId`、`workspace_id` | `VoteRecord[]` |
| PATCH | `/api/v1/votes` | `chat.write` + chat/message owner/workspace check | query：`workspace_id`；body：`{chatId,messageId,type}` | `Message voted` |
| GET | `/api/v1/suggestions` | `document.read` + document owner/workspace check | query：`documentId`、`workspace_id` | `SuggestionRecord[]` |
| GET | `/api/v1/documents` | `document.read` | query：`id`、`workspace_id` | `DocumentRecord[]` |
| POST | `/api/v1/documents` | `document.write` | query：`id`、`workspace_id`；body：`{content,isManualEdit?,kind,title}` | `DocumentRecord[]` |
| DELETE | `/api/v1/documents` | `document.write` | query：`id`、`timestamp`、`workspace_id` | `DocumentRecord[]` |
| POST | `/api/v1/dev/oidc/consent` | development + signed bridge context | headers：`x-asianode-dev-oidc-context`、`x-asianode-dev-oidc-signature`；body：`{clientId,permissions,redirectUri,scopes,state?}` | `{expiresIn,redirectUrl,scope}` |

## Request model highlights

### Knowledge-base grant

```json
{
  "knowledgeBaseId": "uuid",
  "subjectType": "user",
  "subjectId": "user-or-role-id",
  "accessLevel": "read"
}
```

`subjectType` 只能是 `user`/`role`，`accessLevel` 只能是 `read`/`manage`。external/contractor/guest
用户只能通过明确的 user/role grant 访问受限知识库；role grant 会匹配 workspace role 和认证
Token roles。

### Agent query

```json
{
  "tool": "searchProductsTool",
  "arguments": {}
}
```

`tool` 只能是 `listKnowledgeBasesTool`、`listKnowledgeFilesTool`、
`getKnowledgeBaseTool`、`getKnowledgeFileTool`、`searchProductsTool`、`searchContentTool` 或
`searchKnowledgeBaseTool`。用户、角色、权限和 workspace 不属于 request body，由 FastAPI 从
认证上下文解析。`listKnowledgeBasesTool` 只返回当前用户在当前 workspace 有权读取的知识库；
`listKnowledgeFilesTool` 只返回指定授权知识库内的文件和处理状态；`getKnowledgeBaseTool` 和
`getKnowledgeFileTool` 只返回列表中已授权的单个资源。模型应先发现可访问的 `knowledgeBaseId`，
再调用文件列表、单资源上下文或 `searchKnowledgeBaseTool`。

### Independent Agent workflow

```json
{
  "prompt": "Which knowledge bases can I read?",
  "maxSteps": 5
}
```

`POST /api/v1/agents/run` 是不创建 Chat/Message 的独立只读 Agent workflow。FastAPI 使用服务端
配置的模型，最多执行 `maxSteps` 轮“模型请求 → 预定义工具 → 模型请求”，并在每轮继续复用
workspace、用户和知识库授权检查。调用方不能提交 user、role、permission 或 workspace 身份；
达到工具轮数上限、模型不可用或模型返回无效工具调用时，接口返回结构化 `agent:workflow_error`。

### Chat request

```json
{
  "id": "chat-id",
  "message": {"role": "user", "parts": [{"type": "text", "text": "..."}]},
  "selectedChatModel": "deepseek-chat",
  "selectedVisibilityType": "private"
}
```

`message` 和 `messages` 至少要提供一个可提取文本或受支持图片的消息；响应不是 JSON，而是带有
`x-vercel-ai-ui-message-stream: v1` 的 SSE。

`selectedChatModel` 必须是 `/api/v1/models` 返回的模型 ID。未知或未配置的模型 ID 会在 FastAPI
边界回退到 `deepseek-chat`，不会直接转发客户端提交的任意 provider/model 字符串。
模型 provider 请求受 `CHAT_PROVIDER_TIMEOUT_SECONDS` 限制，超时会以 AI SDK SSE error chunk
结束，不会无限占用 FastAPI worker。

Web 的 JPEG/PNG `file` part 会被 FastAPI 转换为模型消息中的 OpenAI-compatible
`image_url` content。图片 URL 只能使用 `http://`、`https://` 或 `data:image/...`；不支持的
文件类型和本地文件路径不会传给模型。

## Compatibility and migration rules

- Next.js BFF 保留原有 `/api/...` 路径，只负责 session 校验、签名 bridge 和响应转发。
- FastAPI 的 `/api/v1` 是业务权限和数据访问的唯一新管道；旧 Next.js handler 暂时保留作回滚
  和未切换开关时的兼容实现。
- `KNOWLEDGE_BASE_ENTITY_ENABLED` 关闭时，FastAPI 使用 `KnowledgeSource`；开启前必须先应用
  `migrations/0004_knowledge_bases.sql`。
- `KNOWLEDGE_GRANTS_ENABLED`、`KNOWLEDGE_INGESTION_ENABLED` 和
  `KNOWLEDGE_EMBEDDINGS_ENABLED` 都必须在对应数据库/provider 验证后再开启。
- `CHAT_ATTACHMENTS_ENABLED` 和 `USE_FASTAPI_ATTACHMENT_UPLOAD` 默认关闭。FastAPI local
  storage 使用带 HMAC 和过期时间的签名 URL；S3-compatible storage 使用短期预签名 URL。
  生产环境必须配置可访问 FastAPI 的 `ATTACHMENT_PUBLIC_BASE_URL`，或使用 S3 provider。
- 生产环境切换前，必须完成跨 workspace、未授权知识库、external/contractor 角色和 Agent
  tool 绕过权限的集成测试。
