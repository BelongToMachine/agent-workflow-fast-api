# Asianode 本地账号密码与服务端会话迁移计划

## 1. 文档状态

- 状态：阶段 0 预检部分完成；本地 Session 双轨路径已在本地开发接入，生产尚未切换
- 目标前端：`asianodeagent-front`（React + Vite，部署于 Vercel）
- 目标后端：`asianode-fastapi`（FastAPI，部署于阿里云 VPS）
- 生产前端域名：`https://copilot.asianodeatlas.com`
- 生产 API 域名：`https://api.asianodeatlas.com`
- 当前认证提供方：Logto OIDC
- 目标认证方式：本地账号密码 + FastAPI 服务端不透明 Session Cookie

本文档描述如何在保留现有 `User`、Workspace、聊天、文档和权限数据的前提下，逐步移除 Logto，切换到由 FastAPI 管理密码、账号生命周期和浏览器会话的认证架构。

## 2. 核心结论

当前系统只有一个第一方 Vite 前端和一个第一方 FastAPI，因此不建议在业务系统中自行实现完整 OIDC Provider。

OIDC 是建立在 OAuth 2.0 之上的身份协议。自行实现 OIDC Provider 不只是增加账号密码表，还必须正确实现：

- Authorization Endpoint；
- Token Endpoint；
- Discovery Metadata；
- JWKS 和签名密钥轮换；
- Authorization Code + PKCE；
- `state`、`nonce` 和精确 Redirect URI 校验；
- Access Token、ID Token 和 Refresh Token 生命周期；
- Token 撤销、重放防护和客户端注册；
- Scope、Audience、Consent 和错误协议。

对于当前单一 Web 应用，推荐使用以下结构：

```text
Vercel React 前端
copilot.asianodeatlas.com
        │
        │ HTTPS + credentials: include
        │ email/password、Session Cookie、CSRF Header
        ▼
FastAPI
api.asianodeatlas.com
        │
        ├── Argon2id 密码验证
        ├── 不透明 Session 创建与验证
        ├── CSRF、限流、账号状态和审计
        ▼
PostgreSQL
User / PasswordCredential / AuthSession / AuthOneTimeToken
WorkspaceMember / WorkspaceMemberPermission

Redis
登录限流、失败计数和短期安全状态
```

这套方案属于本地 Web 认证和服务端会话，不属于 OIDC。未来确实需要移动端、多套业务系统或第三方 SSO 时，应部署成熟的自托管 OIDC Provider，而不是在 FastAPI 业务服务中自行实现协议。

## 3. 设计原则

1. `User.id` 继续作为业务用户唯一标识，不迁移聊天、文档或 Workspace 外键。
2. 密码凭据与用户资料分离，不能复用当前长度不足的 legacy `User.password varchar(64)`。
3. 浏览器只保存不透明 Session Cookie，不保存长期 Access Token 或 Refresh Token。
4. Session 原文、邀请 Token 原文和密码重置 Token 原文不得写入数据库或日志。
5. FastAPI 是最终认证和授权边界，前端传入的用户、角色和 Workspace 身份不可信。
6. Workspace 角色和权限继续由 `WorkspaceMember`、`WorkspaceMemberPermission` 管理。
7. 先双轨迁移，验证本地认证后再删除 Logto，避免一次性切换导致所有用户无法登录。
8. Cloudflare Tunnel 只承担公网传输，不承担应用登录状态。

## 4. 目标数据模型

### 4.1 保留的现有表

- `User`
- `Workspace`
- `WorkspaceMember`
- `WorkspaceMemberPermission`
- 聊天、消息、文档、知识库和其他业务表

切换认证方式时不得重新生成 `User.id`，否则现有业务资源的用户外键会断裂。

### 4.2 `PasswordCredential`

一个本地用户最多拥有一条当前密码凭据。

```text
userId              uuid primary key references User(id) on delete cascade
passwordHash        text not null
passwordVersion     integer not null default 1
passwordChangedAt   timestamp not null
createdAt           timestamp not null
updatedAt           timestamp not null
```

