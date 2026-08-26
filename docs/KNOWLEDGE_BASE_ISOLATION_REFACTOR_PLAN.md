# KnowledgeBase 隔离重构执行计划

> 状态：`ready_for_implementation`
>
> 编写日期：2026-08-24
>
> 适用项目：`asianode-fastapi`、`asianodeagent-front`

## 1. 目标与边界

当前公司规模较小，近期不建设前端多 workspace 切换能力。系统继续保留一个默认 workspace，
将它作为公司级租户边界；本次把 `KnowledgeBase` 建设为公司内部知识数据的实际隔离边界。

目标模型：

```text
Workspace（公司，目前只有一个）
└── KnowledgeBase（公共产品、供应商、采购成本、客户资料等）
    ├── Access policy: workspace | restricted
    ├── KnowledgeBaseGrant: user | role → read | manage
    ├── KnowledgeFile
    └── KnowledgeChunk
```

本次目标：

- 保留 `Workspace` 字段、外键和后端校验，为未来多租户保留边界；
- 暂不实现 workspace selector、active workspace 持久化和切换缓存；
- 支持知识库显式设置为公司共享或受限访问；
- 所有列表、直接访问、产品/内容检索、向量搜索和 Agent tool 使用同一套知识库授权；
- 前端不再要求管理员手填 user UUID 或任意 role 字符串；
- migration 可预检、可重复执行，并在打开 feature flag 前完成数据一致性验证。

不在本次范围：

- 多 workspace UI 和用户自助创建 workspace；
- Logto RBAC 替代本地 `WorkspaceMember` 权限；
- 数据库 PostgreSQL RLS；
- 部门、团队、用户组实体；
- 改变 `employee` 当前禁止 `knowledge.read`/`knowledge.manage` 的规则；
- 删除 legacy `KnowledgeSource` 表。

## 2. 真实现状盘点

### 2.1 当前数据库只读预检

2026-08-24 使用现有 FastAPI 配置进行只读检查，未执行 migration，结果如下：

| 项目 | 当前状态 |
|---|---|
| `Workspace` | 1 行 |
| `KnowledgeSource` | 2 行，均为 `ready`、`sourceType=legacy` |
| KnowledgeSource 覆盖 workspace | 1 个，无空 `workspaceId` |
| `RealProductResearch` | 47 行，无缺失或悬空 `sourceId` |
| `ContentRecord` | 46 行，无缺失或悬空 `sourceId` |
| `KnowledgeBase` | 不存在 |
| `KnowledgeBaseGrant` | 不存在 |
| `KnowledgeFile` | 不存在 |
| `KnowledgeChunk` | 不存在 |
| `0001`–`0004` knowledge migrations | 全部 pending |
| `0005_auth_identity` | applied |

因此当前不能直接启用：

```env
KNOWLEDGE_BASE_ENTITY_ENABLED=1
KNOWLEDGE_GRANTS_ENABLED=1
KNOWLEDGE_INGESTION_ENABLED=1
KNOWLEDGE_EMBEDDINGS_ENABLED=1
```

现有两个 `KnowledgeSource` 必须先以相同 UUID 回填到 `KnowledgeBase`，以保持
`RealProductResearch.sourceId` 和 `ContentRecord.sourceId` 的关联不变。

### 2.2 后端已经具备的能力

- `app/core/knowledge_access.py` 已支持 user/role grant、`read`/`manage` 和 owner/admin bypass；
- `/knowledge-bases`、`/knowledge-sources`、`/products`、`/content/search` 已接入授权 ID 过滤；
- 知识库文件和向量搜索按 `workspaceId + knowledgeBaseId` 检查权限；
- Agent tools 通过现有知识库、产品和内容路由间接复用授权过滤；
- `KnowledgeBaseGrant` 管理 API 已支持查询、upsert、删除和 `AuditLog`；
- `0004_knowledge_bases.sql` 已设计用相同 UUID 从 `KnowledgeSource` 回填独立实体；
- migration status 和 knowledge integrity 已有只读检查框架。

### 2.3 后端实际缺口

