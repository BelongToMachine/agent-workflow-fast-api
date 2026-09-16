# KnowledgeBase / KnowledgeFile 来源架构

## 目标

简化知识库来源模型：`KnowledgeBase` 只负责容器、工作区隔离和权限；`KnowledgeFile` 负责一个实际上传文件的元数据和存储位置。业务表不再把 `KnowledgeSource` 当作来源。

## 当前关系

```text
Workspace
└── KnowledgeBase                 容器、状态、权限边界
    ├── KnowledgeBaseGrant        用户/角色授权
    └── KnowledgeFile             一个上传文件 = 一个来源记录
        └── KnowledgeChunk        解析后的文本片段（为未来 RAG 保留）

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
6. 将旧 `sourceId` 改为可空兼容字段。它不再被新代码写入，`KnowledgeSource` 表暂时保留用于回滚和历史数据库兼容。

这是一种安全的分阶段下线：先切换读写和约束，再观察历史数据和回滚窗口，最后才可以单独安排删除旧字段和旧表的清理迁移。

## 导入约定

文件上传接口先创建 `KnowledgeFile`，返回 `fileId`。解析、人工审核和入库任务必须使用该 `fileId` 写入 `sourceFileId`，同时写入 `sourceSheet`、`sourceRow`。不要使用产品名称、文件显示名或旧 `sourceId` 作为关系键。
