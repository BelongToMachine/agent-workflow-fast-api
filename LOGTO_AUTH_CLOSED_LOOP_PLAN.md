# Logto + Google + 微信认证授权闭环实施计划

> 适用架构：`asianodeagent-front`（React + Vite）+ `asianode-fastapi`（FastAPI）+ PostgreSQL + Logto
> 文档状态：实施计划
> 最后更新：2026-08-20

## 1. 目标

建立一条可用于生产环境的完整认证授权链路：

```text
Google / 微信网页用户
  → Logto Hosted Sign-in
  → React/Vite 获取 Logto Access Token
  → Authorization: Bearer <access_token>
  → FastAPI 验证 JWT
  → Logto sub 映射为本地 User UUID
  → 查询本地 WorkspaceMember / role / permission override
  → 按 workspace 和资源归属执行授权
  → 前端根据 /me 返回的权限状态展示功能
```

闭环完成后必须满足：

- Google 和微信网页登录都能成功完成回调；
- 浏览器只持有 SPA 可以持有的 Logto Token，不持有任何第三方 client secret；
- FastAPI 能验证 Logto Access Token 的签名、issuer、audience、有效期和 subject；
- 同一个 Logto 用户始终映射到同一个本地 `User.id`；
- 未加入 workspace 的用户能够登录，但不能访问业务数据；
- workspace、role、permissions 和资源归属均由 FastAPI/PostgreSQL 判定；
- Token 过期后由 Logto SDK 刷新，刷新失败时回到未登录状态；
- 生产环境不依赖 NextAuth、开发 direct token 或前端提交的身份字段。

## 2. 范围与非目标

### 2.1 本次范围

- React SPA 的 Logto 登录、回调、退出和 Token 生命周期；
- Google Social Connector；
- WeChat Web Social Connector；
- Logto API Resource 和 FastAPI JWT 验证；
- Logto 外部身份与本地 `User` 的稳定映射；
- 首次登录用户初始化；
- workspace membership、role 和 permission 闭环；
- 前端 `/me` 初始化、active workspace 和权限态；
- 401、403、无 membership、账号禁用等状态处理；
- 自动化测试、真实环境联调、灰度和回滚。

### 2.2 暂不纳入 MVP

- Logto Organizations 替换本地 `Workspace`；
- Logto RBAC 替换本地 `WorkspaceMemberPermission`；
- 微信 Native App 登录；
- 获取 Google Drive、Calendar 等额外 Google API 权限；
- 在业务后端保存 Google 或微信 access token；
- 扩展旧 Next.js/NextAuth 认证链路；
- 根据 email 自动合并不同 Logto 用户；
- 根据 email 自动授予 owner/admin 权限。

当前阶段坚持一个授权来源：Logto 负责“是谁”，FastAPI/PostgreSQL 负责“能做什么”。

## 3. 当前代码现状

### 3.1 已具备

#### React/Vite 前端

- 已安装 `@logto/react`；
- 已有 `LogtoProvider` 配置入口；
- 已有 `/callback` 路由和 `useHandleSignInCallback()`；
- 已有登录、退出和 ID Token claims 读取；
- 已有 `getAccessToken(API_RESOURCE)`；
- `apiFetch()` 已能注入 `Authorization: Bearer`；
- 非开发构建在未配置 Logto 时会阻止应用静默进入开发认证模式；
- 开发 direct token 与 Logto 模式已经分离。

关键文件：

- `../asianodeagent-front/src/lib/auth.tsx`
- `../asianodeagent-front/src/lib/auth/logto.tsx`
- `../asianodeagent-front/src/lib/auth/logtoConfig.ts`
- `../asianodeagent-front/src/lib/auth/logtoToken.ts`
- `../asianodeagent-front/src/lib/backend/directClient.ts`
- `../asianodeagent-front/src/App.jsx`

#### FastAPI 后端

- 已有统一 `get_current_user()` 依赖；
- 已验证 JWT algorithm、`kid`、JWKS、issuer、audience、`exp` 和 `sub`；
- staging/production 默认强制 Bearer Token；
- 已有 `/api/v1/me`；
- 已有 `WorkspaceMember`、role 默认权限和 member permission override；
- 业务路由普遍执行 workspace membership 和权限检查；
- 聊天、文档、知识库等查询具有 workspace/owner/resource 过滤；
- `/dev/oidc` 和 dev direct token 在非 development 环境关闭；
- 生产启动配置会检查 HTTPS issuer、明确 CORS、限流和 SQLAdmin 状态。

关键文件：

- `app/core/auth.py`
- `app/api/routes/me.py`
- `app/core/workspace_access.py`
- `app/core/permissions.py`
- `app/core/knowledge_access.py`
- `app/core/config.py`
- `app/main.py`

### 3.2 当前阻断点

#### 阻断点 A：Logto `sub` 被直接当作本地 UUID

