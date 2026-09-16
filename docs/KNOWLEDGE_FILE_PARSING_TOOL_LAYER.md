# Knowledge File Parsing Tool Layer

## 1. 目标

本层负责让 AI Agent 通过受控工具读取已经存储在 S3/MinIO 中的知识文件，并将文件内容转换为统一的文本或结构化结果。

解析层不直接写入业务表，也不直接把原始文件内容交给模型。它先生成可追溯的中间结果，再由 Agent 将结果分流到 PostgreSQL 业务数据通道或向量数据通道。

```text
S3/MinIO 原始文件
        ↓
KnowledgeFile
        ↓
Parser Tool Layer
        ↓
ParsedDocument
        ↓
KnowledgeParsedDocument
        ↓
开发审核 / 手动生成
        ↓
KnowledgeChunk
        ↓
AI Agent / Embedding / RAG
```

当前实现把解析和切片拆成两个显式动作：上传只保存原始文件；点击“开始解析”后生成并保存 `ParsedDocument`；审核确认后点击“生成知识片段”才会替换该文件对应的 `KnowledgeChunk`。结构化业务入库和 Qdrant 仍是后续独立流程。

## 2. 核心原则

1. `KnowledgeBase` 负责知识库容器、Workspace 隔离和权限边界。
2. `KnowledgeFile` 代表一个实际上传的原始文件，是所有解析结果和业务数据的来源锚点。
3. Agent 只能通过 `fileId` 读取文件，不能直接传入任意 bucket、object key 或文件系统路径。
4. Parser 负责确定性解析，Agent 负责理解、分类和生成入库草稿。
5. Agent 不直接执行任意 SQL，也不直接修改业务表或 Qdrant。
6. 精确数值由 PostgreSQL 作为事实来源，语义文本由 Qdrant 作为召回来源。
7. 同一文件或同一内容块可以同时产生结构化事实和语义文本。

## 3. Agent 工具边界

第一版建议向 Agent 暴露少量通用工具，而不是为每种文件格式暴露一套工具。

### 3.1 文件发现与检查

```text
listKnowledgeFilesTool
inspectKnowledgeFileTool
listParsedDocumentsTool
```

`inspectKnowledgeFileTool` 应返回：

- `fileId`
- 文件名和 MIME 类型
- 文件大小和哈希
- 解析器类型和支持状态
- 页数、Sheet 数量或幻灯片数量（可获取时）
- 当前解析任务状态

### 3.2 文件解析

```text
extractKnowledgeFileTool
POST /knowledge-bases/{knowledgeBaseId}/files/{fileId}/parse
GET /knowledge-bases/{knowledgeBaseId}/parsed-documents
GET /knowledge-bases/{knowledgeBaseId}/files/{fileId}/parsed-document
```

解析工具建议支持：

```json
{
  "fileId": "file-id",
  "output": "text|structured",
  "page": 3,
  "sheet": "产品报价",
  "cursor": "optional-cursor"
}
```

当前 API 的解析任务通过 FastAPI 后台任务执行，结果持久化在 PostgreSQL 的 `KnowledgeParsedDocument.document` JSONB 字段。知识库级接口 `GET /knowledge-bases/{knowledgeBaseId}/parsed-documents` 返回该知识库下所有已保存的 ParsedDocument，并按 `offset`/`limit` 分页 ParsedDocument 记录；每个 ParsedDocument 默认返回前 30 个 block，可用 `block_offset`/`block_limit` 分页 block。原来的文件级接口仍保留，用于兼容和查看单个文件的中间态。接口不会把大文件的原始二进制返回浏览器。生产环境后续可将后台任务替换为 Redis Worker。

### 3.3 ParsedDocument 审核与切片

```text
GET  .../parsed-documents       查看当前知识库的全部中间态
GET  .../files/{fileId}/parsed-document  查看单个文件的中间态
POST .../chunks                 手动触发 ParsedDocument → KnowledgeChunk
```

