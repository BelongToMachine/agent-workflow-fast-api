# AI Agent 文件解析、审核与入库架构

## 1. 文档状态

- 状态：设计草案
- 当前范围：文件上传、确定性解析、AI 生成待入库提案、开发人员审核、受控入库
- 暂不包含：向量、Embedding、RAG、自动建表、完全自动批准
- 设计目标：在不改变现有业务表作为最终数据来源的前提下，建立可追踪、可审核、可重试、可撤回、可扩展的文件导入流水线

## 2. 核心结论

AI Agent 只负责理解解析结果并生成结构化变更提案，不直接执行 SQL，也不能创建数据库表。

推荐采用以下四层架构：

```text
不可变源文件
    ↓
标准化解析产物
    ↓
待审核 ImportProposal
    ↓
受控 Application Service 入库
```

完整流程：

```text
用户上传文件
    ↓
FastAPI 校验权限、类型、大小和文件哈希
    ↓
S3 保存原始文件，PostgreSQL 创建 KnowledgeFile 和 ImportJob
    ↓
独立 Worker 领取任务并选择确定性解析器
    ↓
解析器生成统一 ParsedArtifact，并保存到 S3
    ↓
AI Agent 读取 ParsedArtifact、目标 Schema 和现有业务数据
    ↓
AI Agent 生成 ImportProposal，不修改业务表
    ↓
开发人员查看原文、来源位置、数据差异和冲突
    ↓
开发人员修改、批准或拒绝提案
    ↓
Application Service 在数据库事务内执行批准后的提案
    ↓
写入业务表、ImportedFact 和 AuditLog
```

## 3. 设计原则

### 3.1 原始文件不可变

原始文件上传到 S3 后不覆盖。文件内容变化时创建新的 `KnowledgeFile` 和新的版本关系，不在原对象上直接更新。

文件使用 SHA-256 哈希去重。同一个知识库内重复上传相同内容时，不重复创建导入数据。

### 3.2 解析和理解分离

文件格式解析由确定性代码完成，AI Agent 不直接读取或解释二进制文件。

解析器负责回答“文件里有什么”，AI Agent 负责回答“这些内容应该如何映射到业务数据”。

### 3.3 提案和写入分离

Agent 的输出必须先保存成 `ImportProposal`。只有通过开发人员审核后，固定的 Application Service 才能写业务表。

### 3.4 数据库 Schema 由代码管理

Agent 只能使用代码中声明的实体、匹配键和可写字段。新增表和字段必须通过代码评审和数据库 migration 完成。

### 3.5 每个入库字段都能追溯来源

业务表保存当前生效值，`ImportedFact` 保存该值来自哪个文件、哪个位置、哪个提案以及原始值是什么。

### 3.6 所有步骤可幂等重试

文件上传、解析、Agent 分析和最终入库都必须具有幂等键。Worker 或 API 重试不能产生重复产品或重复字段来源。

## 4. 支持的文件类型

第一阶段支持：

| 文件类型 | 解析策略 | 来源定位 |
|---|---|---|
| PDF | `rapidocr_pdf` 统一处理：优先提取原生文本，无有效文本的页面自动进入 RapidOCR | 页码、段落、页面置信度 |
| XLSX | 按工作表、行、列读取，保留表头 | Sheet、行号、列名 |
| CSV | 检测编码和分隔符后按行读取 | 行号、列名 |
| JSON | 保留对象和数组结构 | JSONPath |
| Markdown | 按标题、段落、列表、代码块解析 | 标题路径、行号 |
| TXT | 按段落和行解析 | 行号、字符范围 |
| PPTX | 按幻灯片和 Shape 提取文字及表格 | 幻灯片编号、Shape 编号 |

第一阶段优先支持 `.pptx`。旧版 `.ppt` 是二进制格式，应先通过受控转换程序转换成 `.pptx`，再进入标准解析流程。

## 5. 标准化解析产物

所有解析器必须输出同一种 `ParsedArtifact` 结构，避免 Agent 为每种文件重新理解不同协议。

建议结构：