当前 `_user_from_claims()` 把 Token 的 `sub` 直接写入 `AuthenticatedUser.user_id`，而 `/me`、workspace 权限和大量业务路由会执行 `UUID(current_user.user_id)`。

Logto `sub` 是外部身份标识，不能假设等于本地 PostgreSQL UUID。真实 Logto 用户即使 JWT 验证成功，也可能在 `/me` 或第一个 workspace 接口收到 403。

#### 阻断点 B：没有 Logto 首次登录初始化

当前只有 development identity 会自动创建本地 User。Logto 用户不存在以下流程：

- 查找外部身份映射；
- 创建本地 User；
- 并发首次登录去重；
- 同步基本资料；
- 返回待授权状态；
- 为管理员提供加入 workspace 的入口。

#### 阻断点 C：本地 User 要求 email 非空

现有 `User.email` 是非空字段。Google 通常可以提供 email，但微信网页身份不保证提供 email。要完整支持微信，不能把 email 作为创建本地 User 的必要身份键。

#### 阻断点 D：前端没有消费后端 `/me`

当前前端只根据 Logto ID Token 判断 `authenticated`，没有读取本地 User、memberships、role 和 permissions。因此：

- 登录成功不等于业务身份初始化成功；
- 无 workspace membership 没有独立状态页；
- active workspace 仍来自固定环境变量；
- 权限菜单目前没有使用后端权威权限；
- 前端 query key 没有完整包含 workspace 作用域。

#### 阻断点 E：真实 Logto/Google/微信环境尚未配置和验收

环境变量仍是占位值，也没有真实 Token → `/me` → workspace API 的端到端测试。

## 4. 目标架构与信任边界

### 4.1 身份与权限数据的所有权

| 数据 | 权威来源 | 前端是否可信 |
| --- | --- | --- |
| 登录是否完成 | Logto SDK / Logto session | 仅用于 UI 状态 |
| 外部身份 `sub` | 已验证的 Logto Access Token | 否 |
| 本地 `User.id` | FastAPI + PostgreSQL | 否 |
| email/name/avatar | Logto claims，同步到本地资料 | 否，不用于授权 |
| workspace | PostgreSQL `WorkspaceMember` | 否 |
| role | PostgreSQL `WorkspaceMember.role` | 否 |
| permissions | role 默认值 + permission override | 否 |
| knowledge base grant | PostgreSQL `KnowledgeBaseGrant` | 否 |
| 资源 owner | PostgreSQL 业务表 | 否 |
| active workspace | 前端选择的请求上下文 | 否，后端必须再次校验 membership |

### 4.2 生产主链路

```text
React/Vite SPA
  ├─ LogtoProvider
  ├─ Hosted Sign-in
  ├─ callback + PKCE（由 Logto SDK 处理）
  ├─ getAccessToken(API_RESOURCE)
  ├─ POST /api/v1/auth/bootstrap
  ├─ GET /api/v1/me
  └─ Bearer Token + active workspace 调用业务 API

FastAPI
  ├─ 验证 Logto JWT
  ├─ 解析 ExternalPrincipal
  ├─ ExternalIdentity → User UUID
  ├─ 校验 User 状态
  ├─ 校验 active WorkspaceMember
  ├─ 计算 effective permissions
  └─ 校验业务资源 workspace/owner/grant
```

旧 Next.js/NextAuth bridge 只作为迁移兼容路径，不允许成为独立 Vite 前端的新依赖。生产切换完成后应单独安排删除。

## 5. 本地身份模型

### 5.1 推荐新增 `ExternalIdentity` 表

不要把外部 subject 塞进现有 `User.id`。推荐增加独立表：

```sql
CREATE TABLE "ExternalIdentity" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "userId" uuid NOT NULL REFERENCES "User"("id") ON DELETE CASCADE,
    "provider" varchar(32) NOT NULL,
    "subject" varchar(255) NOT NULL,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "lastLoginAt" timestamp,
    UNIQUE ("provider", "subject")
);

CREATE INDEX "ExternalIdentity_user_idx"
    ON "ExternalIdentity" ("userId");
```

Logto 链路固定使用：

```text
provider = "logto"
subject  = Access Token.sub
```

即使用户使用 Google 或微信登录，FastAPI 看到的身份提供方仍然是 Logto。Google/微信 identity 由 Logto 管理，业务库只依赖稳定的 Logto `sub`。

### 5.2 调整 `User` 表

建议迁移：

- `email` 改为可空，并扩展到 `varchar(320)`；
- `name`、`image` 保持可空；
- 增加 `status`：`active | suspended`，默认 `active`；
- 保留旧 `password` 字段用于迁移兼容，但 Logto 用户不写 password；
- 不给 `email` 增加外部身份唯一约束；
- email 变化只更新资料，不创建新 User。

### 5.3 `AuthenticatedUser` 拆分

把“Token 身份”和“业务身份”明确分开：