要求：

- 使用 Argon2id；
- `passwordHash` 使用 `text`，不要限制为 64 个字符；
- 不保存明文密码、可逆密文或单独 salt 字段；
- Argon2 编码结果已经携带算法、salt 和参数；
- 密码算法参数升级时，在用户下次成功登录后自动 rehash。

### 4.3 `AuthSession`

```text
id                  uuid primary key
userId              uuid not null references User(id) on delete cascade
tokenHash           char(64) unique not null
createdAt           timestamp not null
lastSeenAt          timestamp not null
idleExpiresAt       timestamp not null
absoluteExpiresAt   timestamp not null
revokedAt           timestamp null
ipHash              char(64) null
userAgentHash       char(64) null
```

设计要求：

- 浏览器端 Session Token 由 CSPRNG 生成，至少 256 bit；
- 数据库只保存 Token 的 SHA-256 哈希；
- Session Token 必须无业务含义，不能携带用户 ID、邮箱或角色；
- 权限变更、密码变更和敏感操作后应旋转或撤销 Session；
- 服务端同时执行 idle timeout 和 absolute timeout；
- `lastSeenAt` 可以按时间窗口合并更新，避免每个请求都写数据库。

### 4.4 `AuthOneTimeToken`

邀请激活、邮箱验证和密码重置统一使用一次性 Token 表。

```text
id                  uuid primary key
userId              uuid null references User(id) on delete cascade
normalizedEmail     varchar(320) not null
purpose             varchar(32) not null
tokenHash           char(64) unique not null
workspaceId         uuid null
workspaceRole       varchar(16) null
expiresAt           timestamp not null
usedAt              timestamp null
revokedAt           timestamp null
createdBy            uuid null references User(id)
createdAt           timestamp not null
```

`purpose` 至少包括：

- `invitation`
- `password_reset`
- `email_verification`

一次性 Token 要求：

- 使用 CSPRNG 生成；
- 数据库只保存 SHA-256 哈希；
- 按用途绑定，不得跨用途使用；
- 短时有效；
- 成功使用后在同一个数据库事务中标记 `usedAt`；
- 新 Token 创建后撤销同一用户、同一用途的旧 Token；
- 不得把完整 Token 写入应用日志、审计日志或错误信息。

### 4.5 `AuthAuditLog`

现有 `AuditLog.workspaceId` 为必填，不适合记录尚未进入 Workspace 的登录事件。建议新增独立认证审计表，或者经过明确迁移后允许认证事件没有 Workspace。

建议记录：

- 登录成功和失败；
- 登出和全部设备登出；
- 邀请创建、接受、撤销和过期；
- 密码修改和密码重置；
- Session 创建、旋转和管理员撤销；
- 用户激活、暂停和恢复；
- 管理员敏感操作重新认证结果。

不得记录：

- 密码；
- Session Token 原文；
- 邀请或重置 Token 原文；
- 完整 Authorization Header；
- 不必要的个人隐私信息。

### 4.6 邮箱唯一性

本地密码登录依赖邮箱时，需要先检查生产数据库中是否存在大小写不同或重复邮箱，再建立规范化唯一约束。

建议使用以下任一方案：

- PostgreSQL `citext`；或
- 独立 `normalizedEmail` 字段；或
- `lower(email)` 的部分唯一索引。

在完成重复邮箱预检前，不得直接添加唯一索引。

## 5. 密码安全策略

### 5.1 密码哈希

使用 `pwdlib[argon2]` 或 `argon2-cffi` 提供的 Argon2id 实现，不自行编写密码哈希算法。

参数起点至少满足 OWASP 当前建议：

```text
memory_cost >= 19 MiB
time_cost >= 2
parallelism >= 1
```

最终参数需要在 1 CPU、768 MiB 限制下的生产 API 容器中基准测试。单次密码验证应足够慢以增加离线破解成本，同时不能让少量并发登录耗尽容器资源。

### 5.2 密码规则