```json
{
  "schemaVersion": "1",
  "sourceFileId": "uuid",
  "parser": {
    "name": "xlsx-parser",
    "version": "1.0.0"
  },
  "blocks": [
    {
      "blockId": "block-001",
      "type": "table_row",
      "text": "ABC-001, Chair, 129.90 USD",
      "structuredData": {
        "sku": "ABC-001",
        "name": "Chair",
        "price": 129.9,
        "currency": "USD"
      },
      "sourceLocator": {
        "sheet": "Products",
        "row": 18
      }
    }
  ]
}
```

`blockId` 在同一个解析产物中必须稳定。重新使用相同文件、解析器版本和 Schema 版本生成解析产物时，应得到相同的 block 标识。

解析产物保存在 S3，不要求将全部解析文字写入 PostgreSQL：

```text
imports/{workspace_id}/{file_id}/{job_id}/parsed.json
```

数据库只保存 `parsedArtifactKey`、哈希、解析器版本和状态。审核页面需要展示原文时，通过后端读取对应的解析产物。

## 6. 数据模型

### 6.1 KnowledgeFile

复用现有 `KnowledgeFile` 作为文件层，继续保存：

```text
id
workspaceId
knowledgeBaseId
originalName
fileHash
storageProvider
storageKey
mimeType
byteSize
status
uploadedBy
createdAt
updatedAt
```

建议后续增加：

```text
logicalSourceId   同一份逻辑文件不同版本的分组标识
version           文件版本
retiredAt         文件退出使用的时间
retiredBy         执行退出操作的用户
```

原始文件状态和导入任务状态应分开。`KnowledgeFile.status` 表示文件是否可用，具体解析和入库进度由 `ImportJob.status` 表示。

当前最小闭环先使用 `KnowledgeParsedDocument` 保存解析后的 JSONB 中间态，并由 `chunkStatus` 跟踪手动生成 `KnowledgeChunk` 的进度；`ImportJob` 可在后续把 FastAPI 后台任务替换成可恢复的独立 Worker。

### 6.2 ImportJob

一条记录代表一次文件解析和提案生成任务。

建议字段：

```text
id
workspaceId
knowledgeBaseId
sourceFileId
status
parsedArtifactKey
parsedArtifactHash
parserName
parserVersion
promptVersion
schemaVersion
attemptCount
errorCode
errorMessage
createdBy
createdAt
startedAt
finishedAt
```

状态机：

```text
queued
  → parsing
  → analyzing
  → awaiting_review
  → approved
  → applying
  → completed
```

异常和人工分支：

```text
queued/parsing/analyzing/applying → failed
awaiting_review                  → rejected
awaiting_review                  → schema_review_required
任意未完成状态                    → cancelled
```

建议唯一幂等键：

```text
sourceFileId + parserVersion + promptVersion + schemaVersion
```

### 6.3 ImportProposal

一条记录代表 Agent 对一个业务实体提出的一次创建或更新操作。

建议字段：

```text
id
jobId
workspaceId
targetEntityType
targetEntityId
matchKey JSONB
operation
patch JSONB
sourceReferences JSONB
confidence
status
reviewComment
reviewedBy
reviewedAt
createdAt
updatedAt
```

`operation` 第一阶段只允许：

```text
insert
update
```

`status`：

```text
pending
approved
rejected
applied
failed
schema_review_required
```

提案例子：

```json
{
  "targetEntityType": "product",
  "operation": "update",
  "matchKey": {
    "sku": "ABC-001"
  },
  "patch": {
    "price": {
      "before": 119.9,
      "after": 129.9,
      "sourceBlockId": "block-001",
      "confidence": 0.96
    }
  }
}
```

`patch` 中保存审核时看到的 `before`，但执行入库前必须重新读取数据库。如果当前值已经变化，应停止应用并将提案标记为冲突，不能覆盖新数据。

### 6.4 ImportedFact

`ImportedFact` 保存已经批准并应用的字段级来源关系。它既是来源记录，也是未来文件撤回和数据重建的基础。

建议字段：

```text
id
workspaceId
proposalId
sourceFileId
entityType
entityId
fieldName
valueJson
sourceLocator JSONB
confidence
status
createdAt
retiredAt
```

状态：

```text
active
superseded
retired
```