```python
class ExternalPrincipal(BaseModel):
    subject: str
    issuer: str
    email: str | None
    email_verified: bool | None
    name: str | None
    picture: str | None
    roles: list[str]
    claims: dict[str, Any]

class AuthenticatedUser(BaseModel):
    user_id: UUID               # 本地 User.id
    external_subject: str       # Logto sub
    auth_provider: str          # logto
    email: str | None
    roles: list[str]            # 只作为附加上下文，不用于 workspace 授权
    claims: dict[str, Any]
```

JWT 验证函数只产生 `ExternalPrincipal`；业务依赖必须在查询 `ExternalIdentity` 后才产生 `AuthenticatedUser`。

### 5.4 并发和幂等要求

首次登录初始化必须在数据库事务中执行，并依赖 `(provider, subject)` 唯一约束处理并发：

1. 查询 identity；
2. 找到则更新 `lastLoginAt` 和非敏感资料；
3. 未找到则创建 User；
4. 创建 ExternalIdentity；
5. 若唯一约束冲突，回滚新 User 并重新读取已存在 identity；
6. 任何情况下都不能产生两个本地 User。

## 6. 首次登录与 workspace 策略

### 6.1 推荐 MVP 策略

采用“JIT 创建 User，但不自动授予 workspace”策略：

```text
首次 Logto 登录
  → 创建本地 User + ExternalIdentity
  → memberships = []
  → 前端显示“账号已创建，等待管理员授权”
  → 管理员加入 workspace
  → 用户刷新 /me 后进入业务页面
```

这样可以确保任何能够在 Logto 注册的人都不会自动获得业务数据权限。

### 6.2 第一个 owner

第一个 owner 通过一次性、显式的运维命令授予：

```text
grant-workspace-member
  --provider logto
  --subject <logto-sub>
  --workspace-id <uuid>
  --role owner
```

要求：

- 命令只操作明确的 subject 和 workspace UUID；
- 操作前显示目标用户和 workspace；
- 写入 `AuditLog`；
- 不允许“第一个登录的人自动成为 owner”；
- 不允许通过前端提交 email 获得 owner。

### 6.3 后续成员加入

在现有成员管理基础上补充：

- 查询已经完成 Logto 首次登录、但未加入当前 workspace 的本地用户；
- `POST /api/v1/admin/members` 创建 membership；
- 请求体只接受本地 `userId`、role 和初始 permissions；
- 要求调用者拥有 `members.manage`；
- owner/admin 保护逻辑继续复用现有实现；
- 创建、停用、恢复和权限变更都写 `AuditLog`。

邀请制可以作为后续增强。若未来按 email 邀请，必须要求 Logto email 已验证，并且邀请只表示管理员授权意图，不能把 email 当作身份主键。微信无 email 用户应支持按本地 User/Logto subject 授权。

## 7. 后端 API 设计

### 7.1 依赖分层

建议拆成三层：

```text
verify_access_token
  → ExternalPrincipal

get_current_user
  → 查 ExternalIdentity
  → 返回本地 AuthenticatedUser

require_workspace_permission
  → 查 WorkspaceMember
  → 计算 effective permissions
  → 返回 WorkspaceAccess
```

### 7.2 新增 `POST /api/v1/auth/bootstrap`

用途：登录回调完成后，显式、幂等地初始化本地业务身份。

认证：有效 Logto Bearer Token。

行为：

- 验证 Token；
- 创建或读取 User + ExternalIdentity；
- 同步允许同步的资料；
- 返回与 `/me` 相同的业务身份数据；
- 不自动创建 workspace membership；
- 限流；
- 不记录或返回完整 Token。

推荐响应：

```json
{
  "userId": "local-user-uuid",
  "email": "user@example.com",
  "name": "User",
  "image": "https://...",
  "status": "active",
  "accessState": "pending_workspace",
  "memberships": []
}
```

### 7.3 调整 `GET /api/v1/me`

`/me` 保持只读，只接受已经初始化的本地身份：

```json
{
  "userId": "local-user-uuid",
  "email": null,
  "name": "微信用户",
  "image": null,
  "status": "active",
  "accessState": "ready",
  "memberships": [
    {
      "membershipId": "uuid",
      "workspaceId": "uuid",
      "workspaceName": "Asianode",
      "role": "viewer",
      "status": "active",
      "permissions": ["knowledge.read", "chat.read", "chat.write"],
      "overrides": []
    }
  ]
}
```

状态语义：

- Token 无效或过期：401；
- Token 有效但 identity 尚未 bootstrap：403 `auth_identity:not_initialized`；
- User suspended：403 `user:suspended`；
- User 有效但没有 membership：200，`accessState=pending_workspace`；
- workspace membership 不存在/停用：业务接口返回 403；
- 权限不足：403；
- 数据库或 JWKS 临时不可用：503。

### 7.4 新增成员初始化能力