1. `KNOWLEDGE_GRANTS_ENABLED=false` 时，`get_authorized_source_ids()` 返回 `None`，含义是不过滤。
   该兼容模式不能作为正式隔离方案。
2. 当前授权语义依赖“是否存在 grant”推断是否受限，没有显式 `accessMode`。
3. 普通内部角色对“没有 grant 的知识库”存在默认放行路径，无法清楚表达严格隔离。
4. `PATCH /knowledge-bases/{id}` 只检查 workspace 级 `knowledge.manage`，没有检查该知识库的
   `manage` grant；删除接口已经使用知识库级检查，二者不一致。
5. grant API 只验证 `subjectType` 和字符串格式，不验证：
   - user 是否存在；
   - user 是否是当前 workspace 的 active member；
   - role 是否属于当前角色目录；
   - 被授权主体是否具备相应 workspace 权限上限。
6. `KnowledgeBaseGrant.workspaceId` 和 `knowledgeBaseId` 分别有外键，但数据库没有组合外键阻止
   “grant workspace 与知识库 workspace 不一致”。文件和 chunk 也存在同类风险。
7. Agent tool 直接调用 FastAPI route function，领域逻辑和 HTTP 层耦合，测试与错误转换较复杂。
8. 旧 `KnowledgeSource` 和新 `KnowledgeBase` 由 feature flag 双轨运行，正式切换顺序尚未固化。

### 2.4 前端已经具备的能力

- 已有知识库创建、重命名、删除和 grant 管理页面；
- 已有知识库文件列表、上传、删除和 processing 状态；
- `requestBackend` 会附带 Bearer token 和固定 workspace query；
- 路由和 sidebar 已按 workspace permission 隐藏入口；
- 后端 `401/403/409` 可以通过统一请求错误进入 UI。

### 2.5 前端实际缺口

1. `/settings/knowledge-bases` 按 `knowledge.manage` 放行，但后端 grant API 要求
   `members.manage`，前后端权限合同冲突。
2. grant 表单要求手工输入 `user UUID` 或任意 role 字符串，容易产生无效和悬空授权。
3. UI 没有 `workspace/shared` 与 `restricted` 状态，当前文案却把所有知识库描述成 restricted。
4. 页面使用 `useEffect + useState + requestBackend` 手工维护服务器状态，没有使用 React Query
   的 query key、失效和请求取消。
5. grant、知识库生命周期和文件页面各自维护知识库列表，mutation 后容易出现跨页面陈旧缓存。
6. query key 尚未形成 `identity + workspaceId + knowledgeBaseId + resource` 的统一结构。
7. 前端只能做入口隐藏和按钮禁用，不能承担最终授权；所有安全判断仍必须由 FastAPI 完成。

## 3. 架构决策

### 3.1 Workspace 保留但不暴露切换

- 继续使用默认 workspace `00000000-0000-0000-0000-000000000001`；
- 前端暂不增加 workspace selector；
- 所有知识库表继续保留 `workspaceId`；
- FastAPI 仍先验证 `WorkspaceMember`，再验证 KnowledgeBase policy；
- 不把 workspace ID、role 或 permission 当作前端可信输入。

### 3.2 KnowledgeBase 增加显式访问模式

新增字段：

```text
KnowledgeBase.accessMode: workspace | restricted
```

语义：

| accessMode | 访问规则 |
|---|---|
| `workspace` | 拥有 workspace `knowledge.read/manage` 即可按能力访问 |
| `restricted` | 除 owner/admin 外，必须同时匹配 `KnowledgeBaseGrant` |

默认策略：

- 从现有 `KnowledgeSource` 迁移的两个知识库回填为 `workspace`，避免上线时意外锁死现有业务；
- UI 创建新知识库时显式提交 `restricted`，符合后续隔离需求；
- owner/admin 是恢复通道，可查看和管理所有知识库；
- `manage` 隐含 `read`；
- grant 只能缩小知识范围，不能突破 workspace permission 上限。

示例：

```text
viewer + knowledge.read + KB read grant       → 可读 restricted KB
editor + knowledge.manage + KB manage grant   → 可读写 restricted KB
editor + knowledge.manage + 只有 KB read grant → 只能读
employee + KB read grant                      → 仍不可读
```