- 密码作为单因素认证时，最小长度采用 15 个字符；
- 支持至少 64 个字符；
- 允许空格、粘贴和密码管理器自动填充；
- 不强制大小写、数字、符号组合；
- 使用常见和已泄露密码 blocklist；
- 没有泄露迹象时不定期强制修改密码；
- 不使用安全问题找回密码；
- 不截断密码；
- 接受 Unicode 时，在哈希前采用一致的 NFC 规范化策略。

### 5.3 防止账号枚举和暴力破解

- 登录失败统一返回“账号或密码错误”；
- 不暴露邮箱是否存在、账号是否已邀请；
- 未知邮箱也执行一次固定 dummy Argon2 验证，降低响应时间差异；
- 同时按客户端 IP、规范化邮箱和全局异常速率限流；
- 采用逐步延迟或临时冷却，避免永久硬锁造成拒绝服务；
- 管理员账号可以采用更严格阈值；
- Cloudflare WAF 作为外层防护，FastAPI 限流仍是最终安全边界。

当前 FastAPI 通用限流按 `request.client.host` 取客户端地址。Cloudflare Tunnel 后该地址可能是本机连接地址，因此实施登录限流前，必须明确只信任 Cloudflare 转发的真实客户端地址，并保证 API 不能绕过 Tunnel 直接公网访问。

## 6. Session Cookie 设计

生产 Cookie：

```http
Set-Cookie: __Host-asianode_session=<opaque-random-token>;
  Path=/;
  Secure;
  HttpOnly;
  SameSite=Lax
```

要求：

- 使用 `__Host-` 前缀；
- 不设置 `Domain`；
- `Path=/`；
- 仅通过 HTTPS；
- JavaScript 无法读取；
- Cookie 只发给 `api.asianodeatlas.com`；
- Cookie 值只是不透明随机标识，不包含用户数据；
- 登出时服务端先撤销数据库 Session，再清除 Cookie；
- Cookie 的过期时间不是唯一安全边界，服务端必须独立检查 Session 是否过期或撤销。

当前前端和 API 是不同 Origin，但都属于 `asianodeatlas.com`。前端访问 API 时统一使用：

```ts
fetch(url, {
  ...init,
  credentials: "include",
});
```

不把 Cookie 的 `Domain` 设置为 `.asianodeatlas.com`，以减少其他子域伪造或窃取认证 Cookie 的风险。

## 7. CORS 与 CSRF

### 7.1 CORS

生产环境只允许明确 Origin：

```text
https://copilot.asianodeatlas.com
```

开发环境可以显式增加：

```text
http://localhost:5173
http://127.0.0.1:5173
```

要求：

- `allow_credentials=true`；
- `Access-Control-Allow-Origin` 不得为 `*`；
- 不使用泛匹配允许所有 `*.asianodeatlas.com`；
- 只允许实际需要的请求头和 HTTP 方法；
- 所有状态修改接口拒绝 simple content type，默认只接收 JSON 或明确的上传格式。

### 7.2 CSRF

所有 `POST`、`PUT`、`PATCH`、`DELETE` 请求执行双重防护：

1. 精确校验 `Origin`，必要时回退到严格 `Referer` 校验；
2. 校验 `X-CSRF-Token`。

建议流程：

```text
GET /api/v1/auth/csrf
  → 返回 CSRF token
  → 同时设置与其绑定的 CSRF Cookie

前端内存保存返回值
  → 写请求增加 X-CSRF-Token

FastAPI
  → 对比 Header、Cookie 和签名/服务端状态
  → 校验通过后执行写操作
```

登录接口也必须执行 Origin 和 CSRF 校验，防止 login CSRF。

## 8. API 合同

### 8.1 浏览器认证接口