建议增加：

```text
GET  /api/v1/admin/access-candidates?workspace_id=<uuid>&query=<text>
POST /api/v1/admin/members?workspace_id=<uuid>
```

`POST` 示例：

```json
{
  "userId": "local-user-uuid",
  "role": "viewer",
  "permissions": ["knowledge.read", "chat.read", "chat.write"]
}
```

后端必须检查：

- actor 有 `members.manage`；
- actor 是目标 workspace 的 active member；
- target User 存在且未 suspended；
- 不能创建重复 membership；
- 只有 owner 能授予 owner；
- workspace 至少保留一个 active owner。

### 7.5 现有业务接口保持不变

业务接口继续接收 `workspace_id` 作为请求上下文，但必须：

- 使用本地 User UUID 查询 membership；
- 不信任前端 role、permissions 或 owner；
- 在 SQL 中携带 workspace 条件；
- 对 Chat/Document/Vote/File 等继续检查 owner/resource；
- 对知识库继续执行 grant 过滤；
- 不使用 Logto Token 的 role 直接替代本地 role。

## 8. 前端认证状态模型

### 8.1 AuthContext 目标结构

当前 `Session = { user } | null` 不足以表达业务状态。建议扩展为：

```ts
type AuthStatus =
  | "loading"
  | "unauthenticated"
  | "initializing"
  | "pending_workspace"
  | "authenticated"
  | "suspended"
  | "error";

type AuthContextValue = {
  status: AuthStatus;
  logtoUser: LogtoProfile | null;
  currentUser: CurrentUserResponse | null;
  activeWorkspace: WorkspaceMembership | null;
  setActiveWorkspace: (workspaceId: string) => void;
  refreshCurrentUser: () => Promise<void>;
  signOut: () => Promise<void>;
};
```

### 8.2 登录后初始化时序

```text
/callback 完成
  → Logto isAuthenticated=true
  → getAccessToken(API_RESOURCE)
  → POST /api/v1/auth/bootstrap
  → GET /api/v1/me 或直接使用 bootstrap 响应
  → 选择 active workspace
  → status=authenticated
```

失败分支：

- 401：清理应用认证态，进入 `/login`；
- `pending_workspace`：进入 `/access-pending`；
- suspended：进入 `/account-suspended`；
- 503：显示可重试错误，不误判为未登录；
- 网络错误：保留 Logto session，允许重试 bootstrap。

### 8.3 Active workspace

选择规则：

1. 从 `/me.memberships` 获取 active memberships；
2. 读取按本地 User ID 隔离的上次选择；
3. 若仍是 active membership，则使用；
4. 否则使用第一个 active membership；
5. memberships 为空则进入 pending 状态；
6. 切换后清理/失效 workspace 相关 React Query 和 SWR cache。

本地存储只保存“上次选择的 workspace ID”，它不是授权凭证。FastAPI 每次请求仍要验证 membership。

### 8.4 请求层

`apiFetch()` 继续统一处理：

- 调用 `getAccessToken(VITE_LOGTO_API_RESOURCE)`；
- 注入 Bearer Token；
- 为 workspace-scoped API 注入 active workspace；
- 不从固定 `VITE_WORKSPACE_ID` 获取生产 workspace；
- 统一解析 401/403/503；
- 不在日志、toast、错误监控中输出 Token；
- Token 获取失败时通知 AuthContext，而不是发送匿名业务请求。

Logto React SDK 的 `getAccessToken(resource)` 会在缓存 Token 过期时尝试使用 refresh token 获取新 Token。API 返回 401 且 SDK 仍认为 Token 有效时，不应无限重试；应清理业务会话并要求重新登录。

### 8.5 前端权限 UX

所有权限 UI 基于当前 active membership 的 `permissions`：

- `members.read`：显示成员页面入口；
- `members.manage`：允许编辑成员；
- `knowledge.manage`：显示知识库创建/修改/文件管理入口；
- `chat.delete`：显示删除聊天操作；
- 其他权限按 `app/core/permissions.py` 和 `src/lib/permissions.ts` 对齐。

还需要：

- Settings 路由守卫；
- 无权限页面；
- 403 后刷新 `/me`，处理管理员刚刚修改权限的情况；
- query key 至少包含本地 `userId + workspaceId + resource`；
- 退出或切换用户时清空用户级缓存。

前端权限判断只改善 UX，FastAPI 仍然是安全边界。

## 9. Logto Console 配置

### 9.1 创建 React SPA 应用

开发环境：

```text
Redirect URI:             http://localhost:5173/callback
Post sign-out redirect:   http://localhost:5173/
```

生产环境：

```text
Redirect URI:             https://<frontend-domain>/callback
Post sign-out redirect:   https://<frontend-domain>/
```

要求：

- 生产优先使用精确 URI；
- Preview wildcard 只在确实需要时启用；
- `/callback` 必须是前端公开路由；
- 回调完成后只跳转同源、已验证的 return path；
- SPA 不配置 client secret。