最后一行是有意设计：当前 `employee` 在前后端角色目录中都被禁止 knowledge 权限。
如果未来要允许 employee 访问指定知识库，应单独修改角色产品定义，不能让 KB grant 隐式提权。

### 3.3 管理权限与内容权限分开

- `members.manage`：修改知识库的访问模式和 grant；
- `knowledge.manage` + KB `manage`：重命名、上传文件、删除文件、删除知识库；
- `knowledge.read` + KB `read/manage`：查看知识库、文件状态、搜索内容；
- owner/admin 保留全局恢复能力。

这会修正当前“前端允许 editor 打开 grant 页面，但后端拒绝”的不一致。

### 3.4 未授权资源使用 404 隐藏存在性

- workspace membership 或 workspace capability 缺失：返回结构化 `403`；
- 知识库不存在或当前用户无权知道其存在：统一返回结构化 `404`；
- feature/migration 未就绪：返回结构化 `409` 或启动失败，不得回退为全量放行；
- 数据库/provider 故障：返回结构化 `503`。

### 3.5 HTTP 层与知识领域服务分离

目标调用关系：

```text
FastAPI route ─┐
               ├── knowledge domain service ── access policy ── repository/SQL
Agent tool ────┘
```

Route 只负责 HTTP 参数、身份 dependency 和 response model。Agent tool 不再直接调用 route
function，而是调用同一领域 service，避免依赖 FastAPI `Depends` 默认值或解析 `JSONResponse`。

## 4. 目标数据库 Schema

### 4.1 新 migration

新增：

```text
migrations/0006_knowledge_base_access_policy.sql
```

不得修改已经发布的 `0001`–`0005` 语义；即使当前数据库尚未应用 `0001`–`0004`，新能力仍通过
向前 migration 表达，兼容其他可能已应用旧 migration 的环境。

### 4.2 KnowledgeBase

新增：

```sql
"accessMode" varchar(16) NOT NULL DEFAULT 'workspace'
```

约束：

```text
CHECK accessMode IN ('workspace', 'restricted')
UNIQUE (id, workspaceId)
```

索引：

```text
(workspaceId, status, accessMode)
(workspaceId, displayName)
```

现有数据回填：

```text
所有由 KnowledgeSource 回填的 KnowledgeBase → accessMode='workspace'
```

数据库 default 保留为 `workspace` 是为了 migration/旧代码兼容；新 API 的 Pydantic request default
使用 `restricted`。这样旧代码不会因为缺字段立刻锁死，新代码创建的知识库则默认隔离。

### 4.3 KnowledgeBaseGrant

保留现有字段：

```text
id
workspaceId
knowledgeBaseId
subjectType: user | role
subjectId: local User UUID string | workspace role
accessLevel: read | manage
createdAt
updatedAt
```

增加或强化：

- 唯一约束：`(knowledgeBaseId, subjectType, subjectId)`；
- 查询索引：`(workspaceId, subjectType, subjectId, accessLevel, knowledgeBaseId)`；
- 组合外键：`(knowledgeBaseId, workspaceId) → KnowledgeBase(id, workspaceId)`；
- user/role 的存在性由 API 在事务内校验，避免 polymorphic `subjectId` 无法直接使用单一数据库 FK。

### 4.4 KnowledgeFile 与 KnowledgeChunk

增加组合一致性约束：

```text
KnowledgeFile(knowledgeBaseId, workspaceId)
  → KnowledgeBase(id, workspaceId)

KnowledgeChunk(knowledgeBaseId, workspaceId)
  → KnowledgeBase(id, workspaceId)

KnowledgeChunk(fileId, knowledgeBaseId, workspaceId)
  → KnowledgeFile(id, knowledgeBaseId, workspaceId)
```

执行组合外键前必须先运行现有 `knowledge_integrity`，并为父表增加相应 unique constraint。

### 4.5 Legacy KnowledgeSource