| Method | Path | 作用 |
| --- | --- | --- |
| `GET` | `/api/v1/auth/csrf` | 获取 CSRF Token |
| `POST` | `/api/v1/auth/login` | 验证邮箱和密码，创建 Session |
| `POST` | `/api/v1/auth/logout` | 撤销当前 Session 并清除 Cookie |
| `POST` | `/api/v1/auth/logout-all` | 撤销当前用户全部 Session |
| `GET` | `/api/v1/auth/session` | 返回当前会话的最小用户状态 |
| `POST` | `/api/v1/auth/change-password` | 验证当前密码后修改密码 |
| `POST` | `/api/v1/auth/activate` | 使用邀请 Token 设置首次密码 |
| `POST` | `/api/v1/auth/password-reset/request` | 发起密码重置，始终返回通用结果 |
| `POST` | `/api/v1/auth/password-reset/confirm` | 使用一次性 Token 设置新密码 |

### 8.2 管理员接口

| Method | Path | 作用 |
| --- | --- | --- |
| `POST` | `/api/v1/admin/auth/invitations` | 创建员工邀请 |
| `POST` | `/api/v1/admin/auth/invitations/{id}/revoke` | 撤销邀请 |
| `POST` | `/api/v1/admin/auth/users/{id}/suspend` | 暂停用户并撤销 Session |
| `POST` | `/api/v1/admin/auth/users/{id}/restore` | 恢复用户 |
| `POST` | `/api/v1/admin/auth/users/{id}/password-reset` | 为用户生成一次性重置流程 |
| `GET` | `/api/v1/admin/auth/users/{id}/sessions` | 查看用户 Session 元数据 |
| `DELETE` | `/api/v1/admin/auth/users/{id}/sessions` | 撤销用户全部 Session |

管理员创建用户时不设置和查看员工密码。管理员只创建一次性邀请，员工本人设置密码。

### 8.3 统一 FastAPI 认证依赖

保留现有 `AuthenticatedUser` 作为业务层输入模型，将 `get_current_user()` 的实现从 Logto Bearer/JWKS 验证替换为：

```text
读取 __Host-asianode_session Cookie
        ↓
计算 SHA-256 tokenHash
        ↓
查询有效 AuthSession + User
        ↓
拒绝过期、撤销或 suspended 用户
        ↓
返回 AuthenticatedUser
        ↓
现有 Workspace 权限依赖继续运行
```

FastAPI 路由继续通过 `Annotated[AuthenticatedUser, Depends(get_current_user)]` 复用认证依赖。业务端点不应自行读取 Cookie 或重复查询 Session。

## 9. 登录与账号生命周期

### 9.1 邀请激活

```text
管理员创建邀请
        ↓
服务端创建随机 Token，只保存哈希
        ↓
员工打开 /activate?token=...
        ↓
前端提交 Token + 新密码
        ↓
FastAPI 在同一事务中：
  1. 锁定并验证 Token
  2. 创建或复用 User
  3. 写入 PasswordCredential
  4. 创建 WorkspaceMember
  5. 标记 Token 已使用
  6. 写入审计日志
  7. 创建 Session
```

### 9.2 日常登录

```text
前端获取 CSRF Token
        ↓
提交 email + password + X-CSRF-Token
        ↓
FastAPI 规范化邮箱并执行限流
        ↓
Argon2id 验证（未知用户执行 dummy hash）
        ↓
检查 User.status
        ↓
创建 AuthSession，设置 HttpOnly Cookie
        ↓
前端请求 GET /api/v1/me
```

### 9.3 修改密码

- 要求当前有效 Session；
- 要求再次输入当前密码；
- 检查新密码长度和 blocklist；
- 更新 Argon2id 哈希和 `passwordVersion`；
- 撤销其他 Session；
- 当前 Session 旋转 Token；
- 写入认证审计日志。

### 9.4 密码重置

- 请求接口始终返回相同响应，避免泄露账号是否存在；
- 重置 Token 一次性且短时有效；
- 确认重置时使用行锁或等效原子操作防止并发重复使用；
- 重置成功后撤销全部旧 Session；
- 不通过管理员或客服直接查看、复制用户密码。

### 9.5 用户暂停

- 将 `User.status` 设置为 `suspended`；
- 在同一操作中撤销该用户全部 Session；
- 所有后续请求即使持有旧 Cookie 也返回 403；
- 恢复用户不会自动恢复已撤销 Session，必须重新登录。

