# Asianode 业务数据表说明

## 1. 文档目的

本文维护当前系统中由 Agent 查询、文件导入和业务功能使用的主要数据表，说明每张表负责的业务、关键字段和表之间的关系。

本文描述的是当前实现，不代表未来最终的数据模型。新增字段或调整表关系时，应同步更新本文。

## 2. 先理解几个通用字段

| 字段 | 含义 |
| --- | --- |
| `id` | 当前表记录的唯一 ID。不同表的 `id` 不能直接混用。 |
| `workspaceId` | 工作区 ID，用于多租户隔离。查询业务数据时必须限制工作区。 |
| `sourceFileId` | 结构化业务数据的来源文件 ID，直接指向 `KnowledgeFile.id`。这是当前规范中的唯一来源追溯字段。 |
| `sourceId` | 旧版来源字段，迁移后仅为兼容历史数据保留；新代码不再写入，也不应作为查询依据。 |
| `knowledgeBaseId` | 知识库 ID，表示文件或文本片段属于哪个知识库。 |
| `fileId` | 文件 ID，通常指向 `KnowledgeFile.id`。 |
| `researchId` | 产品相关表指向 `RealProductResearch.id` 的外键。 |
| `status` | 生命周期状态，例如 pending、processing、ready、failed。不同表允许的值可能不同。 |
| `sourceSheet` | Excel 来源工作表名称。 |
| `sourceRow` | Excel 来源行号，用于定位原始记录。 |
| `metadata` | JSON 格式的扩展信息，适合保存页码、表头、解析器版本等不稳定字段。 |

## 3. 业务表关系

### 3.1 产品数据

```text
RealProductResearch
├── ProductPrice       一个产品可以有多条报价
├── ProductOperation   产品的运营状态，通常为一条或少量记录
└── ProductDocument    产品关联的文档记录

RealProductResearch.sourceFileId
        └── KnowledgeFile.id
                    └── KnowledgeBase.knowledgeBaseId
```

### 3.2 文件知识数据

```text
KnowledgeBase
└── KnowledgeFile
    └── KnowledgeChunk
```

一个原始文件对应一条 `KnowledgeFile`，一个文件经过解析后会拆成多条 `KnowledgeChunk`。

### 3.3 权限数据

```text
User
└── WorkspaceMember
    └── WorkspaceMemberPermission

KnowledgeBase
└── KnowledgeBaseGrant
```

权限表不是产品业务数据，但 Agent 查询时会使用它们来限制用户能看到的数据。

## 4. 产品业务表

### 4.1 `RealProductResearch`：产品主资料

这张表保存产品的主体信息，是产品搜索的核心表。当前产品接口通常将 `id` 作为产品记录的主要标识。

| 字段 | 业务含义 |
| --- | --- |
| `id` | 产品研究记录 ID。当前接口中的 `product_id` 通常来自这里。 |
| `productName` | 产品名称。 |
| `category` | 产品分类。 |
| `brand` | 品牌名称。 |
| `productIntro` | 产品简介、详细介绍。 |
| `productHighlights` | 产品卖点或重点优势。 |
| `productFeatures` | 产品特征，例如材质、功能、尺寸等。 |
| `procurementConditions` | 采购条件，例如 MOQ、定制要求、采购限制等。 |
| `shippingTime` | 发货时间、交期或物流时效。 |
| `contactPerson` | 产品或供应商联系人。 |
| `supplierContact` | 供应商联系方式或供应商相关说明。 |
| `sourceFileId` | 该产品记录来自哪个上传文件，直接指向 `KnowledgeFile.id`。 |
| `sourceSheet` | 产品来自哪个 Excel 工作表。 |
| `sourceRow` | 产品来自 Excel 的哪一行。 |

这张表适合回答：

- 这个产品叫什么；
- 产品是什么类别、有什么特点；
- 产品的介绍和卖点是什么；
- 产品来自哪个文件、哪个 Sheet、哪一行。

注意：当前接口返回的 `sku`、`supplier_name`、`lead_time_days` 等展示字段，不一定都是这张表中同名的物理列，有些是查询别名、文本解析结果或接口层计算结果。