### 9.2 创建 API Resource

建议：

```text
API Name:       Asianode FastAPI
API Identifier: https://api.<your-domain>
Token TTL:      3600 秒（先使用默认值）
```

以下三处必须完全一致：

```text
VITE_LOGTO_API_RESOURCE
AUTH_AUDIENCE
Logto API Identifier
```

React `LogtoConfig.resources` 必须包含该 identifier，前端调用 `getAccessToken(identifier)` 获取用于 FastAPI 的 JWT，不能把 UserInfo opaque token 当作 FastAPI access token。

MVP 不必在 Logto API Resource 中迁移本地业务 permissions；权限仍从 PostgreSQL 读取。

### 9.3 Google Connector

1. 在 Google Cloud 创建或选择项目；
2. 配置 OAuth consent screen；
3. 创建类型为 Web application 的 OAuth Client；
4. Authorized JavaScript origins 填 Logto 实例 origin；
5. Authorized redirect URI 使用 Logto Google Connector 页面给出的 Callback URI；
6. 将 Google Client ID/Client Secret 只填入 Logto Connector；
7. 登录用途保持基本 scopes：`openid profile email`；
8. External 应用开发期配置 test users，生产前发布；
9. 在 Logto Sign-up and sign-in 中启用 Google Social sign-in；
10. 验证新用户、老用户、取消授权和退出。

不要把 Google client secret 写入 `.env`、Vite 或 FastAPI。

### 9.4 WeChat Web Connector

1. 在微信开放平台创建并认证账号；
2. 在“网页应用”中创建应用；
3. 授权回调域填写 Logto 域名，不是 React 前端域名；
4. 等待微信平台审核；
5. 将微信 Client ID/Client Secret 填入 Logto WeChat Web Connector；
6. scope 默认使用 `snsapi_userinfo`，如需更小范围再评估 `snsapi_base`；
7. 在 Logto Sign-up and sign-in 中启用 WeChat Web Social sign-in；
8. 使用真实微信账号在桌面浏览器完成扫码登录测试；
9. 验证无 email 的微信用户也能创建本地 User；
10. 记录审核、域名和生产切换依赖。

WeChat Web Connector 只覆盖网页应用；未来移动端需要单独的 WeChat Native Connector。

### 9.5 Google/微信账号关联策略

默认规则：不同 Logto `sub` 就是不同本地 User，绝不按 email 自动合并。

如果产品要求同一个人能把 Google 和微信关联到同一账号，应使用 Logto Account API/Account Center 提供显式 link/unlink 流程。只有当 Logto 最终保持同一个 user `sub` 时，本地业务用户才保持同一个 `User.id`。

## 10. 环境变量

### 10.1 React/Vite

```env
VITE_LOGTO_ENDPOINT=https://<tenant>.logto.app
VITE_LOGTO_APP_ID=<spa-app-id>
VITE_LOGTO_API_RESOURCE=https://api.<your-domain>
VITE_FASTAPI_URL=https://api.<your-domain>
```

规则：

- 不增加 `VITE_LOGTO_CLIENT_SECRET`；
- 生产不使用 `VITE_WORKSPACE_ID` 作为真实 active workspace；
- 所有 `VITE_*` 都视为浏览器公开配置；
- production build 缺少三项 Logto 配置时应失败或显示阻断页。

### 10.2 FastAPI

```env
ASIANODE_ENVIRONMENT=production
ASIANODE_DEBUG=false
AUTH_REQUIRED=true
AUTH_ISSUER=https://<tenant>.logto.app/oidc
AUTH_AUDIENCE=https://api.<your-domain>
AUTH_JWKS_URL=https://<tenant>.logto.app/oidc/jwks
AUTH_ALGORITHMS=RS256
CORS_ORIGINS=https://<frontend-domain>
```

规则：

- `AUTH_ISSUER` 必须与 Token `iss` 完全一致；
- `AUTH_AUDIENCE` 必须与 API Resource identifier 完全一致；
- CORS 只允许真实前端 origin；
- Preview 域名需要明确的环境策略，不能使用 `*`；
- `SQLADMIN_ENABLED=false`；
- 生产不得使用 fallback bridge/dev secret；
- 密钥由部署平台 Secret 管理。

## 11. 错误模型

建议统一返回：

```json
{
  "code": "auth_identity:not_initialized",
  "message": "Your account has not been initialized.",
  "requestId": "..."
}
```

错误码建议：