## 10. Logto 迁移策略

不得先删除 Logto 代码。采用双轨迁移，确保现有用户能够设置本地密码并保留原有数据。

### 阶段 0：生产预检与回滚准备

当前状态：预检已在本地开发配置完成一部分；生产数据库备份、用户映射导出和恢复演练尚未执行。`AUTH_MODE` 已加入配置，默认值为 `logto`，本阶段不会改变现有 Logto 行为。

- [ ] 备份 PostgreSQL；
- [ ] 导出当前用户、`ExternalIdentity` 和 Workspace membership 对照；
- [x] 对当前 `.env.local` 所指向的开发数据库执行只读身份迁移预检：`0005_auth_identity` 已应用；重复/非法邮箱检查命令已加入 `make auth-migration-preflight`。复核结果为 25 个用户、5 个外部身份、25 条 membership，发现 2 组重复邮箱和 12 条非法/空邮箱，因此用户映射仍被阻止；
- [ ] 确认每个待迁移用户可以联系；
- [x] 记录本地开发认证环境变量名（只记录名称，不记录值）：`AUTH_MODE`、`AUTH_REQUIRED`、`AUTH_ISSUER`、`AUTH_AUDIENCE`、`AUTH_JWKS_URL`、`AUTH_ALGORITHMS`；生产 Vercel/VPS 环境暂不处理；
- [ ] 验证回滚镜像和数据库恢复流程；
- [x] 建立迁移 feature flag：`AUTH_MODE=logto|dual|local_session`，默认 `logto`，当前阶段仅完成配置校验，尚未切换认证路径。

完成条件：数据库可恢复，用户映射明确，认证切换可以回滚。

### 阶段 1：新增本地认证基础设施

当前状态：本地基础设施和第一轮浏览器认证 API 已完成，邀请、激活和密码重置流程尚未实现。

- [x] 增加认证数据表和迁移：`0010_local_auth.sql`，并提供本地安全门控的 `make local-auth-status` / `make migrate-local-auth`；
- [x] 引入 Argon2id 库：使用 `pwdlib[argon2]`，执行 NFC 规范化和 15–1024 字符策略；
- [x] 实现 Session repository：只保存 SHA-256 Token hash，同时支持 idle/absolute expiry、touch 和撤销；
- [x] 实现 CSRF 和严格 Origin 校验基础工具；
- [ ] 实现认证专用限流；
- [ ] 实现邀请、激活、修改密码和重置密码接口；
- [x] 实现 CSRF、登录、登出和当前 Session 查询接口；
- [x] 保留现有 Logto Bearer 路径，本轮未改变当前认证行为。

完成条件：自动测试通过，本地测试账号可以独立完成完整生命周期。

### 阶段 2：后端双认证模式

当前状态：本地双认证入口已开始实现，尚未完成本地凭据领取和邀请制账号创建。

在 `AUTH_MODE=dual` 下：

- [x] 优先验证本地 Session；
- [x] 没有 Session 时临时接受现有 Logto Bearer Token；
- [ ] Logto 用户登录后可以领取或设置本地凭据；
- [x] 两种方式解析后都返回同一个 `AuthenticatedUser`；
- [x] Workspace 和权限逻辑保持不变；
- [ ] 新账号只通过本地邀请创建，不再通过 Logto bootstrap 创建。

完成条件：已存在用户可以用 Logto 登录，也可以完成本地密码激活。

### 阶段 3：前端切换到本地 Session

- [x] 实现真实登录表单；
- 实现激活、忘记密码、重置密码和修改密码页面；
- [x] 所有 FastAPI 请求增加 `credentials: "include"`；
- [x] 写请求增加 `X-CSRF-Token`；
- [x] 认证状态改为读取 `/api/v1/auth/session` 和 `/api/v1/me`；
- [x] 401 清空前端用户缓存并跳转 `/login`；
- [x] 403 保持现有 suspended 和 workspace pending UX；
- 停止在生产浏览器中获取 Logto Access Token。