`KnowledgeParsedDocument.chunkStatus` 单独记录 `pending / processing / ready / failed`。重复点击会通过数据库原子 claim 避免并发重复生成；生成成功时先删除该文件旧的 chunk，再写入当前 ParsedDocument 对应的新 chunk。解析本身不会自动创建或删除 chunk。

### 3.4 入库草稿

```text
createImportProposalTool
getImportProposalTool
```

Agent 根据解析结果生成待审核的结构化入库草稿。开发人员审核通过后，由后端事务性写入业务表。

向量索引也应使用受控的发布流程，例如：

```text
publishApprovedChunks
```

是否自动发布向量数据，应由业务策略决定，不能由模型自行决定。

## 4. 统一解析输出格式

所有格式的解析器都应输出统一的 `ParsedDocument`，而不是直接暴露第三方库的返回值。

```json
{
  "fileId": "file-id",
  "fileHash": "sha256...",
  "parser": "xlsx",
  "parserVersion": "1.0",
  "contentType": "structured",
  "blocks": [
    {
      "blockId": "block-001",
      "kind": "table_row",
      "text": "Riboton，售价 99 USD，尺寸 20cm",
      "data": {
        "productName": "Riboton",
        "price": 99,
        "currency": "USD",
        "size": "20cm"
      },
      "locator": {
        "sheet": "产品报价",
        "row": 12
      }
    }
  ],
  "warnings": [],
  "truncated": false
}
```

每个 block 至少应包含：

- 稳定的 `blockId`；
- 原始文本 `text`；
- 可选的结构化 `data`；
- 原始位置 `locator`；
- 文件 ID、文件哈希和解析器版本；
- 解析警告和截断状态。

## 5. 文件类型与解析器

当前支持的文件类型和推荐解析工具如下：

| 文件类型 | 推荐解析器 | 默认输出 | 主要限制 |
| --- | --- | --- | --- |
| TXT | Python 标准库 | 纯文本 | 需要处理 UTF-8、BOM 和换行符 |
| Markdown | Markdown 解析器或保留原文 | 纯文本和标题/段落结构 | 不应只转换为 HTML，应保留原始结构 |
| JSON | Python `json` | JSON 和规范化文本 | 保留数组层级和 JSON Path |
| CSV | Python `csv` 或 Polars | 表头、行数据、JSON rows | 需要处理编码、分隔符、空值和重复表头 |
| XLSX | `openpyxl` | Sheet、表头、行数据和文本 | 使用只读模式，保留 Sheet 和行号 |
| PDF | `rapidocr_pdf`（内部使用 PyMuPDF + RapidOCR/ONNX Runtime） | 按页提取文本，扫描页自动 OCR | 支持普通、扫描和混合 PDF；保留页码与页面置信度 |
| PPTX | `python-pptx` | 按幻灯片、形状和表格提取文本 | 图片和图表中的文字需要 OCR |
| PPT | LibreOffice 转换或暂不支持 | — | 旧式二进制格式不建议直接解析 |

当前代码中已经使用或预留：

- `rapidocr_pdf`：统一处理 PDF 文本层和扫描页 OCR；底层使用 PyMuPDF 提取原生文本，使用 RapidOCR/ONNX Runtime 识别图片型页面；
- `openpyxl`：XLSX 只读解析；
- `python-pptx`：PPTX 文本和表格解析；
- Python 标准库：CSV、JSON、TXT；
- 现有 S3/MinIO storage adapter：统一读取原始文件和保存解析产物。

当前 PDF Adapter 已统一使用 `rapidocr_pdf`：普通 PDF 优先读取原生文本，无法提取文字的页面自动进入 RapidOCR。这样可以覆盖普通、扫描和混合 PDF，同时保留同一个 `ParsedDocument` 输出契约。PPTX 内嵌图片和图表的 OCR 仍应作为独立 Parser Adapter，未来也可以把云端 OCR 作为 PDF 的可选替代实现。

## 6. PostgreSQL 结构化数据通道

适合写入 PostgreSQL 业务表的数据包括：