| HTTP | code | 语义 |
| --- | --- | --- |
| 401 | `auth:token_required` | 缺少 Bearer Token |
| 401 | `auth:token_invalid` | 签名、issuer、audience 或格式错误 |
| 401 | `auth:token_expired` | Token 已过期且无法恢复 |
| 403 | `auth_identity:not_initialized` | 未完成本地 bootstrap |
| 403 | `user:suspended` | 本地用户被停用 |
| 403 | `workspace:membership_required` | 没有 active membership |
| 403 | `workspace:permission_denied` | 缺少权限 |
| 403 | `workspace:context_mismatch` | workspace 上下文不匹配 |
| 404 | `resource:not_found` | 当前 workspace 中资源不存在 |
| 503 | `auth:jwks_unavailable` | JWKS 临时不可用 |
| 503 | `database:unavailable` | 本地身份或权限数据库不可用 |

不要把所有 403 都重定向到登录页；登录有效但无业务权限时，应显示对应状态。

## 12. 安全要求

- 使用 Logto React SDK 的 Authorization Code + PKCE 流程；
- 只接受 `Authorization: Bearer` 访问业务 API；
- 验证 `alg`、`kid`、签名、issuer、audience、`exp`、`sub`；
- JWKS `kid` 未命中时允许一次强制刷新，不能跳过签名验证；
- 不使用 ID Token 调 FastAPI，必须使用目标 API Resource 的 Access Token；
- 不信任前端提交的 `userId`、role、permissions、workspace owner；
- 不按 email 合并账号；
- 不记录 access token、refresh token、authorization code 或第三方 secret；
- bootstrap 和登录相关错误日志只记录 request ID、issuer、subject hash 和错误类型；
- 生产 CORS 使用明确 origin；
- 生产使用 HTTPS；
- User/WorkspaceMember suspended 必须在每次请求授权时生效；
- member/role/permission/owner 修改写 `AuditLog`；
- 管理员不能删除或降级最后一个 owner；
- 开发 OIDC、SQLAdmin、mock database 和 fallback secret 不得进入生产路径。

## 13. 实施阶段

### 预计代码改动路径

| 工作项 | 主要文件 |
| --- | --- |
| 身份表和 User 字段迁移 | 新增 `migrations/0005_auth_identity.sql`、`app/db/migrate_auth_identity.py`、`app/db/auth_identity_status.py`，更新 `Makefile` |
| JWT principal 与本地身份映射 | 更新 `app/core/auth.py`，新增 `app/core/identity.py` |
| bootstrap 与 `/me` | 新增 `app/api/routes/auth.py`，更新 `app/api/routes/me.py`、`app/main.py` |
| workspace 成员初始化 | 更新 `app/api/routes/admin_members.py`、`app/core/workspace_access.py` |
| 后端测试 | 在 `tests/` 增加 identity、bootstrap、JWT、workspace authorization 测试 |
| 前端认证状态 | 更新 `../asianodeagent-front/src/lib/auth.tsx`、`../asianodeagent-front/src/lib/auth/logto.tsx`、`../asianodeagent-front/src/lib/auth/logtoConfig.ts` |
| Bearer Token 与 active workspace | 更新 `../asianodeagent-front/src/lib/backend/directClient.ts`，新增或更新 current-user/workspace hooks |
| 登录后路由和状态页 | 更新 `../asianodeagent-front/src/App.jsx`，在 `../asianodeagent-front/src/components/auth/` 增加 pending、suspended、forbidden 状态页 |
| 权限 UI | 更新 `../asianodeagent-front/src/components/chat/appSidebar.tsx`、`../asianodeagent-front/src/components/settings/memberPermissions.tsx`、`../asianodeagent-front/src/lib/permissions.ts` |

新增文件名可在实现时按现有模块边界微调，但数据库迁移和业务查询必须留在 FastAPI；不得写入前端遗留的 `src/lib/db/`。

### Phase 0：确定配置和数据策略

- [ ] 确认 Logto Cloud 或 self-hosted 实例；
- [ ] 确认开发、preview、production 前端/API 域名；
- [ ] 确认 API Resource identifier；
- [ ] 确认 JIT User + pending workspace 策略；
- [ ] 确认第一个 owner 的 Logto subject；
- [ ] 确认 Google External/Internal 发布方式；
- [ ] 确认微信开放平台账号、网页应用和审核负责人；
- [ ] 确认不同 Logto `sub` 不自动合并。

完成条件：配置表和负责人明确，数据库方案获确认。

### Phase 1：数据库身份模型

- [ ] 新增 `ExternalIdentity` migration；
- [ ] 将 `User.email` 调整为 nullable/320；
- [ ] 增加 `User.status`；
- [ ] 增加唯一约束和索引；
- [ ] 增加 migration status 检查；
- [ ] 增加只读 migration preflight；
- [ ] 增加回滚说明；
- [ ] 更新 schema 文档和测试 fixture。

完成条件：migration 可重复执行，旧 User 数据不丢失，现有业务外键保持有效。

### Phase 2：FastAPI 身份解析