当前状态：本地 Session 登录、Cookie 请求、CSRF 注入和前端会话守卫已接入，完整账号生命周期仍在后续工作中。

完成条件：Vercel 生产域名通过 Cloudflare Tunnel API 完成登录、刷新、业务请求和登出闭环。

### 阶段 4：用户迁移

- 为已有 Logto 用户生成本地密码激活链接；
- 按现有 email 找到本地 `User.id`，不得新建重复用户；
- 激活后新增 `PasswordCredential`；
- 验证原有聊天、文档和 Workspace 权限仍属于同一个 `User.id`；
- 记录每个用户迁移状态；
- 未迁移用户在截止日前仍可通过双轨模式登录。

Logto 不会提供现有用户的明文密码或可直接迁移的密码哈希，因此每个用户都必须通过激活或重置流程设置新密码。

完成条件：所有有效员工账号已有本地凭据。

### 阶段 5：生产切换

- 将后端切换到 `AUTH_MODE=local_session`；
- 前端移除 Logto Provider 和回调路由；
- 生产 Smoke Test；
- 观察 401、403、429、登录失败和 Session 错误指标；
- 保留一个明确的短期回滚窗口。

完成条件：生产请求完全不依赖 Logto。

### 阶段 6：Logto 清理

回滚窗口结束后再执行：

- 删除前端 Logto SDK；
- 删除前端 Logto 配置、Token bridge 和浏览器缓存清理代码；
- 删除 `/callback`；
- 删除 `/auth/bootstrap`；
- 删除后端 JWKS、issuer、audience 和外部 principal 验证逻辑；
- 删除 VPS 和 Vercel 的 `VITE_LOGTO_*`、`AUTH_ISSUER`、`AUTH_AUDIENCE`、`AUTH_JWKS_URL`；
- 确认无其他用途后移除 `pyjwt[crypto]`；
- 将旧 Logto 文档标记为历史方案；
- `ExternalIdentity` 至少保留到回滚窗口结束；
- 如未来仍可能接企业 SSO，可将其保留为通用 federated identity 表，不必立即删除。

## 11. 代码改造清单

### 11.1 FastAPI

#### 重写或拆分

- `app/core/auth.py`
  - 保留 `AuthenticatedUser`；
  - 增加 Session Cookie 读取和数据库解析；
  - 最终删除 Logto JWKS/Bearer 验证；
  - 使用可复用的 `Annotated` 认证依赖。
- `app/core/identity.py`
  - 移除硬编码 `LOGTO_PROVIDER`；
  - 将外部身份 bootstrap 替换为本地账号激活和用户查询；
  - 保持现有 User、WorkspaceMember 解析边界。
- `app/core/config.py`
  - 增加本地 Session、Cookie、CSRF 和密码参数；
  - 最终移除 Logto issuer、audience、JWKS 配置；
  - staging/production 启动时 fail fast 检查 Cookie 和 Origin 配置。
- `app/core/rate_limit.py`
  - 为登录、激活和密码重置增加独立限流策略；
  - 在 Tunnel 环境中安全获取真实客户端地址；
  - 不再依赖 Authorization Header 作为认证请求的限流键。

#### 新增建议

- `app/core/passwords.py`
- `app/core/sessions.py`
- `app/core/csrf.py`
- `app/db/auth_sessions.py`
- `app/db/local_auth_status.py`
- `app/db/migrate_local_auth.py`
- `app/core/auth_rate_limit.py`
- `app/api/routes/auth_sessions.py`
- `app/api/routes/auth_passwords.py`
- `app/api/routes/auth_invitations.py`
- `app/db/auth_repository.py`
- 对应 migration 和测试文件

#### 最终删除或停用

- `app/api/routes/auth_bootstrap.py`
- `app/api/routes/dev_oidc.py` 及其 router 注册
- Logto 专用 identity bootstrap 代码
- Logto 专用测试和命令行参数

### 11.2 React/Vite 前端

#### 删除