- 产品名称；
- 价格、币种和价格类型；
- 尺寸、重量、数量等数学量；
- 供应商和联系方式；
- 日期、状态和销售渠道；
- 产品参数和可枚举属性。

处理流程：

```text
ParsedDocument
    ↓
Agent 提取结构化事实
    ↓
ImportProposal
    ↓
人工审核
    ↓
后端事务性写入业务表
```

示例：

```json
{
  "targetTable": "ProductPrice",
  "operation": "insert",
  "data": {
    "priceMin": 99,
    "currency": "USD"
  },
  "sourceFileId": "file-id",
  "sourceLocator": {
    "sheet": "产品报价",
    "row": 12
  },
  "confidence": 0.96
}
```

价格、库存、尺寸和日期等信息不能依赖向量相似度作为最终答案，必须从 PostgreSQL 精确查询。

## 7. Qdrant 语义数据通道

适合进入 Qdrant 的内容包括：

- 产品介绍；
- 使用说明和说明书；
- 产品特点和应用场景；
- 活动方案和市场分析；
- 大量自然语言描述。

Qdrant 中的每个向量点应携带最少以下 payload：

```json
{
  "fileId": "file-id",
  "knowledgeBaseId": "base-id",
  "workspaceId": "workspace-id",
  "content": "该产品适用于户外场景……",
  "locator": {
    "page": 3
  },
  "parserVersion": "1.0",
  "embeddingModel": "text-embedding-3-small",
  "contentHash": "sha256..."
}
```

Qdrant 只负责召回相关内容，不负责保存精确业务事实。查询“产品价格”时应查询 PostgreSQL；查询“产品适合什么场景”时才主要查询 Qdrant；混合问题需要同时查询两者。

当前项目已经存在 `KnowledgeChunk` 和 pgvector 相关能力。若正式采用 Qdrant，应明确唯一的向量事实来源，不要让 pgvector 和 Qdrant 在没有同步策略的情况下同时承担生产索引职责。可以保留 `KnowledgeChunk` 作为解析块和生命周期目录，再将 Qdrant 作为向量索引；也可以完全由 Qdrant 管理 chunk，但必须保留文件 ID、内容哈希和解析版本等审计元数据。

## 8. 文件、解析和入库状态

当前代码复用已有的 `KnowledgeFile.status` 表示解析任务状态：`pending` 表示已上传待解析，`processing` 表示解析中，`ready` 表示 ParsedDocument 已保存，`failed` 表示解析失败。新增的 `KnowledgeParsedDocument` 表保存中间态正文和 chunk 生成状态；结构化事实和未来向量索引仍需各自独立的状态。

```text
KnowledgeFile.status                    pending / processing / ready / failed
KnowledgeParsedDocument.chunkStatus     pending / processing / ready / failed
factsStatus                              pending / reviewing / approved / rejected / applied
vectorStatus                             pending / indexing / ready / failed / retired
```

### 8.1 KnowledgeParsedDocument

```text
id
workspaceId
knowledgeBaseId
fileId                  UNIQUE，关联 KnowledgeFile
fileHash
schemaVersion
parser
parserVersion
contentType
blockCount
warningCount
document                ParsedDocument JSONB
chunkStatus
chunkErrorMessage
chunkedAt
createdAt
updatedAt
```

这张表保留的是“确定性解析结果”，不是业务表，也不是向量数据库。它让开发人员可以审核和重跑切片；原始文件仍保存在 S3/MinIO，`KnowledgeFile` 是原文件和业务来源的锚点。

当前阶段暂不做文件版本管理：一个 `KnowledgeFile` 只对应一条当前的 `KnowledgeParsedDocument`，重新解析会更新这条中间态记录；知识库级列表接口返回当前知识库下所有文件的 ParsedDocument。后续如果需要历史版本，再单独引入逻辑文件和版本表。

当前 migration 为 `0013_knowledge_parsed_documents`。它只创建表和索引，不会尝试自动解析历史文件；历史文件需要在 UI 中重新点击“开始解析”。

