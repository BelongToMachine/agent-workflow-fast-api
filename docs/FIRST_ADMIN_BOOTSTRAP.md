# 首次管理员（Owner）添加手册

本文用于单工作区 MVP 的第一次授权。当前系统只有一个配置好的默认 workspace；首次管理员使用 `owner` 角色，后续可以在成员管理页面添加 `admin`、`editor`、`employee` 或 `viewer`。

## 什么时候使用

只有在默认 workspace 还没有 active owner 时使用本手册。该流程不会把“第一个登录的人”自动升级为管理员，也不会按 email 自动授予管理员权限。

整个链路是：

```text
用户用 Logto 登录一次
  → FastAPI bootstrap 创建 User + ExternalIdentity + 默认 viewer membership
  → 运维命令按 Logto subject 找到本地 User
  → 将该用户提升为默认 workspace 的 owner
  → AuditLog 记录本次运维授权
```

## 前置条件

- FastAPI 已配置可写的 `POSTGRES_URL`；
- `0005_auth_identity` 已执行，`ExternalIdentity`、`User.status` 和 nullable email 已存在；
- 默认 workspace 已存在，默认值为：

  ```text
  00000000-0000-0000-0000-000000000001
  ```

- 目标用户已经在 Logto 完成一次登录/注册，并能进入应用；
- 目标用户的本地 `User.status` 为 `active`；
- 目标 workspace 目前没有其他 active owner。

## 第一步：获取 Logto subject

命令需要的是已验证的 Logto `sub`，不是邮箱、密码、access token 或 refresh token。

推荐从 Logto Console 的 **User management** 打开目标用户，复制该用户的 **User ID**。Logto 的 User ID 就是业务 Token 中稳定的 `sub`。

如果已经知道本地 `User.id`，也可以在数据库只读查询对应 subject：

```sql
SELECT
    identity."provider",
    identity."subject",
    identity."userId",
    user_record."email",
    user_record."status"
FROM "ExternalIdentity" AS identity
JOIN "User" AS user_record
  ON user_record."id" = identity."userId"
WHERE identity."provider" = 'logto'
  AND identity."userId" = '<local-user-uuid>';
```

确认 `provider = logto`、用户资料和目标账号一致后，再继续。不要把完整 Token 粘贴到终端、工单或聊天中。

## 第二步：先做 preflight

在 `asianode-fastapi` 目录执行：

```bash
uv run python -m app.db.grant_workspace_member \
  --provider logto \
  --subject '<logto-sub>' \
  --workspace-id '00000000-0000-0000-0000-000000000001'
```

不带 `--yes` 时只会检查并显示目标用户、workspace 和将要授予的角色；不会写入数据库。正常情况下命令会以退出码 `2` 结束，这是“preflight 完成、等待确认”的含义。

如果提示没有本地映射，先让目标用户重新完成一次 Logto 登录，并确认 `/api/v1/auth/bootstrap` 成功，然后重新执行 preflight。

## 第三步：确认后授予 owner

确认终端输出的用户和 workspace 都正确后，执行：

```bash
uv run python -m app.db.grant_workspace_member \
  --provider logto \
  --subject '<logto-sub>' \
  --workspace-id '00000000-0000-0000-0000-000000000001' \
  --yes
```

也可以使用 Makefile 快捷命令：

```bash
make grant-first-owner \
  SUBJECT='<logto-sub>' \
  WORKSPACE_ID='00000000-0000-0000-0000-000000000001'
```

该命令具有以下保护：

- 只按 `ExternalIdentity(provider, subject)` 定位用户；
- 目标用户不存在、未 bootstrap、被停用或是匿名用户时拒绝执行；
- 已有其他 active owner 时拒绝执行，避免误替换已有 owner；
- 目标用户已经是 active owner 时幂等返回，不重复写入；
- 如果目标用户已有默认 viewer membership，则只升级该 membership，不创建重复 membership；
- 清除该 membership 的旧 permission override，让 owner 使用完整 owner 权限；
- 写入 `AuditLog.action = workspace.member_bootstrapped`，`actorUserId` 为空表示这是受控运维命令，目标用户和 workspace 仍会记录。

## 第四步：验证

1. 让目标用户刷新应用，必要时退出后重新登录；
2. 调用 `GET /api/v1/me`，确认：

   ```json
   {
     "accessState": "ready",
     "memberships": [
       {
         "role": "owner",
         "status": "active"
       }
     ]
   }
   ```

3. 打开前端 **Settings → Workspace permissions**；
4. 确认可以看到成员列表和“Add a registered user”；
5. 确认数据库中有对应审计记录：

   ```sql
   SELECT "action", "actorUserId", "targetUserId", "workspaceId", "metadata"
   FROM "AuditLog"
   WHERE "action" = 'workspace.member_bootstrapped'
   ORDER BY "createdAt" DESC
   LIMIT 10;
   ```

## 添加后续管理员

后续用户不需要再次执行首个 owner 命令：

1. 用户先用 Logto 登录一次，完成本地 bootstrap；
2. owner 打开成员管理页面；
3. 在 **Add a registered user** 中选择该用户；
4. 选择 `Administrator`，点击 **Add member**；
5. 后端会检查 `members.manage`、目标用户状态、重复 membership 和 owner 保护，并写入 `workspace.member_added` 审计日志。

管理员可以添加普通成员、修改角色和权限、停用或恢复成员。只有 owner 能授予/修改 owner，任何管理员都不能停用自己或最后一个 active owner。

## 常见问题

### 用户已经登录，但候选列表没有显示

候选列表只显示：已完成 Logto bootstrap、`User.status = active`、非匿名、且当前 workspace 没有任何 membership 的用户。如果用户已经是 suspended membership，请使用恢复操作，不会重复出现在候选列表。

### 命令提示已有 active owner

这是保护机制。不要继续重复执行首个 owner 命令；让现有 owner 在前端成员管理页面添加或恢复其他成员。

### 页面仍显示 Viewer

刷新 `/me` 或退出后重新登录，确认请求使用的是最新 access token，并检查 `WorkspaceMember.status = active`。前端的 role 只是显示和菜单控制，最终授权以 FastAPI 查询结果为准。

### 需要更换首个 owner

不要直接改 SQL。由当前 owner 在成员管理页面先添加/提升新的 owner，再处理旧 owner；系统会阻止降级或停用最后一个 active owner。