建议唯一键至少包含：

```text
proposalId + entityType + entityId + fieldName + sourceFileId
```

### 6.5 AuditLog

复用现有 `AuditLog`，记录：

```text
file.uploaded
import.job_started
import.proposal_created
import.proposal_edited
import.proposal_approved
import.proposal_rejected
import.proposal_applied
import.proposal_failed
source.file_retired
import.fact_retired
```

AuditLog 不替代 `ImportedFact`。AuditLog 用于记录谁在什么时候做了什么，ImportedFact 用于回答当前业务字段来自哪里。

## 7. 多文件共同维护一个 Product

不能只在 `Product` 上保存一个 `sourceFileId`。同一个 Product 的不同字段可能来自不同文件：

```text
Product ABC-001.name     ← 文件 A，第 18 行
Product ABC-001.price    ← 文件 B，第 32 行
Product ABC-001.supplier ← 文件 C，第 5 页
```

`Product` 继续保存当前生效值：

```text
Product.price = 129.9
```

对应的来源和历史值写入 `ImportedFact`：

```text
entityType = product
entityId   = ABC-001 对应的数据库 ID
fieldName  = price
valueJson  = 129.9
sourceFileId = 文件 B
sourceLocator = {"sheet":"Products","row":32}
```

第一阶段不要求自动合并所有冲突。遇到多个文件提供不同值时，默认创建冲突提案并要求开发人员选择。

后续可以添加可配置的合并规则：

```text
人工输入 > 受信任数据源 > 最新已批准文件 > Agent 置信度
```

合并规则必须由代码或配置定义，不能由 Agent 临时决定。

## 8. Agent 工具边界

第一阶段建议提供以下只读和提案工具：

### 8.1 getParsedBlocks

按照 `jobId` 和分页游标读取解析结果，不一次把整个文件放入模型上下文。

输入：

```text
jobId
cursor
limit
```

输出：

```text
blocks
nextCursor
```

### 8.2 getWritableSchema

返回当前允许导入的实体、匹配键、字段类型和写入规则。

例如：

```json
{
  "entityType": "product",
  "matchKeys": ["sku"],
  "writableFields": {
    "name": "string",
    "price": "decimal",
    "currency": "string"
  }
}
```

### 8.3 findExistingEntities

根据受控匹配字段查询可能存在的业务记录，用于去重和生成 `before/after` 差异。

### 8.4 submitImportProposal

提交符合 Pydantic Schema 的提案。该工具只写 `ImportProposal`，不能写业务表。

Agent 不得获得以下工具：

```text
executeSQL
createTable
alterTable
updateDatabase
deleteDatabaseRecord
```

## 9. 可写 Schema Registry

在代码仓库内维护可写 Schema，不把实际数据库表结构完整暴露给 Agent。

每个实体定义：

```text
entityType
target service
match keys
writable fields
field types
normalization rules
required fields
conflict policy
permission requirement
```

例如：

```yaml
product:
  match_keys:
    - sku
  writable_fields:
    name: string
    price: decimal
    currency: string
  required_fields:
    - sku
    - name
```

如果 Agent 发现未知实体或未知字段：

1. 保存原始解析内容；
2. 创建 `schema_review_required` 提案；
3. 开发人员决定映射到已有字段、写入 `extraAttributes JSONB`，或创建 migration；
4. Schema Registry 更新后重新运行 ImportJob。

## 10. API 设计

### 10.1 上传并创建任务

```http
POST /api/v1/knowledge-bases/{knowledge_base_id}/imports?workspace_id={workspace_id}
Content-Type: multipart/form-data
```

成功返回：

```http
202 Accepted
```

```json
{
  "fileId": "uuid",
  "jobId": "uuid",
  "status": "queued"
}
```

### 10.2 查看任务

```http
GET /api/v1/import-jobs/{job_id}?workspace_id={workspace_id}
```

### 10.3 查看提案

```http
GET /api/v1/import-jobs/{job_id}/proposals?workspace_id={workspace_id}
```

### 10.4 修改提案

```http
PATCH /api/v1/import-proposals/{proposal_id}?workspace_id={workspace_id}
```

