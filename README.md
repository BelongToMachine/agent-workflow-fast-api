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
- 成员列表：`GET http://127.0.0.1:8000/api/v1/admin/members?workspace_id={workspace_id}`
- 成员权限更新：`PATCH http://127.0.0.1:8000/api/v1/admin/members?workspace_id={workspace_id}`
- 本地 Mock OIDC consent：`POST http://127.0.0.1:8000/api/v1/dev/oidc/consent`
- 聊天接口：`POST http://127.0.0.1:8000/api/v1/chat`
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

聊天请求会由浏览器直接发送到 FastAPI `8000` 端口，FastAPI 负责模型调用和 SSE 返回。本地默认使用开发身份，生产环境需要配置 OIDC/Logto Token 后再开放跨域访问。

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

## 知识库授权迁移

`migrations/0001_knowledge_base_grants.sql` 新增了过渡版
`KnowledgeBaseGrant` 表。当前每个 `KnowledgeSource` 暂时视为一个知识库，授权主体
可以是用户或角色。没有 grant 的旧知识库继续使用 workspace 权限；存在 grant 的知识库
只允许匹配的用户/角色访问。

应用迁移 SQL 后，再设置：

```env
KNOWLEDGE_GRANTS_ENABLED=1
```

在开关关闭时，产品、内容和知识库列表保持原有 workspace 级行为，避免数据库迁移尚未
执行时导致现有接口不可用。

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
│   │   ├── admin_members.py
│   │   ├── chat.py
│   │   ├── content.py
│   │   ├── dev_oidc.py
│   │   ├── health.py
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
4. 🚧 基于现有 Workspace/WorkspaceMember 完成企业、成员、角色和知识库权限模型，再增加单知识库 grant。
5. 增加文件上传、解析、向量检索和 AI Agent 接口。

商品和内容查询当前已经迁移到 FastAPI，并完成了与 Next.js 查询结果的真实数据对比。

当前聊天接口还未迁移消息持久化和工具调用；统一用户身份验证已经接入，但 workspace/role/knowledge-base 授权会在后续权限模型阶段补齐。当前多轮上下文由 Web 前端暂时随请求传给 FastAPI，因此刷新页面后仍依赖现有 Next.js 消息接口。