- `@logto/react`
- `src/lib/auth/logtoConfig.ts`
- `src/lib/auth/logto.tsx`
- `src/lib/auth/logtoStorage.ts`
- `src/lib/auth/logtoToken.ts`
- `/callback` 页面和路由
- Logto Auth Mode 切换器
- 生产 Logto 环境变量

#### 重写

- `src/lib/auth.tsx`
  - 使用 `/api/v1/auth/session` 或 `/api/v1/me` 读取会话；
  - 登录、登出和 Session 失效全部调用 FastAPI；
  - 不解码或信任浏览器 Token。
- `src/lib/auth/applicationAuth.tsx`
  - 删除 Logto bootstrap query；
  - 登录成功后直接加载当前用户和 Workspace 权限；
  - 保留 suspended、pending workspace 和权限 UX。
- `src/lib/backend/directClient.ts`
  - 删除生产 Bearer Token 注入；
  - 统一设置 `credentials: "include"`；
  - 对状态修改请求注入 CSRF Header。
- `src/App.jsx`
  - 登录表单调用真实 FastAPI API；
  - 删除公开 `/register`，保留邀请 `/activate`；
  - 增加忘记密码、重置密码和修改密码页面；
  - 删除 Logto Provider 和 `/callback`。

开发环境可以保留独立的测试登录入口，但必须与生产构建隔离，生产环境不得接受开发 Token。

## 12. 环境变量建议

后端建议增加：

```dotenv
AUTH_MODE=local_session
SESSION_COOKIE_NAME=__Host-asianode_session
SESSION_IDLE_TTL_SECONDS=<reviewed-value>
SESSION_ABSOLUTE_TTL_SECONDS=<reviewed-value>
AUTH_ALLOWED_ORIGINS=https://copilot.asianodeatlas.com
CSRF_HMAC_KEY=<at-least-32-random-bytes>
PASSWORD_ARGON2_MEMORY_KIB=<benchmarked-value>
PASSWORD_ARGON2_TIME_COST=<benchmarked-value>
PASSWORD_ARGON2_PARALLELISM=<benchmarked-value>
```

原则：

- 所有密钥只存在 VPS 环境变量或受控密钥系统；
- 不创建任何 `VITE_*` 密钥；
- 本地、preview、production 使用不同密钥；
- 密钥轮换必须有明确流程；
- 不在日志中打印环境变量值。

前端最终删除：

```text
VITE_LOGTO_ENDPOINT
VITE_LOGTO_APP_ID
VITE_LOGTO_API_RESOURCE
```

后端最终删除：

```text
AUTH_ISSUER
AUTH_AUDIENCE
AUTH_JWKS_URL
LOGTO_ISSUER
LOGTO_AUDIENCE
LOGTO_JWKS_URL
```

## 13. Redis 使用边界

当前 preview Redis 使用 `appendonly no`，因此不把 Redis 作为唯一、持久的 Session 数据源。

第一阶段建议：

- PostgreSQL 是 Session source of truth；
- Redis 保存登录限流计数；
- Redis 保存短期失败次数和冷却状态；
- Redis 丢失最多导致限流状态重置，不导致持久账号或审计数据丢失。

未来如果把活跃 Session 放入 Redis，需要先明确：

- Redis 持久化策略；
- 容器 volume；
- Redis 重启时是否接受所有用户被登出；
- Session 撤销和 PostgreSQL 记录之间的一致性；
- 多 API 实例共享 Session 的方式。

## 14. 测试计划

### 14.1 密码测试

- 正确密码成功；
- 错误密码失败；
- 未知邮箱和错误密码返回完全相同的外部错误；
- 密码最小、最大长度；
- Unicode 规范化；
- blocklist；
- 旧 Argon2 参数登录后自动 rehash；
- 数据库中不存在明文密码。

### 14.2 Session 测试

- 登录创建 Cookie；
- Cookie 包含 `Secure`、`HttpOnly`、`SameSite` 和 `Path=/`；
- 数据库只保存 Token 哈希；
- 过期、撤销和伪造 Cookie 返回 401；
- suspended 用户返回 403；
- 登出后旧 Cookie 无效；
- 修改密码后其他 Session 失效；
- Session fixation 防护和 Token 旋转。