### 4.2 `ProductPrice`：产品报价

这张表保存产品的报价信息。一个产品可以对应多条记录，例如不同规格、不同价格区间或不同报价方案。

| 字段 | 业务含义 |
| --- | --- |
| `researchId` | 对应 `RealProductResearch.id`。 |
| `sourceFileId` | 报价来自哪个上传文件，直接指向 `KnowledgeFile.id`。 |
| `variant` | 产品规格或变体，例如颜色、尺寸、功率、包装规格。 |
| `priceMin` | 最低报价。当前实现中可能以文本形式保存。 |
| `priceMax` | 最高报价。当前实现中可能以文本形式保存。 |
| `currency` | 货币单位，例如 USD、CNY、TRY。 |

这张表适合回答“某产品报价是多少”。但是当前模型还没有完整表达以下信息：

- 报价时间和有效期；
- 供应商；
- 数量阶梯；
- 报价对应的贸易条款，例如 FOB、EXW、DDP；
- 不同客户或市场的价格。

如果以后要准确回答“某供应商在某日期、某数量下的最新报价”，需要扩展报价模型，而不能只依赖 `priceMin` 和 `priceMax`。

### 4.3 `ProductOperation`：产品运营和商业状态

这张表描述产品是否进入运营、推广和销售流程。

| 字段 | 业务含义 |
| --- | --- |
| `researchId` | 对应产品记录。 |
| `sourceFileId` | 运营记录来自哪个上传文件，直接指向 `KnowledgeFile.id`。 |
| `logisticsTerm` | 物流或贸易条款，例如 FOB、EXW、DDP。 |
| `operationStatus` | 产品运营状态。 |
| `promotionStatus` | 产品推广状态。 |
| `proposer` | 产品提案人或提交人。 |
| `qualifications` | 产品资质、认证或合规信息。 |
| `targetChannels` | 目标销售渠道，例如 TikTok、Amazon、线下渠道。 |

这张表适合回答：

- 产品是否正在运营；
- 产品是否已经推广；
- 产品适合哪些渠道；
- 产品是否有资质；
- 谁提出或提交了这个产品。

### 4.4 `ProductDocument`：产品关联文档

这张表维护产品与文档之间的关系，例如说明书、产品详情、规格文件或报价附件。

当前 Agent 产品查询主要通过 `researchId` 统计产品是否有文档以及文档数量，并不会在产品查询中直接返回文档全文。文档文件和解析后的文本分别由 `KnowledgeFile`、`KnowledgeChunk` 负责。

| 关键字段 | 业务含义 |
| --- | --- |
| `researchId` | 对应 `RealProductResearch.id`。 |
| `sourceFileId` | 文档记录来自哪个上传文件，直接指向 `KnowledgeFile.id`。 |
| 其他文档关联字段 | 由实际数据库表结构决定，当前产品搜索合同不依赖这些字段。 |

## 5. 内容业务表

### 5.1 `ContentRecord`：内容营销和视频内容

这张表保存内容运营记录，例如短视频、脚本、文案、拍摄计划和发布状态。

#### 账号和渠道字段

| 字段 | 业务含义 |
| --- | --- |
| `accountName` | 账号名称。 |
| `accountType` | 账号类型。 |
| `accountDirection` | 账号定位或运营方向。 |
| `platform` | 发布平台，例如 TikTok、Instagram。 |
| `language` | 内容语言。 |

#### 内容字段

| 字段 | 业务含义 |
| --- | --- |
| `title` | 内容标题。 |
| `recordType` | 内容记录类型。 |
| `product` | 关联产品。 |
| `targetTopic` | 目标主题。 |
| `tags` | 内容标签。 |
| `copyText` | 原始文案。 |
| `revisedCopy` | 修改后的文案。 |
| `copyWriter` | 文案作者。 |
| `notes` | 备注。 |

#### 视频和拍摄字段