开发人员可以修正字段映射和值。修改行为必须写入 AuditLog。

### 10.5 批准或拒绝

```http
POST /api/v1/import-jobs/{job_id}/approve?workspace_id={workspace_id}
POST /api/v1/import-jobs/{job_id}/reject?workspace_id={workspace_id}
```

批准只改变审核状态，不立即允许 Agent 执行 SQL。

### 10.6 应用提案

```http
POST /api/v1/import-jobs/{job_id}/apply?workspace_id={workspace_id}
```

由受控 Application Service 异步执行，返回 `202`。任务最终进入 `completed` 或 `failed`。

## 11. 审核页面要求

开发人员审核时至少需要看到：

- 文件名、文件版本、上传人和上传时间；
- 解析器版本和 Agent prompt/model 版本；
- 原文件下载链接；
- 原始内容及页码、Sheet、行号、JSONPath 或幻灯片编号；
- 目标实体、目标记录和匹配依据；
- 修改前、修改后；
- 新增、更新和冲突数量；
- Agent 置信度和解释；
- 未识别字段；
- 审核意见和历史修改记录。

第一阶段所有提案都要求人工批准。自动批准应在业务规则稳定后作为独立阶段设计。

## 12. 受控入库服务

批准后的提案由固定 Application Service 执行：

1. 检查操作人权限；
2. 检查 ImportJob 和所有 Proposal 都处于可应用状态；
3. 根据 Schema Registry 再次校验实体、字段和值；
4. 重新查询目标记录；
5. 比较当前值和 Proposal 中的 `before`；
6. 有冲突时停止，不覆盖新值；
7. 开启数据库事务；
8. 写业务表；
9. 为每个应用字段写入 `ImportedFact`；
10. 写 AuditLog；
11. 将 Proposal 标记为 `applied`；
12. 所有操作成功后提交事务。

不允许部分事务成功后静默继续。单个 Proposal 内业务表和来源记录必须同时成功或同时回滚。

## 13. Worker 架构

文件解析和 Agent 调用不应运行在 FastAPI 请求生命周期内，也不应依赖 FastAPI `BackgroundTasks`。

建议在 Compose 中增加独立 Worker：

```text
api      接收上传、查询状态、执行审核操作
worker   解析文件、调用 Agent、应用批准后的提案
redis    可选的任务唤醒和短期协调
postgres ImportJob 的权威状态和幂等控制
```

当前导入量较小时，可以直接以 PostgreSQL 作为任务队列：

```sql
SELECT ...
FROM "ImportJob"
WHERE status = 'queued'
ORDER BY "createdAt"
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Redis 可以用于通知 Worker 有新任务，但不能作为唯一任务记录。即使 Redis 重启，Worker 也必须能从 PostgreSQL 恢复未完成任务。

## 14. 文件撤回和数据可逆性

第一阶段需要保存完整来源，但可以暂不提供自动撤回 API。设计上必须保证以后可以实现：

```text
KnowledgeFile 标记 retired
    ↓
禁止新的 Agent 和查询继续使用该文件
    ↓
该文件对应的 ImportedFact 标记 retired
    ↓
找出受影响的业务实体和字段
    ↓
存在其他 active 来源：选择其他来源并重建字段
不存在其他来源：清空、归档或进入人工审核
```

原始 S3 对象建议先进入保留期，不立即永久删除。保留期结束后才执行物理删除。物理删除后无法再从该文件重建数据。

## 15. S3 对象结构

建议结构：

```text
knowledge/
  {workspace_id}/
    original/
      {file_id}/{original_name}
    imports/
      {file_id}/{job_id}/parsed.json
      {file_id}/{job_id}/agent-output.json
      {file_id}/{job_id}/review-snapshot.json
