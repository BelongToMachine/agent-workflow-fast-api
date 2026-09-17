# 业务数据表前端展示页计划

> 基于 [`BUSINESS_DATA_TABLES.md`](./BUSINESS_DATA_TABLES.md) 编写。本文用于前端页面和后端列表接口的实现评审。
>
> 调研日期：2026-09-17。方案以 React + TypeScript 前端为例；如果前端项目使用其他框架，页面与 API 设计仍可复用，表格组件需重新评估。

## 1. 目标

提供一个统一的只读业务数据浏览页，让有权限的用户按表查看业务数据，并能在完整数据集范围内检索、筛选、排序和自定义列布局。

页面需要覆盖：

- 产品资料及其报价、运营、文档关联数据；
- 内容营销记录；
- 知识库、文件和解析片段；
- 工作区与知识库权限辅助数据；
- 聊天会话及消息记录；
- 文档提到的旧版 `KnowledgeSource`（仅在后端确认表存在且授权后显示，默认折叠并标记为 Legacy）。

首期只读，不在此页编辑或删除记录，也不提供任意 SQL 查询。表名通过固定注册表解析，前端不能自行传数据库表名。

## 2. 表格库方案

### 推荐：AG Grid Community + Infinite Row Model

建议采用 `ag-grid-community`、`ag-grid-react` 的 Community 功能。AG Grid 的 Infinite Row Model 按 `startRow` / `endRow` 请求数据块，内置区块缓存和虚拟渲染；滚动位置触发取数。排序和筛选状态会随 datasource 请求传给应用，因此后端可对完整结果集排序、筛选，而不是只处理浏览器当前已加载的数据。[Infinite Row Model 文档](https://www.ag-grid.com/react-data-grid/infinite-scrolling/) [行模型说明](https://www.ag-grid.com/react-data-grid/row-models/)

选择它的原因：

1. **虚拟滚动和无限加载是表格本身的能力。** 前端将滚动请求映射为后端的 offset/limit 区块查询，并配置缓存大小即可。
2. **适合动态列。** 不同业务表可从字段元数据生成列定义；表格支持列排序、筛选、移动、调整宽度和保存/恢复列状态。[列状态文档](https://www.ag-grid.com/react-data-grid/column-state/)
3. **支持类型化过滤。** Community 提供文本、数字和日期过滤器；状态、平台等枚举字段可用自定义下拉过滤器。AG Grid 会提供过滤模型，但完整数据集上的实际过滤必须由后端完成。[过滤文档](https://www.ag-grid.com/react-data-grid/filtering/) [Infinite Row Model 的排序与筛选说明](https://www.ag-grid.com/react-data-grid/infinite-scrolling/)
4. **首期无需购买 Enterprise。** 官方说明 Infinite Row Model 不要求 Enterprise；不过高级筛选、Set Filter、服务端分组/聚合和 Excel 导出等能力可能需要 Enterprise 或自定义实现。[AG Grid 定价与许可](https://www.ag-grid.com/license-pricing/)

### Community 与 Enterprise 的功能边界

首期使用 `ag-grid-community` 可免费上线，包含基础排序、文本/数字/日期筛选、行列虚拟化、Infinite Row Model，以及基础列移动、调整宽度和固定列。以下常见增强功能属于 Enterprise，或需要自行实现：

- Enterprise：Server-Side Row Model、Set Filter、Multi Filter、Advanced Filter、分组/聚合/透视、Excel 导出、内置 Columns Tool Panel / Column Chooser、Master/Detail、集成图表；官方功能对比也将多列排序列在 Enterprise。
- 首期可用自定义 UI 补足：枚举值筛选、个人列设置抽屉、命名视图；排序先限定单列。若必须支持多列排序，购买 Enterprise，或自行做排序条件面板并将有序排序规则交给后端。
- Enterprise 官网当前标价为每位开发者 999 美元起；采购时还需核对部署许可和更新期限。[官方许可与价格](https://www.ag-grid.com/license-pricing/) [Community / Enterprise 对比](https://www.ag-grid.com/vue-data-grid/community-vs-enterprise/)

### 候选方案对比

| 方案 | 无限滚动与虚拟化 | 搜索、过滤、排序 | 列配置 | 取舍 |
| --- | --- | --- | --- | --- |
| **AG Grid Community（推荐）** | Infinite Row Model 内置分块加载；内置虚拟渲染 | 常用交互和状态由 Grid 管理；服务端过滤/排序仍需后端实现 | 可通过 Grid State / Column State 保存宽度、顺序、可见性、固定列和排序 | 功能完整、落地快；高级 Set Filter、服务端分组等需确认 Enterprise 许可或自行实现 |
| TanStack Table + TanStack Virtual + TanStack Query | 虚拟化、无限加载需组合实现 | headless 状态和 server-side/manual 模式灵活；请求层可用 `useInfiniteQuery` | 完全自定义 | MIT、框架适配面广，但筛选面板、列设置、缓存与滚动行为需要前端投入更多实现。[虚拟化指南](https://tanstack.com/table/latest/docs/framework/react/guide/virtualization) [服务端模式指南](https://tanstack.com/table/latest/docs/guide/client-side-vs-server-side) [无限查询指南](https://tanstack.com/query/latest/docs/framework/react/guides/infinite-queries) |
| MUI X Data Grid Pro | 支持 server-side lazy loading / infinite loading | Data Source 可串起服务端过滤、排序和取数 | 组件集成度高 | 如果项目已全面使用 MUI，可作为备选；lazy loading 属于 Pro 功能，需购买商业许可。[Lazy loading 文档](https://mui.com/x/react-data-grid/server-side-data/lazy-loading/) [许可说明](https://mui.com/x/introduction/licensing/) |

AG Grid 的默认外观不必决定整个页面设计：通过项目现有设计系统提供页面工具栏、表选择器、列设置抽屉和详情面板；Grid 用于承载高性能表格交互。

## 3. 页面信息架构

建议路由：`/admin/data-tables`。只有具备管理或数据浏览权限的用户可访问。

### 页面区域

1. **标题和权限提示**：业务数据表；展示当前工作区名称。工作区从已登录会话取得，用户不能通过 URL 参数切换到未授权工作区。
2. **表选择器**：按下方分类展示表名、中文名、简要说明；切换表后清空旧表缓存和滚动位置。
3. **搜索与筛选工具栏**：全局关键词、列筛选、已生效筛选条件、清空筛选、刷新。
4. **表格工具栏**：列设置、恢复默认列、密度选择；可选“复制当前筛选链接”。
5. **数据表格**：固定可滚动容器高度；表头固定；纵向虚拟滚动和横向滚动。行高首期固定，长文本截断并在详情中完整展示。
6. **记录详情抽屉**：点击一行后展示该记录完整字段、JSON 展开视图、关联 ID 和来源追溯信息。产品相关表可提供到 `RealProductResearch` 的关联跳转。

### 表分类和首期表清单

| 分类 | 表 | 页面说明 |
| --- | --- | --- |
| 产品 | `RealProductResearch` | 产品主资料；默认显示 `id`、`productName`、`category`、`brand`、来源和更新时间等字段（实际字段按 API 元数据）。 |
| 产品 | `ProductPrice` | 报价；可按 `researchId` 查看或跳转到产品主资料。 |
| 产品 | `ProductOperation` | 产品运营、推广和商业状态。 |
| 产品 | `ProductDocument` | 产品关联文档；文档说明中的具体字段不完整，不能在前端硬编码未知列。 |
| 内容 | `ContentRecord` | 内容、账号、视频、审核状态和导入来源。长文案通过详情抽屉阅读。 |
| 知识库 | `KnowledgeBase` | 知识库容器和工作区归属。 |
| 知识库 | `KnowledgeFile` | 文件元数据、处理状态、来源知识库。`storageKey` 默认不下发或不展示。 |
| 知识库 | `KnowledgeChunk` | 文件解析片段；`content` 默认截断预览，`metadata` 可展开；`embedding` 不作为普通表格列返回。 |
| 权限管理 | `User` | 用户身份辅助数据；仅管理员可见，字段需经过白名单审查。 |
| 权限管理 | `WorkspaceMember` | 工作区成员、角色和状态。 |
| 权限管理 | `WorkspaceMemberPermission` | 成员权限覆盖。 |
| 权限管理 | `KnowledgeBaseGrant` | 知识库授权关系。 |
| 会话数据 | `Chat` | 聊天会话；字段由后端表元数据返回。 |
| 会话数据 | `Message_v2` | 消息记录；内容可能较长，表格只显示摘要，详情抽屉显示完整内容。 |
| 兼容数据 | `KnowledgeSource`（Legacy） | 仅当表仍存在且管理员获授权时展示；默认折叠、只读，说明其为迁移兼容表。 |

上表不是对实际数据库物理列的补充定义。`ProductDocument`、`Chat`、`Message_v2`、`KnowledgeSource` 等未在源文档中完整列出字段的表，必须以服务端返回的可展示字段元数据为准。

## 4. 表格交互规格

### 4.1 虚拟滚动与无限下拉

- 使用 AG Grid 的 `rowModelType: 'infinite'`，每次根据 `startRow` / `endRow` 从 datasource 请求一块数据。
- 首期建议 `cacheBlockSize=100`，`maxBlocksInCache` 初始设置 5–10；结合真实网络和表大小压测后调整。
- Grid 只渲染视口附近的行与列；按滚动加载时显示骨架行、底部加载状态和失败重试。
- datasource 请求失败时调用失败回调；提示用户重试，不清空已经成功加载且仍与当前查询匹配的区块。
- 如果 API 能返回精确总数，响应最后一块时返回 `lastRow`；如果总数计算成本高，可以暂不返回总数，在最后一块不足 `limit` 条时推断末尾。
- 每一页查询使用稳定排序：用户指定的排序字段之外，服务端追加唯一键（通常是 `id`）作为最终排序条件，避免相同值记录在相邻区块间重复或跳过。
- `offset/limit` 是 Infinite Row Model 的自然映射。若某张表规模导致深分页代价明显，应先通过数据库索引和压测确认；再单独评估后端区块快照或其他分页方案。

### 4.2 搜索与筛选

- **全局搜索**：由后端在当前表的允许搜索字段中执行，搜索范围包括全部匹配记录，而非已加载行。输入防抖约 300–500ms；支持 Enter 立即执行；中文输入法组合输入期间不触发请求。
- **列筛选**：根据字段类型展示操作符：文本 contains/equals/startsWith，数字范围，日期范围，布尔值，枚举值选择。操作符以字段元数据声明为准。
- 多个列过滤器默认按 AND 组合；全局关键词与列过滤器也按 AND 组合。后端需校验字段和操作符。
- `ContentRecord.searchText` 可用于内容记录快速检索；其他表由后端定义允许参与全局搜索的字段。不要将 `metadata`、向量字段或所有 JSON 内容默认拼接后全表扫描。
- 输入搜索或更改筛选后，重置当前区块缓存并滚回顶部。搜索/筛选条件变化时取消或忽略旧请求，防止旧响应覆盖新条件。

### 4.3 排序

- Community 首期点击列头切换单列升序、降序和取消排序。
- AG Grid 官方当前功能对比将多列排序列为 Enterprise 能力。若要无 Enterprise 支持多列排序，应自行实现排序条件面板，提交有序排序规则给后端；不可把 Shift 多列排序当成免费版默认能力。
- 只有后端元数据声明 `sortable=true` 的列开放排序。
- 数据源接收多排序条件，由后端白名单校验列名、方向和 NULL 排序规则，然后应用于完整结果集。
- 排序变化后重置缓存和滚动位置。客户端不得只对已加载区块进行“全表排序”假象。

### 4.4 自定义列和表头配置

提供自定义“列设置”抽屉（不要启用 Enterprise Columns Tool Panel / Column Chooser），让用户可以：

- 显示/隐藏字段；
- 调整字段顺序、宽度和左右固定位置；
- 恢复当前表默认配置；
- 可选保存命名视图（例如“产品概览”“导入追溯”）。

列显示名、格式化规则和默认可见性由字段注册表定义。用户配置作为个人偏好保存，不能改变全局字段含义或越过字段访问权限。使用稳定 `tableKey + fieldKey` 作为列状态 key；表结构更新后忽略已删除字段，并为新增字段应用默认值。[AG Grid Column State](https://www.ag-grid.com/react-data-grid/column-state/) 支持读取和恢复列状态。

首期个人偏好可保存到后端用户设置；在用户设置接口尚未准备好时可临时使用 `localStorage`，Key 至少包含 `workspaceId/userId/tableKey`。不要仅按表名共享状态，以免不同用户的偏好互相覆盖。

## 5. 建议 API 契约

API 路径仅为建议，需与现有 FastAPI 路由约定统一。建议建立显式只读的表注册表和字段 allowlist。

### 5.1 表和字段元数据

`GET /api/admin/data-tables`

返回当前用户可见的表清单，字段包括：

- `tableKey`、`displayName`、`category`、`description`；
- `columns[]`：`fieldKey`、`displayName`、`dataType`、`defaultVisible`、`sortable`、`searchable`、`filterOperators`、`sensitive`；
- 可选 `rowCount` 或 `rowCountAvailable`。

只有字段注册表中允许显示的列才能返回。`embedding`、文件物理存储路径、凭据、内部令牌等字段不得因为底层数据库有该列就自动透传给前端。

### 5.2 表数据分块读取

`GET /api/admin/data-tables/{tableKey}/rows`

建议参数：

```text
offset: integer
limit: integer (服务端设置上限，例如 500)
q: string (optional)
sort: JSON array, e.g. [{"field":"createdAt","direction":"desc"}]
filters: JSON array, e.g. [{"field":"status","operator":"eq","value":"ready"}]
```

建议响应：

```json
{
  "rows": [{"id": "..."}],
  "offset": 0,
  "limit": 100,
  "total": 235,
  "hasMore": true
}
```

`total` 可选；若返回，必须代表应用所有筛选后的总数。前端 datasource 将它映射为 AG Grid 的 `lastRow`。响应行只包含当前用户授权且字段 allowlist 中声明的值。

### 5.3 后端约束

- 服务端从登录上下文解析 `workspaceId` 和用户权限；忽略或拒绝客户端传入的任意 `workspaceId` 覆盖。
- `tableKey` 只能映射到服务端固定注册表，不可直接插入 SQL 表名。
- 对每张表、每个字段、排序方向、过滤操作符进行 allowlist 校验；使用参数化查询。
- 每次请求都执行 workspace 隔离和 RBAC/知识库授权检查。权限表和聊天消息应默认受更严格的管理员权限控制。
- 所有列表查询均为只读；后端不得因为使用通用表格端点而开放通用增删改接口。
- 对 `KnowledgeChunk.embedding`、`KnowledgeFile.storageKey`、`fileHash`、错误堆栈等内部或敏感数据按策略屏蔽、脱敏或不下发。
- `ProductPrice.priceMin/priceMax` 当前可能是文本；除非数据类型和数值格式规范确定，否则按文本展示和检索，不假设可进行数值区间比较。

## 6. 字段展示规则

- 根据 `dataType` 选择格式化方式：日期按时区统一展示；布尔值显示为是/否；状态显示中文标签并保留原值可查看；空值统一显示 `—`。
- 主键和外键可以在列设置中显示；默认视图优先展示业务可读字段，来源 ID 等追溯字段默认隐藏或放在详情区。
- 长文本列（`productIntro`、`productHighlights`、`copyText`、`revisedCopy`、`KnowledgeChunk.content` 等）表格中截断，详情抽屉显示完整文本，避免自动行高破坏虚拟滚动性能。
- `metadata` 以可折叠 JSON 预览呈现；默认不支持对任意 JSON 深层字段排序/筛选。
- `ProductDocument`、`Chat`、`Message_v2` 和 legacy 表的默认列必须来自后端元数据；不得在前端伪造字段或推断不存在的关联。

## 7. 权限、隐私和审计

- 页面访问权限与 API 数据权限均在后端执行，前端隐藏菜单不构成授权。
- 产品、内容、知识库等记录必须按当前工作区隔离。涉及知识库文件/片段时同时检查知识库授权。
- 权限辅助表、`Chat`、`Message_v2` 默认仅管理员或被明确授权的角色可见；字段级敏感信息需要独立 allowlist。
- 页面只显示当前会话可访问的数据；切换工作区、身份变化或权限失效时清空缓存并重新取数。
- 记录数据浏览审计可沿用现有审计设施；如果尚无审计接口，至少由后端记录管理员访问敏感表的用户、工作区、表名和时间，不在日志中复制整行消息正文。

## 8. 交付拆分

### 阶段一：可用的数据浏览

- 完成表注册表 / 字段元数据 API 与当前用户可见表列表；
- 建立页面框架、表分类选择和 AG Grid Community Infinite Row Model；
- 完成分块查询、基础关键词搜索、服务端排序和类型化筛选；
- 提供只读记录详情抽屉和空态、加载态、错误重试。

### 阶段二：个人化列配置

- 增加显示/隐藏、顺序、宽度、固定列和恢复默认；
- 保存用户与工作区级表格偏好；
- 校验表结构变更时旧配置仍可安全恢复。

### 阶段三：进阶能力（按实际需求排期）

- 命名视图、可分享筛选链接；
- 导出当前查询结果（由后端按权限流式生成，避免只导出浏览器已加载区块）；
- 全量计数、枚举 faceting、服务端分组或聚合；
- 如确有需要，评估 AG Grid Enterprise。不要为了“可能以后用”提前依赖付费模块。

## 9. 验收标准

- 所有第 3 节列出的可用表均能从表选择器访问；未授权表不会出现在元数据/API 响应中；legacy 表明确标记。
- 初次打开只请求首个区块；向下滚动加载后续区块，向上滚动时缓存命中或可重新加载；DOM 节点数不会随已浏览总行数线性增长。
- 在未加载区块中的记录也能被全局搜索、列筛选命中；排序结果跨区块正确，且不会因相同排序值而重复或漏行。
- 改变表、工作区、搜索、筛选或排序后旧数据不会混入新结果，视口回到起始位置。
- 列显示、顺序、宽度、固定状态可以保存并恢复；不同用户偏好互相隔离；服务端元数据变更不会导致前端异常。
- 后端拒绝未注册表名、未授权工作区、未许可字段、未许可排序/过滤字段以及越界 `limit`。
- `KnowledgeChunk.embedding` 和 `KnowledgeFile.storageKey` 不会作为普通行字段泄露；长文本不会撑开行高导致滚动抖动。
- 对代表性大表使用至少 100,000 行的测试数据验证滚动、检索、排序、筛选和切表行为，并记录首屏与区块请求耗时；性能阈值由团队依据目标环境和后端数据量定稿。

## 10. 官方资料

- [AG Grid Infinite Row Model](https://www.ag-grid.com/react-data-grid/infinite-scrolling/)
- [AG Grid Row Models](https://www.ag-grid.com/react-data-grid/row-models/)
- [AG Grid Column State](https://www.ag-grid.com/react-data-grid/column-state/)
- [AG Grid Column Filters](https://www.ag-grid.com/react-data-grid/filtering/)
- [AG Grid Licensing and Pricing](https://www.ag-grid.com/license-pricing/)
- [TanStack Table Virtualization](https://tanstack.com/table/latest/docs/framework/react/guide/virtualization)
- [TanStack Table Client-Side vs Server-Side](https://tanstack.com/table/latest/docs/guide/client-side-vs-server-side)
- [TanStack Query Infinite Queries](https://tanstack.com/query/latest/docs/framework/react/guides/infinite-queries)
- [MUI X Server-Side Lazy Loading](https://mui.com/x/react-data-grid/server-side-data/lazy-loading/)
- [MUI X Licensing](https://mui.com/x/introduction/licensing/)