| 字段 | 业务含义 |
| --- | --- |
| `videoType` | 视频类型。 |
| `shootingScene` | 拍摄场景。 |
| `shootConfirmed` | 是否确认拍摄。 |
| `plannedAt` | 计划拍摄或发布时间。 |
| `photographer` | 摄影师或拍摄负责人。 |
| `referenceVideo` | 参考视频地址或说明。 |
| `scriptDocument` | 脚本文件或脚本地址。 |
| `aiMaterials` | AI 生成或辅助制作的素材。 |
| `attachment` | 内容附件。 |

#### 状态和来源字段

| 字段 | 业务含义 |
| --- | --- |
| `reviewStatus` | 内容审核状态。 |
| `usageStatus` | 内容使用状态。 |
| `submitter` | 内容提交人。 |
| `sourceFileId` | 数据来源文件 ID，直接指向 `KnowledgeFile.id`。 |
| `sourceSheet` | Excel 来源工作表。 |
| `sourceRow` | Excel 来源行号。 |
| `searchText` | 为搜索生成的合并文本。 |

这张表适合回答：

- 某个产品有哪些内容和视频；
- 哪个平台要发布什么；
- 文案是谁写的；
- 内容目前是否审核、是否使用；
- 内容来自哪个文件和 Excel 行。

## 6. 文件和知识库表

### 6.1 `KnowledgeBase`：知识库容器和权限边界

`KnowledgeBase` 是知识库容器，负责工作区归属、生命周期和授权边界；它不再承担具体文件来源记录的职责。
旧的 `KnowledgeSource` 表仅为迁移回滚保留，当前代码不向其中写入新数据。

| 字段 | 业务含义 |
| --- | --- |
| `id` | 知识库或来源 ID。 |
| `displayName` | 知识库名称。 |
| `sourceType` | 知识库创建方式或业务类型，例如 manual。 |
| `status` | 知识库状态，例如 ready。 |
| `version` | 知识库元数据版本。 |
| `workspaceId` | 所属工作区。 |
| `createdAt` | 创建时间。 |
| `updatedAt` | 最后更新时间。 |

### 6.2 `KnowledgeFile`：上传文件元数据

这张表记录上传文件的身份和处理状态，文件本体保存在本地目录或 S3，不直接保存在数据库字段中。

| 字段 | 业务含义 |
| --- | --- |
| `id` | 文件记录 ID。 |
| `originalName` | 用户上传时的原始文件名。 |
| `mimeType` | 文件 MIME 类型，例如 PDF、XLSX、CSV。 |
| `byteSize` | 文件大小，单位为字节。 |
| `fileHash` | 文件内容哈希。 |
| `storageKey` | 文件在本地存储或 S3 中的路径。 |
| `storageProvider` | 存储提供方，例如 local、s3。 |
| `status` | 文件处理状态。 |
| `errorMessage` | 解析失败时保存的错误信息。 |
| `knowledgeBaseId` | 所属知识库。 |
| `workspaceId` | 所属工作区。 |
| `uploadedBy` | 上传用户 ID。 |
| `createdAt` | 上传时间。 |
| `updatedAt` | 最后处理或更新时间。 |

当前 `status` 主要包括：

```text
pending     等待解析
processing  正在解析
ready       解析成功
failed      解析失败
```

### 6.3 `KnowledgeChunk`：文件解析后的文本片段

这张表保存文件解析后拆分出来的文本。一个文件可以对应很多个文本片段。

| 字段 | 业务含义 |
| --- | --- |
| `id` | 文本片段 ID。 |
| `fileId` | 对应 `KnowledgeFile.id`。 |
| `chunkIndex` | 文本片段在文件中的顺序。 |
| `content` | 解析后的实际文本。 |
| `metadata` | JSON 扩展信息，例如页码、标题、表格位置、解析器版本。 |
| `knowledgeBaseId` | 所属知识库。 |
| `workspaceId` | 所属工作区。 |
| `createdAt` | 创建时间。 |
| `embedding` | 可选向量字段，用于未来语义搜索；只有启用向量迁移和相关配置时才使用。 |

删除某个文件时，理论上可以通过 `fileId` 删除它对应的所有 `KnowledgeChunk`，同时删除本地或 S3 中的源文件，实现文件级别的可追溯和撤销。

## 7. 权限辅助表

### 7.1 `User`：用户账户

当前 Agent 的权限判断主要使用以下字段：

