# KnowledgeBase / KnowledgeFile 来源架构

## 目标

简化知识库来源模型：`KnowledgeBase` 只负责容器、工作区隔离和权限；`KnowledgeFile` 负责一个实际上传文件的元数据和存储位置。业务表不再把 `KnowledgeSource` 当作来源。

## 当前关系

```text
Workspace
└── KnowledgeBase                 容器、状态、权限边界
    ├── KnowledgeBaseGrant        用户/角色授权
    └── KnowledgeFile             一个上传文件 = 一个来源记录
        ├── KnowledgeParsedDocument 解析后的结构化文档
        └── KnowledgeChunk        从解析产物派生的文本片段（语义检索载体）

RealProductResearch.sourceFileId ─┐
ContentRecord.sourceFileId        ├──> KnowledgeFile.id
ProductDocument.sourceFileId      │
ProductOperation.sourceFileId     │
ProductPrice.sourceFileId         ┘
```

因此任何业务记录都能沿着：

```text
业务记录 → KnowledgeFile → KnowledgeBase → Workspace
```

`KnowledgeChunk.fileId` 关联 `KnowledgeFile.id`；解析文档到文本片段的派生由应用流程完成，不代表两者之间必须存在数据库外键。`KnowledgeParsedDocument` 保留解析结果，`KnowledgeChunk` 面向分块后的检索与引用；它们不是互相替代的来源记录。

## 向量检索选型决策

- 项目采用 PostgreSQL + pgvector 保存和检索语义向量，当前不另行引入 Qdrant。
- `KnowledgeFile` 仍是文件来源与权限边界；结构化事实和检索片段都应能追溯到来源文件及其位置。`KnowledgeParsedDocument` 是解析结果，检索链路可据此生成 `KnowledgeChunk`。
- `KnowledgeChunk` 是当前语义检索的分块载体；启用 embedding 后，向量保存在其 `embedding` 列中。结构化事实入库与语义检索入库是不同的派生路径，不应把原始解析文档本身误认为向量。
- 项目采用阿里云百炼 `qwen3.7-text-embedding` 生成文本向量，首期固定为 1024 维（模型默认值）。采用固定维度是因为 pgvector 列类型和 HNSW 索引在建库时即确定维度；1024 维低于普通 `vector` HNSW 的 2000 维上限，也便于以后在评测后调整。模型支持的其他维度不能仅通过改请求参数切换：须先迁移向量列和索引、清除旧模型向量，再重新生成；同一检索空间不可混用模型或维度。
- `KnowledgeParsedDocument` 是可追溯的解析产物，`KnowledgeChunk` 是可单独选择进行语义检索的分块。生成 chunks 不调用 embedding；管理者在文件详情中预览并勾选需要语义检索的 chunk 后，API 才调用模型并把向量及模型标识写入 pgvector。结构化事实入库仍是独立派生路径，可直接从 `KnowledgeParsedDocument` 产生并关联源文件，不依赖 `KnowledgeChunk`。

## 删除和可逆性

五张业务表的 `sourceFileId` 都是必填外键，并使用 `ON DELETE CASCADE`。删除一个 `KnowledgeFile` 时，会自动删除该文件产生的结构化业务记录；应用层随后删除本地/S3 文件对象。文件删除前应由管理接口执行确认和审计。

当前一条业务记录只有一个 `sourceFileId`。如果未来需要让同一条产品记录同时由多个文件支撑，再增加 provenance join table，而不是重新引入 `KnowledgeSource`。

## 迁移策略

`0012_knowledge_file_provenance.sql` 会：

1. 为五张业务表增加 `sourceFileId`；
2. 按工作区、旧来源对应的知识库、文件哈希/存储路径回填历史关系；
3. 将报价、运营记录从所属产品研究记录继承文件来源；
4. 校验所有历史记录都已经找到 `KnowledgeFile`，找不到时整个事务失败；
5. 增加外键、索引和非空约束；
6. 将旧 `sourceId` 改为可空兼容字段。它不再被新代码写入，`KnowledgeSource` 暂时保留。

`0015_knowledge_source_retirement.sql` 是后续的最终清理迁移：校验五张业务表都具有已验证的必填 `sourceFileId → KnowledgeFile` 外键；发现任何不属于三条已知旧 `sourceId` 关系的外键时立即失败；通过后移除三张根业务表的旧 `sourceId` 和 `KnowledgeSource`。历史迁移文件保留不改，迁移状态会把这些已被替代的历史步骤识别为完成，避免后续启动尝试重建旧表。

这次代码变更只新增并注册迁移，不会直接对任何数据库执行 `DROP TABLE`。部署时应先备份并确认目标环境迁移状态，再显式执行迁移。

## 导入约定

文件上传接口先创建 `KnowledgeFile`，返回 `fileId`。解析、人工审核和入库任务必须使用该 `fileId` 写入 `sourceFileId`，同时写入 `sourceSheet`、`sourceRow`。不要使用产品名称、文件显示名或旧 `sourceId` 作为关系键。