- 本阶段不删除；
- `0004` 继续以相同 UUID 回填到 `KnowledgeBase`；
- 产品和内容记录已有 `sourceId`，切换后可用相同 ID join `KnowledgeBase`；
- 新业务写入只面向 `KnowledgeBase`、`KnowledgeFile`、`KnowledgeChunk`；
- 待真实流量稳定后，再单独规划 `KnowledgeSource` 下线，不与本次授权重构混合。

## 5. 后端实施计划

### Phase B0：固定真实基线

- [x] 只读确认当前数据库只有一个 workspace；
- [x] 确认 2 个 legacy KnowledgeSource 均为 ready；
- [x] 确认 47 个产品记录和 46 个内容记录没有缺失/悬空 sourceId；
- [x] 确认 knowledge migrations `0001`–`0004` 未应用；
- [x] 确认 auth migration `0005` 已应用；
- [ ] 在执行远程数据库 migration 前生成可恢复备份或 Supabase snapshot；
- [ ] 记录 migration 前表行数和关键约束快照。

### Phase B1：Schema 与 migration runner

- [ ] 创建 `0006_knowledge_base_access_policy.sql`；
- [ ] 将 `0006` 加入 `app/db/migrate_knowledge.py` 的有序 migration 列表；
- [ ] 扩展 `app/db/migration_status.py` 检查 accessMode、索引和组合外键；
- [ ] 扩展 `app/db/knowledge_integrity.py` 检查 accessMode 和三组 workspace 一致性；
- [ ] 增加 migration 幂等性、状态识别和回填测试；
- [ ] 更新 `.env.example`、README 和 API contract 的启用顺序。

### Phase B2：统一访问策略

重构 `app/core/knowledge_access.py`：

- [ ] 移除 `RESTRICTED_KNOWLEDGE_ROLES + 无 grant 默认放行` 的隐式策略；
- [ ] 读取 `KnowledgeBase.accessMode`；
- [ ] 实现统一的 `list_authorized_knowledge_base_ids()`；
- [ ] 实现统一的 `resolve_knowledge_base_access()`，返回 `none/read/manage`；
- [ ] 实现 `require_knowledge_base_access(read|manage)`；
- [ ] 保留 workspace permission 作为能力上限；
- [ ] owner/admin bypass；
- [ ] 未授权知识库统一映射为 404；
- [ ] migration/表未就绪时 fail closed，不返回 `None` 表示全量访问。

建议领域结果：

```python
class EffectiveKnowledgeAccess(str, Enum):
    none = "none"
    read = "read"
    manage = "manage"
```

### Phase B3：知识库生命周期 API

- [ ] `KnowledgeBaseSummary` 增加 `accessMode` 和当前用户 `effectiveAccess`；
- [ ] 创建请求增加 `accessMode`，API 默认 `restricted`；
- [ ] restricted KB 由非 owner/admin 创建时，在同一事务内为创建者写入 user/manage grant；
- [ ] `PATCH /knowledge-bases/{id}` 改为 KB `manage` 检查；
- [ ] 文件 list/upload/delete 继续分别使用 KB read/manage；
- [ ] 知识库删除继续级联 grant/file/chunk，并保持对象存储 best-effort 清理；
- [ ] 所有 mutation 写 `AuditLog`，metadata 只记录 ID、模式和动作，不记录知识内容。

### Phase B4：访问策略管理 API

- [ ] grant 管理继续要求 `members.manage`；
- [ ] 新增访问模式更新 API，例如：

```http
PATCH /api/v1/admin/knowledge-bases/{knowledge_base_id}/access-policy
```

```json
{
  "accessMode": "restricted"
}
```

- [ ] user grant：校验本地 User 存在且是当前 workspace active member；
- [ ] role grant：只接受 `owner/admin/editor/employee/viewer`；
- [ ] 检查 grant 不突破 workspace permission ceiling；
- [ ] grant upsert/delete 和 accessMode 切换写审计日志；
- [ ] 列表响应返回 member 的 name/email，前端无需展示 UUID；
- [ ] API 返回统一 `knowledge:*` 结构化错误码。

建议错误码：

