# Logto 接入 MVP 计划

## 1. 文档目的

本文档用于规划 Logto 接入当前独立前后端体系的最小可用版本（MVP）。目标架构为：

- 前端：`asianodeagent-front`（React + Vite）
- 后端：`asianode-fastapi`（FastAPI）
- 身份认证：Logto
- 业务授权：FastAPI + PostgreSQL 中现有的 User、Workspace、WorkspaceMember 和权限表

本方案不引入新的 Next.js BFF，也不把外层 Next.js 应用作为长期运行时依赖。

## 2. MVP 目标

用户可以使用以下方式登录：

- Google
- 微信网页登录

登录后：

1. Logto 完成用户认证；
2. React 前端获取 Logto access token；
3. 前端通过 `Authorization: Bearer <token>` 调用 FastAPI；
4. FastAPI 校验 JWT；
5. FastAPI 将 Logto 用户映射到本地 User；
6. FastAPI 继续使用本地 workspace 和 permission 数据完成业务授权。

整体链路：

```text
Google / 微信
    ↓
Logto 统一认证
    ↓
React 获取 access token
    ↓
Authorization: Bearer <Logto JWT>
    ↓
FastAPI 校验 JWT
    ↓
本地 User / Workspace / Member / Permission 授权
```

## 3. MVP 边界

### 本次实现

- Logto SPA 应用配置；
- Google Social Connector；
- 微信网页登录 Social Connector；
- React 登录、回调、退出；
- FastAPI Logto JWT 校验；
- Logto 用户与本地 User 映射；
- 首次登录用户初始化策略；
- 现有 workspace 和权限接口继续工作；
- access token 过期后的刷新；
- 未登录、无 membership、无权限和跨 workspace 请求的错误处理。

### 暂不实现

- Logto Organizations；
- Logto RBAC 取代本地权限表；
- Google Drive、Calendar、Gmail 等第三方 API；
- 微信业务 API；
- 自己实现密码存储和密码登录；
- 自己维护 refresh token；
- 外层 Next.js BFF。

## 4. 推荐的职责划分

| 部分 | 负责内容 |
| --- | --- |
| Logto | 登录页面、Google/微信身份认证、用户身份、OIDC token 签发 |
| React 前端 | 发起登录、接收回调、获取 access token、发送 Bearer token |
| FastAPI | 验证 JWT、解析用户身份、映射本地用户、校验 workspace 和权限 |
| PostgreSQL | 保存本地用户、workspace、成员关系和权限覆盖配置 |
| Google / 微信 | 提供外部身份认证 |

核心原则：前端传来的 `userId`、`role`、`permissions`、`workspace owner` 都不能作为可信身份信息。

## 5. 实施计划

### Phase 0：确认身份和权限模型

这是开发前必须完成的设计确认。

#### 5.1 采用 Logto 作为认证源

Logto token 中的 `sub` 代表 Logto 用户身份。后端不能假设这个值一定是本地数据库 UUID。

#### 5.2 增加本地身份映射

推荐给本地 `User` 表增加类似字段：

```text
authProvider   = "logto"
authSubject    = Logto token 的 sub
```

并建立唯一约束：

```text
(authProvider, authSubject) UNIQUE
```

本地 User 继续使用自己的 UUID 作为主键。这样可以避免把第三方身份 ID 直接当成本地 UUID。

#### 5.3 确定首次登录策略

MVP 建议采用以下任一种方式：

- 预先把第一个 Logto 用户加入默认 workspace，并设为 owner；或
- 首次登录自动创建本地 User，但没有 workspace membership，交由管理员手动授权。

不建议根据前端提交的 email 自动授予 owner 或 admin 权限。

#### 5.4 保留本地授权

MVP 不把现有权限迁移到 Logto。权限继续由以下数据决定：

- `WorkspaceMember.role`；
- `WorkspaceMember.status`；
- `WorkspaceMemberPermission`；
- FastAPI 中的 workspace access 检查。