未来如果单个 ParsedDocument 过大，可以把 `document` 移到 S3/MinIO，只在本表保存 artifact key、哈希和状态；API 和 chunk 流程保持不变。

未来的异步任务可以再引入 `KnowledgeParseJob`：

```text
parsed/{fileId}/{parserVersion}/document.json
parsed/{fileId}/{parserVersion}/text.json
parsed/{fileId}/{parserVersion}/structured.json
```

结构化入库草稿可以由 `KnowledgeImportProposal` 保存，至少包含：

```text
id
fileId
status
targetTable
payload
sourceLocator
confidence
createdBy
reviewedBy
```

## 9. 来源追踪、重解析和删除

所有结构化业务记录应保存：

```text
sourceFileId
sourceLocator
```

其中 `sourceLocator` 用于表达：

- XLSX/CSV：Sheet 和行号；
- PDF：页码和段落；
- PPTX：幻灯片和形状；
- JSON：JSON Path；
- TXT/Markdown：起止行号。

同一文件内容发生变化时，创建新的文件版本和解析任务，不直接覆盖旧解析结果。每次解析都记录 `parserVersion` 和 `contentHash`，保证可以重放和比较。

删除文件时：

1. 停止或取消该文件的未完成解析任务；
2. 删除或标记失效的结构化业务记录；
3. 根据 `fileId` 删除 Qdrant 中的向量点；
4. 删除 S3/MinIO 原始文件和解析产物；
5. 写入审计日志。

数据库中的 `sourceFileId` 外键可以用于级联删除结构化业务记录；对象存储和 Qdrant 的删除仍需由应用层显式执行。

## 10. 安全和运行约束

- 每次工具调用都验证 Workspace、KnowledgeBase 和当前用户权限；
- Agent 只能使用 `fileId`，不能访问任意对象存储路径；
- 限制文件大小、解压大小、解析时间和内存；
- XLSX/PPTX 不执行宏、不重新计算公式、不加载外部链接；
- 解析内容视为不可信文档内容，不能把文件中的指令当成 Agent 系统指令；
- 大文件使用流式读取、分页解析和后台 Worker；
- 解析失败要保存明确错误和解析器版本；
- 记录每次下载、解析、入库草稿和向量发布的操作者与时间。

开发环境可以暂时使用 FastAPI 后台任务；生产环境建议使用 Redis 队列和独立 Worker，避免阻塞 API 进程。

## 11. 推荐落地顺序

### 第一阶段：确定性解析

1. 从 S3/MinIO 通过 `KnowledgeFile.id` 安全读取文件；
2. 建立 Parser Registry；
3. 实现 TXT、Markdown、JSON、CSV、XLSX、PDF（`rapidocr_pdf`）、PPTX Adapter；
4. 统一输出 `ParsedDocument`；
5. 将解析结果写入 `KnowledgeParsedDocument`，不生成 `KnowledgeChunk`。

### 第一阶段 b：人工审核后生成 chunk

1. UI 从知识库级接口分页展示 `KnowledgeParsedDocument`；
2. 开发人员确认解析结果；
3. 手动调用 `POST .../chunks`；
4. 后端从已保存的 ParsedDocument 生成 `KnowledgeChunk`；
5. 只有 `chunkStatus = ready` 的文件参与向量搜索。

### 第二阶段：结构化入库草稿

1. Agent 读取分页后的 `ParsedDocument`；
2. 根据业务表白名单生成 `ImportProposal`；
3. 强制附带 `sourceFileId` 和 `sourceLocator`；
4. 开发人员审核；
5. 后端事务性写入 PostgreSQL。

### 第三阶段：语义索引

1. 对已审核的文本块进行语义切分；
2. 生成 embedding；
3. 写入 Qdrant 并保存文件、块和模型元数据；
4. 按 `fileId` 支持删除、重建和版本切换；
5. 实现 PostgreSQL 精确查询与 Qdrant 语义查询的混合 Agent 路由。