```text
knowledge:not_found
knowledge:access_denied
knowledge:manage_required
knowledge:invalid_subject
knowledge:inactive_member
knowledge:grant_exceeds_workspace_permission
knowledge:migration_required
knowledge:feature_disabled
```

### Phase B5：检索和 Agent 全链路

- [ ] `/knowledge-bases` 只返回授权知识库；
- [ ] `/knowledge-sources` 只返回授权知识库；
- [ ] `/products` 的 SQL 始终包含授权 knowledge base IDs；
- [ ] `/content/search` 的 SQL 始终包含授权 knowledge base IDs；
- [ ] source name 查询在 SQL 内完成授权过滤，不依赖查询后 Python 二次过滤；
- [ ] vector search 检查 KB read；
- [ ] 文件访问检查 KB read/manage；
- [ ] 把知识库、产品、内容查询提取到领域 service；
- [ ] Agent tools 调用领域 service，不直接调用 route functions；
- [ ] tool 输入中的 knowledgeBaseId 永远重新授权，不信任模型先前返回的 ID；
- [ ] 空授权列表必须返回空结果，不能退化为 workspace 全量查询。

### Phase B6：Feature flag 收敛

- [ ] `KNOWLEDGE_BASE_ENTITY_ENABLED` 仅用于 legacy → 新实体切换；
- [ ] `KNOWLEDGE_GRANTS_ENABLED` 仅用于 migration 前灰度，正式隔离上线后不得通过关闭它来回滚；
- [ ] enforce 模式下缺表或缺列应在启动检查中失败或让知识 API 返回 503/409；
- [ ] 禁止“授权系统故障时默认放行”；
- [ ] 稳定后规划删除双轨 query renderer 和 legacy flag。

## 6. 前端实施计划

### Phase F1：类型和查询层

新增统一类型：

```ts
type KnowledgeBaseAccessMode = "workspace" | "restricted";
type KnowledgeBaseAccessLevel = "read" | "manage";

type KnowledgeBaseSummary = {
  knowledgeBaseId: string;
  displayName: string;
  accessMode: KnowledgeBaseAccessMode;
  effectiveAccess: KnowledgeBaseAccessLevel;
};
```

- [ ] 把知识库类型从页面内部移到 `src/lib/knowledge/`；
- [ ] 为知识库、文件、grant 建立 React Query hooks；
- [ ] query key 使用 `identity + workspaceId + knowledgeBaseId + resource`；
- [ ] mutation 成功后精确 invalidation；
- [ ] 页面卸载或切换知识库时取消旧请求；
- [ ] 不把 role、grant 或 effectiveAccess 写入 localStorage。

建议 query keys：

```text
[backend, user, userId, workspace, workspaceId, knowledge-bases]
[backend, user, userId, workspace, workspaceId, knowledge-base, kbId, files]
[backend, user, userId, workspace, workspaceId, knowledge-base, kbId, grants]
[backend, user, userId, workspace, workspaceId, members]
```

虽然当前只有一个 workspace，key 仍保留 workspaceId，避免未来切换能力再次重构缓存边界。

### Phase F2：路由权限合同

- [ ] `Knowledge access`/grant 页面入口改为 `members.manage`；
- [ ] `Knowledge files` 页面入口保留 `knowledge.manage`；
- [ ] 后端返回 403/404 时页面展示明确的权限或资源不可用状态；
- [ ] 按钮禁用只是 UX，所有请求仍由后端再次校验；
- [ ] 修正文案，不再宣称所有知识库都是 restricted。

### Phase F3：知识库管理体验

- [ ] 知识库列表展示 `Company shared` 或 `Restricted` badge；
- [ ] 创建知识库默认选择 `Restricted`，允许管理员显式改为 company shared；
- [ ] accessMode 切换增加确认说明；
- [ ] restricted 且没有显式 grant 时提示“仅 owner/admin 可访问”；
- [ ] `effectiveAccess=read` 时隐藏/禁用 rename、upload、delete；
- [ ] `effectiveAccess=manage` 时开放内容管理；
- [ ] 删除知识库继续使用二次确认并说明 grant/file/chunk 会被删除。

### Phase F4：授权主体选择器