- [ ] 增加 `ExternalPrincipal`；
- [ ] 保留并整理 JWT 验证；
- [ ] 增加 external identity resolver；
- [ ] 增加幂等 bootstrap service；
- [ ] 新增 `POST /api/v1/auth/bootstrap`；
- [ ] 调整 `AuthenticatedUser.user_id` 为本地 UUID；
- [ ] 调整 `/api/v1/me` 响应和状态码；
- [ ] 增加 User suspended 检查；
- [ ] 保证业务路由无需认识 Logto `sub`；
- [ ] 增加结构化 401/403 错误码；
- [ ] 给 bootstrap 加限流和安全日志。

完成条件：非 UUID Logto `sub` 能稳定访问 `/me`，所有业务路由收到本地 UUID。

### Phase 3：成员初始化闭环

- [ ] 增加第一个 owner 运维命令；
- [ ] 增加 access candidates 查询；
- [ ] 增加 `POST /admin/members`；
- [ ] 复用 owner 和权限保护；
- [ ] 增加创建/停用/恢复 membership 的 AuditLog；
- [ ] 更新成员管理前端。

完成条件：新 Logto 用户无需直接改 SQL 即可由管理员加入 workspace。

### Phase 4：React/Vite AuthContext

- [ ] 扩展 AuthContext 状态模型；
- [ ] callback 后调用 bootstrap；
- [ ] 增加 `/me` 查询；
- [ ] 增加 `/access-pending`；
- [ ] 增加 `/account-suspended`；
- [ ] 增加 `/forbidden`；
- [ ] 实现 active workspace 选择和持久化；
- [ ] 将 workspace 注入从固定 env 改为 active workspace；
- [ ] 让 Sidebar/Settings 路由使用后端 permissions；
- [ ] 401 时回到登录，403 时保留登录并显示业务状态；
- [ ] 退出、切换用户和 workspace 时清理缓存；
- [ ] 删除新前端对 server-only/NextAuth 遗留模块的引用。

完成条件：前端可以明确区分未登录、初始化中、待授权、已登录无权限和正常可用。

### Phase 5：Logto、Google 和微信配置

- [ ] 创建 Logto SPA；
- [ ] 配置开发/生产 redirect URI；
- [ ] 配置 post sign-out URI；
- [ ] 创建 API Resource；
- [ ] 配置 Google OAuth Client 和 Logto Connector；
- [ ] 发布或配置 Google test users；
- [ ] 创建微信开放平台网页应用；
- [ ] 配置微信授权回调域为 Logto 域名；
- [ ] 完成微信审核；
- [ ] 配置 Logto WeChat Web Connector；
- [ ] 在 Sign-up and sign-in 启用 Google/微信；
- [ ] 配置各环境变量和 CORS。

完成条件：Google 和微信都可以在目标域名完成 Hosted Sign-in。

### Phase 6：测试和联调

- [ ] JWT 正确 issuer/audience/签名/有效期；
- [ ] 错误 issuer/audience/签名/过期 Token 返回 401；
- [ ] JWKS key rotation 测试；
- [ ] 非 UUID `sub` 映射测试；
- [ ] 并发首次登录只创建一个 User；
- [ ] email 改变不创建新 User；
- [ ] 无 email 微信用户可以 bootstrap；
- [ ] 无 membership 返回 pending 状态；
- [ ] suspended User 被拒绝；
- [ ] workspace membership、deny override 和跨 workspace 拒绝；
- [ ] Google 浏览器 E2E；
- [ ] 微信扫码浏览器 E2E；
- [ ] 刷新页面保持登录；
- [ ] Token 过期后自动刷新；
- [ ] 退出后受保护页面重新要求登录；
- [ ] 权限修改后 UI 和 API 同步；
- [ ] 浏览器日志、后端日志和错误监控不包含 Token。

完成条件：自动化测试通过，Google/微信真实账号验收通过。

### Phase 7：生产切换与遗留清理

- [ ] 在 staging 使用生产同构配置联调；
- [ ] 备份数据库并执行 identity migration；
- [ ] 配置生产 Secrets；
- [ ] 确认 `AUTH_REQUIRED=true`；
- [ ] 确认 dev OIDC、SQLAdmin 和 mock 功能关闭；
- [ ] 小范围用户灰度；
- [ ] 观察 401/403/bootstrap/JWKS 指标；
- [ ] 确认回滚方案；
- [ ] 停止 Vite 前端对 NextAuth bridge 的依赖；
- [ ] 单独安排删除旧 Next.js Auth/BFF 路径。

完成条件：生产只通过 Logto Bearer Token 进入 FastAPI 业务链路。

## 14. 测试矩阵