这样可以先完成可靠登录，再逐步评估是否需要 Logto Organizations 或 RBAC。

### Phase 1：配置 Logto

#### 1. 创建 SPA 应用

在 Logto Console 创建 SPA 应用，配置：

```text
开发回调地址：    http://localhost:5173/callback
开发登出地址：    http://localhost:5173/
生产回调地址：    https://<frontend-domain>/callback
生产登出地址：    https://<frontend-domain>/
```

同时配置允许的 Web origins。

#### 2. 创建 API Resource

例如：

```text
https://api.asianode.example.com
```

这个值必须与 FastAPI 的 `AUTH_AUDIENCE` 一致。

#### 3. 配置 Google Connector

在 Google Cloud 创建 OAuth 应用，然后将 client ID 和 client secret 配置到 Logto Google Connector。

client secret 只放在 Logto Connector 配置中，不放入 Vite 环境变量或浏览器代码。

#### 4. 配置微信网页登录 Connector

在微信开放平台创建网页应用，配置授权回调域名，并将 client ID、client secret 和 scope 配置到 Logto。

当前项目是 Web 应用，应使用微信网页登录 Connector，不使用微信原生 App Connector。

微信网页登录通常还需要完成平台审核。

#### 5. 启用登录入口

在 Logto 的 Sign-in & account → Sign-up and sign-in 中启用：

- Continue with Google；
- Continue with WeChat。

参考：