- [ ] 删除 raw user UUID 输入框；
- [ ] 从成员 API 加载 active members，以 name/email 展示、local user UUID 提交；
- [ ] role 使用固定选项，不接受自由文本；
- [ ] 不展示因 workspace permission ceiling 永远无法生效的授权选项；
- [ ] grant 列表显示用户名称、邮箱、角色和 read/manage；
- [ ] member 被 suspended 或移除后显示 stale grant，并允许管理员清理；
- [ ] 所有成功/失败 mutation 使用统一 toast 和结构化错误文案。

### Phase F5：页面结构收敛

建议将当前两个独立设置页收敛为一个知识库详情页：

```text
Knowledge bases
├── Overview（名称、模式、状态）
├── Files（上传、处理状态、删除）
└── Access（仅 members.manage 可见）
```

- [ ] 保留现有 URL redirect，避免书签失效；
- [ ] 共用同一个 selected knowledge base 和 React Query cache；
- [ ] 文件 processing 状态支持手动刷新，后续可增加短期 polling；
- [ ] 非管理员看不到 Access tab；
- [ ] 没有授权知识库时显示业务化空状态，不显示技术错误。

## 7. Migration 与发布顺序

### 7.1 Preview 数据库

严格按顺序执行：

1. [ ] 生成 preview 数据库备份或 snapshot；
2. [ ] 记录现有 Workspace、KnowledgeSource、产品、内容行数；
3. [ ] 先部署兼容旧 schema、但识别新 schema 的后端版本；
4. [ ] 执行 `0001`–`0004` 和新增 `0006`；
5. [ ] 运行 migration status；
6. [ ] 运行 knowledge integrity；
7. [ ] 核对 `KnowledgeBase` 仍是 2 行、UUID 与 KnowledgeSource 相同；
8. [ ] 核对产品 47 行、内容 46 行仍可通过 sourceId 查询；
9. [ ] 设置 `KNOWLEDGE_BASE_ENTITY_ENABLED=1`；
10. [ ] 保持现有两个知识库为 `workspace`，验证行为与切换前一致；
11. [ ] 设置 `KNOWLEDGE_GRANTS_ENABLED=1`/enforce；
12. [ ] 通过 UI 将需要隔离的知识库改为 `restricted` 并配置 grant；
13. [ ] 使用 admin/editor/viewer/employee 账户执行验收矩阵；
14. [ ] 观察 API 403/404、空检索和 Agent tool 日志；
15. [ ] 确认无数据泄露后再准备 production。

当前 `app/db/migrate_knowledge.py` 会把知识 migration 放在一个事务中执行；新增 `0006` 后继续保持
all-or-nothing。远程数据库必须通过正式部署 migration 流程或明确审核后的 `--allow-remote`，不把本地
runner 当成无审查的生产发布工具。

### 7.2 Production

- [ ] 使用与 preview 相同的数据库 preflight；
- [ ] schema 先行，feature flag 后开；
- [ ] 先迁移并保持 `accessMode=workspace`，确认旧功能无回归；
- [ ] 再启用 enforce；
- [ ] 最后逐个知识库切换 restricted；
- [ ] 切换 restricted 前确认至少有 owner/admin 恢复账户；
- [ ] 记录每个知识库的业务 owner 和初始授权名单。

### 7.3 回滚原则

- migration 只新增列、表、索引和约束，不删除 `KnowledgeSource`；
- feature 切换前可以回退应用读取 legacy `KnowledgeSource`；
- 一旦 restricted 知识库承载敏感数据，不允许通过关闭 grant enforcement 回滚，因为这会重新开放数据；
- 正式上线前必须保留一个“兼容新 schema 且继续 enforce”的应用版本作为回滚版本；
- 如果新 UI 故障，可回滚前端，后端授权仍必须保持；
- 对象存储删除不可通过数据库 rollback 自动恢复，删除流程继续使用二次确认和审计。

## 8. 测试矩阵

### 8.1 Schema 与 migration