```

原则：

- 原文件不可覆盖；
- 解析结果按 job 保存；
- Agent 原始输出保留，方便审计和复现；
- S3 key 不直接使用未经清理的用户文件名；
- 下载通过后端鉴权或短期 presigned URL；
- workspace 必须作为对象路径和数据库查询边界。

## 16. 安全要求

- 校验文件扩展名、MIME 和文件签名；
- 设置单文件大小、页数、Sheet 数量和总解压大小限制；
- 防止 XLSX/PPTX ZIP bomb；
- 文件内容属于不可信输入，其中的文字不能覆盖 Agent 系统指令；
- Agent 只接受白名单工具；
- 上传、查看、审核、批准、应用分别检查 workspace 权限；
- S3 对象默认私有；
- 日志不记录文件全文、密钥或个人敏感信息；
- AI provider 处理公司敏感文件前需要确认数据保留和训练策略；
- 入库前所有数据必须经过服务端 Pydantic 校验，不能只信任 Agent 输出。

## 17. 与未来 RAG 的兼容方式

当前流程已经支持手动的 `ParsedDocument → KnowledgeChunk` 阶段，但解析任务本身不会自动创建 chunk，也不要求 Embedding provider。只有开发人员确认后，调用手动 chunk 接口，文件的 `chunkStatus` 才会进入处理流程。

需要保证 `ParsedDocument.blocks` 包含：

```text
稳定 blockId
可读文本
结构化数据
sourceLocator
sourceFileId
```

以后可以增加独立流水线：

```text
KnowledgeParsedDocument
    ↓
Chunk Worker
    ↓
KnowledgeChunk
    ↓
Embedding / RAG
```

RAG 流水线只消费已有解析产物或已确认的 `KnowledgeChunk`，不改变 `ImportJob`、`ImportProposal`、`ImportedFact` 和业务表的职责。

## 18. 第一阶段实施顺序

### 阶段一：文件和任务基础设施

1. 为 production 配置 S3-compatible storage；
2. 创建 `ImportJob`、`ImportProposal` 和 `ImportedFact` migration；
3. 增加上传和任务查询 API；
4. 增加独立 Worker；
5. 支持文件哈希和幂等任务。

### 阶段二：解析器

1. 优先完成 CSV、XLSX、JSON；
2. 完成 Markdown 和 TXT；
3. 完成统一 PDF 解析（普通、扫描和混合 PDF）；
4. 完成 PPTX；
5. 为 PPTX 图片/图表和云端 OCR 增加可选 Parser Adapter。

### 阶段三：Agent 提案

1. 定义 Schema Registry；
2. 先只允许写一个业务实体，例如 Product；
3. 实现只读查询工具和 `submitImportProposal`；
4. 固定 promptVersion 和模型版本；
5. 保存 Agent 原始输出和解析错误。

### 阶段四：开发审核和入库

1. 实现提案列表和详情页；
2. 实现编辑、批准和拒绝；
3. 实现受控 Application Service；
4. 写入 ImportedFact 和 AuditLog；
5. 增加冲突检测、事务回滚和重复提交测试。

### 阶段五：可逆性

1. 增加文件 retired 状态；
2. 支持查看文件影响的实体和字段；
3. 支持撤回预览；
4. 支持批准后撤回和字段重建；
5. 增加 S3 保留期和最终清理任务。

## 19. 第一阶段验收标准

- 支持上传 CSV、XLSX、JSON、Markdown、TXT、PDF 和 PPTX；
- 文件原件存入 S3，数据库不保存二进制正文；
- 上传接口保存原始文件并返回文件记录，不会自动解析；
- 用户显式点击解析后，解析结果写入 `KnowledgeParsedDocument`；
- 审核人员显式点击生成 chunk 后，才会生成 `KnowledgeChunk`；
- 后续可把当前 FastAPI 后台任务替换为独立 Worker；
- 所有解析结果都能定位到原文件中的页、Sheet、行、JSONPath 或幻灯片；
- Agent 不能直接访问 SQL 或修改业务表；
- Agent 只能提交符合 Schema Registry 的 ImportProposal；
- 开发人员可以查看、编辑、批准和拒绝提案；
- 未批准提案不能修改业务表；
- 已批准提案通过事务写入业务表和 ImportedFact；
- 重复调用 apply 不会重复创建数据；
- 业务数据发生并发变化时，旧提案不会静默覆盖新值；
- 每个导入字段可以追踪到文件和具体位置；
- 解析失败和 chunk 生成失败分别记录状态，并可独立重试；
- `KnowledgeParsedDocument` 可以被未来的 RAG 流水线消费。