### 14.3 CSRF 与 CORS 测试

- 合法生产 Origin 成功；
- 未允许 Origin 失败；
- `Origin: null` 失败；
- 缺少或错误 CSRF Header 失败；
- 正确 CSRF Header 与 Cookie 成功；
- 通配符 CORS 不存在；
- Vercel 前端跨 Origin Cookie 请求成功。

### 14.4 限流测试

- 单 IP 高频失败登录触发 429；
- 同一邮箱从多个 IP 尝试触发账号维度冷却；
- 不同合法用户不会因为 Tunnel 本机地址共享而互相误伤；
- Redis 不可用时采用明确的 fail-safe 或降级策略；
- 管理员接口使用更严格策略。

### 14.5 邀请和重置测试

- 有效邀请只能使用一次；
- 过期、撤销、错误用途 Token 被拒绝；
- 并发使用同一 Token 只有一次成功；
- 密码重置后全部旧 Session 失效；
- 管理员无法查看用户密码；
- 已存在用户激活后保留原 `User.id` 和 Workspace 权限。

### 14.6 生产闭环测试

```text
Vercel 登录页
  → Cloudflare
  → FastAPI 登录
  → PostgreSQL Session
  → Set-Cookie
  → /api/v1/me
  → 聊天 SSE
  → 文档/知识库
  → 修改密码
  → 登出
  → 旧 Cookie 被拒绝
```

同时验证：

- 页面刷新后仍登录；
- 多标签页状态一致；
- Cookie 不可被前端 JavaScript 读取；
- API 响应不泄露认证内部信息；
- FastAPI 日志不出现密码或 Token；
- Cloudflare Tunnel 不影响真实客户端限流键；
- 回滚到双轨模式可以恢复访问。

## 15. 验收标准

只有全部满足后才可以删除 Logto：

- [ ] 所有有效员工已经设置本地密码；
- [ ] 每个迁移用户保持原 `User.id`；
- [ ] Workspace role 和 permission 未改变；
- [ ] Argon2id 参数经过生产容器基准测试；
- [ ] Session Cookie 安全属性测试通过；
- [ ] CSRF、CORS 和 Origin 测试通过；
- [ ] 登录与密码重置专用限流测试通过；
- [ ] 用户暂停会即时撤销全部 Session；
- [ ] 数据库和 Redis 故障行为明确；
- [ ] 认证日志无密码或 Token；
- [ ] Vercel → Cloudflare → FastAPI 生产闭环通过；
- [ ] 数据库备份和回滚演练通过；
- [ ] Logto 环境变量已从 Vercel 和 VPS 清除；
- [ ] Logto SDK、callback 和 bootstrap 代码已删除；
- [ ] 旧 Logto 账号数据已经按保留策略导出或删除。

## 16. 不在第一阶段实现的内容

以下能力不应阻塞本地密码认证第一阶段，但应为未来预留：

- WebAuthn / Passkey；
- TOTP MFA 和恢复码；
- 企业 SAML/OIDC SSO；
- 移动端 OAuth Client；
- 第三方应用授权；
- Personal Access Token；
- 独立自托管 OIDC Provider。

如果未来需要这些能力，应重新评估部署成熟的自托管身份服务，而不是继续扩大 FastAPI 业务服务中的自制认证协议。

## 17. 实施顺序摘要

```text
生产数据库预检与备份
        ↓
新增 PasswordCredential / AuthSession / AuthOneTimeToken
        ↓
实现密码、Session、CSRF、限流
        ↓
后端进入 Logto + Local 双轨模式
        ↓
前端改为 Cookie Session
        ↓
现有员工逐个激活本地密码
        ↓
切换 AUTH_MODE=local_session
        ↓
生产观察和回滚窗口
        ↓
删除 Logto 代码、依赖和环境变量
```

## 18. 参考标准

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [OAuth 2.0 Security Best Current Practice — RFC 9700](https://www.rfc-editor.org/info/rfc9700/)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)