| 字段 | 业务含义 |
| --- | --- |
| `id` | 用户 ID。 |
| `isAnonymous` | 是否匿名用户。 |

用户的邮箱、姓名等账户字段可能存在，但不是当前 Agent 权限查询的核心字段。

### 7.2 `WorkspaceMember`：工作区成员关系

这张表表示一个用户是否属于某个工作区，以及该用户在工作区中的角色。

| 字段 | 业务含义 |
| --- | --- |
| `id` | 成员关系 ID。 |
| `workspaceId` | 工作区 ID。 |
| `userId` | 用户 ID。 |
| `role` | 工作区角色。 |
| `status` | 成员状态。 |

### 7.3 `WorkspaceMemberPermission`：成员权限覆盖

这张表用于对单个工作区成员增加或拒绝特定权限。

| 字段 | 业务含义 |
| --- | --- |
| `memberId` | 对应 `WorkspaceMember.id`。 |
| `permission` | 权限名称，例如 `knowledge.read`。 |
| `effect` | 权限效果，例如 allow 或 deny。 |

### 7.4 `KnowledgeBaseGrant`：知识库授权

这张表控制某个用户或角色对某个知识库的访问级别。

| 字段 | 业务含义 |
| --- | --- |
| `id` | 授权记录 ID。 |
| `knowledgeBaseId` | 被授权的知识库 ID。 |
| `subjectType` | 授权对象类型，目前为 `user` 或 `role`。 |
| `subjectId` | 用户 ID 或角色 ID。 |
| `accessLevel` | 访问级别，目前为 `read` 或 `manage`。 |
| `workspaceId` | 所属工作区。 |
| `createdAt` | 授权创建时间。 |
| `updatedAt` | 授权更新时间。 |

通常：

- `read`：可以查询、读取知识库；
- `manage`：还可以上传、删除或管理知识库文件。

## 8. 聊天记录表

### 8.1 `Chat`

保存一次聊天会话的基本信息，例如会话归属用户、标题和时间。

### 8.2 `Message_v2`

保存用户消息和 Agent 回复，是聊天历史数据，不属于产品或知识库业务数据。

Agent 当前执行查询时，业务查询工具本身是只读的；聊天消息的持久化由聊天接口单独写入 `Chat` 和 `Message_v2`。

## 9. 当前 Agent 的数据边界

当前 Agent 通过固定工具查询数据，主要可以访问：

| 工具 | 主要读取的表 |
| --- | --- |
| `searchProductsTool` | `RealProductResearch`、`ProductPrice`、`ProductOperation`、`ProductDocument`、来源表 |
| `searchContentTool` | `ContentRecord`、来源表 |
| `listKnowledgeBasesTool` / `getKnowledgeBaseTool` | `KnowledgeBase` 或 `KnowledgeSource` |
| `listKnowledgeFilesTool` / `getKnowledgeFileTool` | `KnowledgeFile` |
| `searchKnowledgeBaseTool` | `KnowledgeChunk`、`KnowledgeFile`，且需要启用向量搜索 |

权限校验还会读取 `User`、`WorkspaceMember`、`WorkspaceMemberPermission` 和 `KnowledgeBaseGrant`。

当前没有给 Agent 开放任意 SQL 工具，也没有通过上述查询工具直接修改产品、内容或知识库业务表。

## 10. 数据导入和追溯约定

推荐的导入链路是：

```text
上传原始文件
    ↓
KnowledgeFile
    ↓
文件解析 / 文本抽取
    ↓
KnowledgeChunk
    ↓
结构化数据识别和人工审核
    ↓
RealProductResearch / ProductPrice / ProductOperation / ProductDocument / ContentRecord
```

结构化记录进入业务表时，应保留：

- `sourceFileId`：来源文件；
- `sourceSheet`：Excel 工作表；
- `sourceRow`：Excel 行号；
- `researchId`：产品子表回指产品主记录；
- 后续可增加 `sourceChunkId` 或导入批次 ID，但不影响当前关系。

这样在源文件被删除、替换或重新解析时，才能定位哪些业务记录受到影响，而不是依靠产品名称等不稳定文本进行猜测。