| 场景 | 预期结果 |
| --- | --- |
| Google 首次登录 | 创建一个 User + ExternalIdentity，进入 pending |
| Google 重复登录 | 复用同一 User UUID |
| 微信首次登录且无 email | 创建 User，email 为 null，进入 pending |
| 微信重复登录 | 复用同一 User UUID |
| 两个并发 bootstrap | 数据库中只有一条 identity 和一个 User |
| 有效 Token、未 bootstrap | 403 `auth_identity:not_initialized` |
| 已 bootstrap、无 membership | `/me` 200，`pending_workspace` |
| viewer 访问成员管理 | 403，前端不显示管理入口 |
| admin 更新成员权限 | 成功并写 AuditLog |
| 跨 workspace 修改请求参数 | 403 |
| deny override | 对应操作 403 |
| suspended membership | workspace 接口 403 |
| suspended User | 所有业务接口 403 |
| 错误 audience | 401 |
| 错误 issuer | 401 |
| 过期 Token | SDK 尝试刷新；失败后重新登录 |
| JWKS 更换 `kid` | 强制刷新 JWKS 后验证成功 |
| 退出 | 清除 Logto/业务状态和用户缓存 |
| Google 和微信不同 `sub` | 创建不同本地 User，不按 email 合并 |

## 15. 验证命令

### FastAPI

```bash
cd asianode-fastapi
uv run pytest -q
```

身份 migration 建立后应增加：

```bash
make auth-migration-status
make migrate-auth-identity
```

迁移命令必须沿用现有数据库安全目标检查，默认拒绝误操作远程数据库。

### React/Vite

```bash
cd asianodeagent-front
bun run lint
bun run build
```

还需要人工验证：

- `/login` → Logto；
- Google 登录；
- 微信扫码登录；
- `/callback`；
- pending workspace；
- active workspace 切换；
- 成员权限页面；
- 聊天、历史、文档、知识库和文件上传；
- 退出与刷新恢复。

## 16. 上线与回滚

### 16.1 上线顺序

1. 部署向后兼容的数据库 migration；
2. 部署支持 external identity 的 FastAPI；
3. 在 staging 完成真实 Logto Token 联调；
4. 配置生产 Logto SPA/API Resource/Connectors；
5. 部署 React/Vite 前端；
6. bootstrap 第一个 owner；
7. 灰度 Google 登录；
8. 灰度微信登录；
9. 扩大用户范围；
10. 观察稳定后关闭旧认证入口。

### 16.2 回滚原则

- 新增表和 nullable 字段 migration 必须向后兼容旧代码；
- 旧 `User.id` 和所有业务外键不变化；
- FastAPI 可通过部署回滚恢复旧版本；
- 前端可回滚到旧构建；
- Logto Connector 可暂时从 Sign-in experience 隐藏，而不删除用户；
- 不在紧急回滚中删除 `ExternalIdentity` 或新建 User；
- 回滚期间继续拒绝未映射身份，不能临时信任 email 或前端 userId。

## 17. 可观测性

建议指标：

- `auth_token_validation_total{result}`；
- `auth_bootstrap_total{result}`；
- `auth_identity_resolution_total{result}`；
- `auth_jwks_refresh_total{result}`；
- `auth_login_provider_total{provider}`（仅记录 google/wechat 类别，不记录身份数据）；
- `authorization_denied_total{reason}`；
- `workspace_membership_denied_total`；
- 401/403/503 比例；
- callback、bootstrap 和 `/me` 延迟。

日志字段可包含 request ID、local user UUID、workspace UUID 和错误码；外部 subject 只记录不可逆 hash，禁止记录 Token、authorization code 和 connector secret。

## 18. 完成定义

只有同时满足以下条件，才认为认证授权闭环完成：

- [ ] Google 和微信网页登录都通过真实账号验收；
- [ ] Access Token 的 audience 是 Asianode FastAPI API Resource；
- [ ] FastAPI 不再把 Logto `sub` 当作本地 UUID；
- [ ] 同一个 Logto `sub` 始终映射到同一个本地 User UUID；
- [ ] 微信无 email 用户可正常初始化；
- [ ] 首次登录不自动获得 workspace 权限；
- [ ] 管理员可以在产品流程内授予 membership；
- [ ] 前端以 `/me` 为本地身份和权限来源；
- [ ] active workspace 来自 memberships，而不是生产环境固定值；
- [ ] 所有业务接口继续执行 workspace/role/permission/resource 校验；
- [ ] Token 过期、退出、suspended、401、403、503 都有明确行为；
- [ ] 自动化测试和真实 E2E 通过；
- [ ] 生产环境关闭开发认证和 SQLAdmin；
- [ ] 独立 Vite 前端不再依赖 NextAuth 运行时。

## 19. 官方参考

- [Logto React quick start](https://docs.logto.io/quick-starts/react)
- [Logto social connectors](https://docs.logto.io/connectors/social-connectors)
- [Logto Google connector](https://docs.logto.io/integrations/google)
- [Logto WeChat Web connector](https://docs.logto.io/integrations/wechat-web)
- [Logto authorization and API resources](https://docs.logto.io/authorization)
- [Logto RBAC and API resource identifiers](https://docs.logto.io/authorization/role-based-access-control)