- [Logto Google connector](https://docs.logto.io/integrations/google)
- [Logto WeChat Web connector](https://docs.logto.io/integrations/wechat-web)
- [Logto React quick start](https://docs.logto.io/quick-starts/react)

### Phase 2：前端改造

目录：`asianodeagent-front`

#### 2.1 安装 SDK

```bash
bun add @logto/react
```

#### 2.2 增加环境变量

```env
VITE_LOGTO_ENDPOINT=https://your-tenant.logto.app
VITE_LOGTO_APP_ID=your-spa-app-id
VITE_LOGTO_API_RESOURCE=https://api.asianode.example.com
```

这些值可以公开给浏览器。不要增加 `VITE_LOGTO_CLIENT_SECRET`。

#### 2.3 接入 LogtoProvider

在应用入口增加 Logto Provider，并配置：

- endpoint；
- appId；
- resources；
- `openid`、`profile`、`email` 等必要 scope。

建议保留当前 `useSession()` 的外部接口，在 [`src/lib/auth.tsx`](asianodeagent-front/src/lib/auth.tsx) 内部改为适配 Logto。这样可以减少现有页面改动。

#### 2.4 增加 callback 路由

增加 `/callback` 路由，负责处理 Logto 授权回调，然后跳转到首页或登录前的目标页面。

callback 页面不应要求用户已经认证，否则会形成重定向循环。

#### 2.5 替换当前登录页

当前 [`src/App.jsx`](asianodeagent-front/src/App.jsx) 中的 `/login` 和 `/register` 只是表单占位，提交后直接跳转，没有真正发起登录。

改为：

- `Sign in`：调用 Logto `signIn()`；
- `Sign in with Google`：调用 Logto 登录并指定 Google connector；
- `Sign in with WeChat`：调用 Logto 登录并指定 WeChat connector；
- `Sign out`：调用 Logto `signOut()`。

也可以先只跳转 Logto Hosted Sign-in Page，由 Logto 页面展示 Google 和微信按钮。

#### 2.6 改造请求层

修改 [`src/lib/backend/direct-client.ts`](asianodeagent-front/src/lib/backend/direct-client.ts)：

```text
apiFetch()
  → Logto getAccessToken(API_RESOURCE)
  → Authorization: Bearer <access token>
  → FastAPI
```

注意：`apiFetch` 是普通函数，不能直接调用 React Hook。应提供一个独立的 token provider 或 Logto client 单例，供请求层取得 token。

需要移除或限制以下逻辑：

- 生产环境读取 `asianode.fastapi.direct-token`；
- 生产环境使用 `dev.*` token；
- 前端自行解码 token 作为权限判断；
- 前端把 role、permissions 作为可信字段提交。

前端可以解码 ID token 展示用户名，但不能据此决定 API 权限。

#### 2.7 保留开发登录

`/dev/oidc` 和 `dev.*` token 仅在开发模式保留，用于权限测试和本地无 Logto 场景。

生产构建中应隐藏该入口，并确保 FastAPI 在非 development 环境返回 404。

### Phase 3：后端改造

目录：`asianode-fastapi`

#### 3.1 配置环境变量

```env
ENVIRONMENT=production
AUTH_REQUIRED=true

AUTH_ISSUER=https://your-tenant.logto.app/oidc
AUTH_AUDIENCE=https://api.asianode.example.com
AUTH_JWKS_URL=https://your-tenant.logto.app/oidc/jwks
AUTH_ALGORITHMS=RS256
```

当前 [`app/core/auth.py`](asianode-fastapi/app/core/auth.py) 已具备标准 OIDC JWT 校验基础，包括：

- JWKS 获取和缓存；
- `kid` 校验；
- issuer 校验；
- audience 校验；
- `exp` 校验；
- `sub` 校验；
- 签名校验。

#### 3.2 增加 Logto 用户解析

在 access token 验证成功后：

```text
Logto sub
  → 查询 User.authProvider + User.authSubject
  → 找到：使用本地 User UUID
  → 找不到：按首次登录策略创建或拒绝
```

建议把外部身份解析放在认证依赖层完成，使业务路由继续拿到稳定的本地 User UUID。

#### 3.3 调整 AuthenticatedUser

建议区分两个概念：

```text
external_subject：Logto sub
user_id：本地 User UUID
```

避免把 Logto `sub` 直接放进当前所有要求 UUID 的业务路径。

#### 3.4 处理用户资料

首次登录时可以同步：

- email；
- name；
- avatar/image；
- email verified 状态。

email 只作为资料或辅助查找字段，不作为唯一身份主键。

#### 3.5 保持 workspace 权限逻辑

继续复用 [`app/core/workspace_access.py`](asianode-fastapi/app/core/workspace_access.py)：

- 根据本地 User UUID 查询 active membership；
- 根据本地 role 计算权限；
- 应用 member permission override；
- 校验请求 workspace；
- 拒绝跨 workspace 数据访问。

前端的 `workspace_id` 只是请求上下文，不是授权依据。

#### 3.6 Scope 和 Logto RBAC

MVP 阶段不依赖 Logto `scope` 做业务授权，避免同时迁移两套权限模型。

后续如果要使用 Logto RBAC，需要额外处理：

- token 中的 `scope` claim；
- Logto role 与本地 role 的映射；
- workspace/organization 与本地 workspace 的映射；
- 权限变更后的 token 更新策略。

#### 3.7 安全配置

生产环境必须满足：

- `AUTH_REQUIRED=true`；
- `AUTH_ISSUER` 使用 HTTPS；
- `AUTH_AUDIENCE` 非空；
- CORS 只允许实际前端域名；
- 禁止启用 SQLAdmin；
- 禁止启用 `/dev/oidc/token`；
- 不在日志中输出完整 access token。

### Phase 4：数据库和初始化

#### 4.1 Migration

增加本地用户外部身份字段和唯一索引，例如：

```sql
ALTER TABLE "User"
ADD COLUMN "authProvider" TEXT,
ADD COLUMN "authSubject" TEXT;
```

具体字段命名应与当前 Prisma/数据库迁移规范保持一致。

#### 4.2 用户初始化

建议先采用显式初始化：

1. 第一个 Logto 用户登录；
2. 后端创建或找到本地 User；
3. 运维脚本将其加入默认 workspace 并设置 owner；
4. 后续用户由管理员在成员设置中授权。

这样可以避免任何人只要登录就自动获得 workspace 管理权限。

## 6. 配置清单

### Logto

- [ ] 创建 SPA 应用；
- [ ] 配置开发和生产 callback URL；
- [ ] 配置 logout redirect URL；
- [ ] 创建 API Resource；
- [ ] 配置 Google Connector；
- [ ] 配置 WeChat Web Connector；
- [ ] 启用 Google 和微信登录按钮；
- [ ] 确认允许的 origin 和 redirect URL。

### 前端

- [ ] 安装 `@logto/react`；
- [ ] 增加 `VITE_LOGTO_ENDPOINT`；
- [ ] 增加 `VITE_LOGTO_APP_ID`；
- [ ] 增加 `VITE_LOGTO_API_RESOURCE`；
- [ ] 接入 `LogtoProvider`；
- [ ] 实现 callback；
- [ ] 替换占位登录页；
- [ ] 改造 `apiFetch`；
- [ ] 保留开发 token 但限制在 development；
- [ ] 不在前端信任 userId、role、permissions。

### 后端

- [ ] 配置 `AUTH_ISSUER`；
- [ ] 配置 `AUTH_AUDIENCE`；
- [ ] 配置 `AUTH_JWKS_URL`；
- [ ] 确认 PyJWT 的 issuer/audience 校验；
- [ ] 增加 `authSubject` 用户映射；
- [ ] 增加首次登录初始化策略；
- [ ] 保持本地 workspace/member 权限；
- [ ] 增加 401/403 错误处理；
- [ ] 禁用生产 dev token endpoint。

## 7. 验收标准

### 登录

- [ ] 点击 Google 可以完成登录；
- [ ] 点击微信可以完成网页登录；
- [ ] 登录回调可以回到前端；
- [ ] 刷新浏览器后登录状态仍然有效；
- [ ] 退出后再次访问受保护页面会要求登录。

### API

- [ ] FastAPI 请求包含 `Authorization: Bearer`；
- [ ] 有效 Logto token 可以访问 `/api/v1/me`；
- [ ] 错误 issuer、audience、签名或过期 token 返回 401；
- [ ] 未映射本地用户不会被当成有效业务用户；
- [ ] 无 workspace membership 返回 403；
- [ ] 无权限操作返回 403；
- [ ] 修改前端 workspace 参数不能跨 workspace 访问数据。

### 用户映射

- [ ] 同一个 Logto 用户重复登录不会创建重复 User；
- [ ] Google 和微信账号可以按预期关联到同一个 Logto 用户；
- [ ] 本地 User UUID 在业务表中保持稳定；
- [ ] email 变化不会导致创建新用户。

## 8. 风险和注意事项

1. 不要把 Logto client secret 放进 Vite 环境变量。
2. 不要使用 email 作为唯一身份标识。
3. 不要让前端选择 role 后直接获得对应权限；开发环境的 role 选择只能保留给 dev token 流程。
4. 不要在 MVP 同时迁移 Logto RBAC 和本地 workspace 权限。
5. 微信网页登录和 Google OAuth 都可能有域名、审核和回调地址限制。
6. 生产环境必须使用 HTTPS，尤其是 OAuth callback 和 access token 传输。
7. 日志、错误上报和前端调试工具不能输出完整 token。

## 9. 推荐实施顺序

```text
1. 确认 User 外部身份映射方案
2. 在 Logto 配置 SPA、API Resource、Google、微信
3. 后端先完成 JWT 校验和本地 User 映射
4. 前端接入 Logto 登录和 callback
5. 改造 apiFetch 注入 access token
6. 联调 /me、聊天和 workspace 权限
7. 补充失效 token、无权限和跨 workspace 测试
8. 生产配置切换并关闭 dev token
```

## 10. MVP 完成定义

当用户可以使用 Google 或微信登录，并且登录后的请求能够：

- 被 FastAPI 正确认证；
- 映射到稳定的本地 User；
- 按本地 workspace membership 判断权限；
- 正常使用聊天和现有业务接口；
- 在 token 过期后自动恢复；

即可认为 Logto 接入 MVP 完成。