- [ ] 空数据库按顺序执行 `0001`–`0006` 成功；
- [ ] 当前 legacy 数据库执行后，2 个 KnowledgeBase ID 与 KnowledgeSource 一致；
- [ ] migration 重复运行不破坏数据；
- [ ] workspace/knowledgeBase 不匹配的 grant/file/chunk 被组合外键拒绝；
- [ ] migration status 能识别缺列、缺索引、缺约束；
- [ ] integrity 检查结果为零异常。

### 8.2 授权单元测试

- [ ] shared + `knowledge.read` → read；
- [ ] shared + `knowledge.manage` → manage；
- [ ] restricted + 无 grant → 404；
- [ ] restricted + user/read → read；
- [ ] restricted + user/manage → manage；
- [ ] restricted + role/read → read；
- [ ] manage grant 隐含 read；
- [ ] read grant 不能 rename/upload/delete；
- [ ] owner/admin 可恢复所有 KB；
- [ ] employee 即使有 grant 也不能突破 workspace ceiling；
- [ ] suspended/non-member user grant 创建失败；
- [ ] 未知 role grant 创建失败；
- [ ] 空 authorized IDs 返回空结果，不返回全量。

### 8.3 API 集成测试

- [ ] 知识库列表不泄露未授权名称；
- [ ] 直接猜 knowledgeBaseId 返回 404；
- [ ] 文件列表、上传、删除分别执行 read/manage；
- [ ] vector search 不返回其他 KB chunk；
- [ ] products/content 都按授权 source IDs 过滤；
- [ ] sourceFileNames 不能绕过授权；
- [ ] accessMode 和 grant mutation 写 AuditLog；
- [ ] grant 撤销后下一个请求立即生效，不依赖 token 刷新。

### 8.4 Agent 测试

- [ ] listKnowledgeBasesTool 只返回授权 KB；
- [ ] 模型传入未授权 KB ID 时 tool 返回安全错误；
- [ ] searchProductsTool 不返回未授权 source 的产品；
- [ ] searchContentTool 不返回未授权 source 的内容；
- [ ] searchKnowledgeBaseTool 不返回未授权 chunk；
- [ ] tool 错误中不包含隐藏知识库名称或内容。

### 8.5 前端验收

- [ ] admin 可以切换 shared/restricted 并管理 grants；
- [ ] editor 只管理拥有 manage access 的 KB；
- [ ] viewer 只能读取授权 KB；
- [ ] employee 看不到知识库入口和知识结果；
- [ ] 用户选择器显示 name/email，不要求输入 UUID；
- [ ] grant 更新后列表、文件页和搜索缓存正确失效；
- [ ] 401、403、404、409、503 都有可理解的 UI；
- [ ] `bun run lint` 通过；
- [ ] `bun run build` 通过。

## 9. 完成标准

以下条件全部满足后，KnowledgeBase 隔离才算完成：

- [ ] 数据库中存在独立 `KnowledgeBase` 和显式 `accessMode`；
- [ ] 当前两个 legacy source 无损迁移，产品与内容数据数量一致；
- [ ] restricted KB 必须通过 user/role grant 才能访问；
- [ ] 所有 HTTP、检索和 Agent 路径共用同一授权服务；
- [ ] 后端拒绝逻辑不依赖前端隐藏按钮；
- [ ] grant subject 不再接受未经校验的任意值；
- [ ] 前端权限合同与后端一致；
- [ ] migration 和 integrity 检查可在 preview/production 发布流程中重复执行；
- [ ] 权限撤销无需重新登录或等待 token 过期即可生效；
- [ ] rollback 不会把 restricted 数据重新开放。

## 10. 推荐实施批次

为降低一次性改动风险，代码提交建议分为以下批次：

1. `Add explicit knowledge base access policy schema`
   - `0006` migration、status、integrity、migration tests。
2. `Enforce knowledge base access policies`
   - access service、生命周期 API、grant subject 校验、结构化错误。
3. `Apply knowledge isolation to search and agent tools`
   - products/content/vector/file/Agent 统一 service 和回归测试。
4. `Build knowledge base access management UI`
   - React Query hooks、access mode、成员选择器、路由权限修正。
5. `Document and verify knowledge isolation rollout`
   - API contract、README、preview migration 结果和 E2E 验收记录。

