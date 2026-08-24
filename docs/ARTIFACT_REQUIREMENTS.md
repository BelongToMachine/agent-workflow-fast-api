# Artifact 功能需求文档

## 1. 文档状态

- 功能状态：**TODO**
- 产品阶段：MVP
- 适用架构：`asianodeagent-front`（Vite/React） + `asianode-fastapi`（FastAPI）
- 范围说明：本文只关注当前前后端直连 FastAPI 的链路，不依赖外层 Next.js BFF。

## 2. 功能结论

当前 Artifact 功能处于“半实现状态”：

> 项目已经实现了 Artifact 的文档存储 API、权限校验和前端编辑器 UI，但没有实现通过对话生成 Artifact 的完整前后端链路。因此，在当前 FastAPI + Vite 架构下，Artifact 功能还不能视为已完成。

当前对话中看到的报告、标题、段落和 Markdown 表格，都是普通 assistant message，不是 Artifact。

## 3. Artifact 定义

Artifact 是由对话或 Agent 生成、具有独立 `documentId`、可独立读取和编辑的持久化产物。

当前规划支持以下类型：

- `text`：可编辑的文本或 Markdown 文档
- `code`：可编辑的代码文件
- `sheet`：可编辑的 CSV/表格
- `image`：可预览的图片产物

普通聊天中的 Markdown、代码块或内联表格不自动视为 Artifact。只有在获得独立文档身份并通过文档接口持久化后，才算真正的 Artifact。

## 4. 当前已经实现的部分

### 4.1 FastAPI 文档存储 API

FastAPI 已提供：

- `GET /api/v1/documents`
- `POST /api/v1/documents`
- `DELETE /api/v1/documents`

已支持：

- `text`、`code`、`image`、`sheet` 类型
- 文档版本读取
- 新版本保存
- 手动编辑保存
- 按时间删除后续版本
- `document.read` 权限检查
- `document.write` 权限检查
- 用户和 workspace 隔离

相关代码：

- `app/api/routes/documents.py`
- `app/api/router.py`
- `tests/test_documents.py`

### 4.2 前端 Artifact UI

前端已经包含：

- Artifact 侧边编辑面板
- 文本编辑器
- Python 代码编辑器
- CSV 表格编辑器
- 图片预览
- 版本切换
- Diff 查看
- Restore
- 手动保存
- Artifact 工具栏和操作按钮

相关代码：

- `src/components/chat/artifact.tsx`
- `src/components/chat/artifactActions.tsx`
- `src/components/chat/versionFooter.tsx`
- `src/artifacts/text/client.tsx`
- `src/artifacts/code/client.tsx`
- `src/artifacts/sheet/client.tsx`
- `src/artifacts/image/client.tsx`

### 4.3 前端到 FastAPI 的文档路径适配

前端会将旧的 `/api/document` 路径映射到 FastAPI 的 `/api/v1/documents`，并自动附带 workspace 参数和 Logto Bearer Token。

相关代码：

- `src/lib/backend/directClient.ts`
- `src/lib/backend/request.ts`

## 5. 当前未实现或未接通的部分

### 5.1 缺少 Artifact 生成入口

FastAPI 当前 Agent 工具主要用于：

- 搜索产品
- 搜索内容运营数据
- 查询知识库

目前没有以下能力：

- `createDocument`
- `updateDocument`
- `generateArtifact`
- 根据用户指令选择 Artifact 类型
- 生成文档并返回 `documentId`

因此，用户在对话中要求“生成一个可编辑文档”时，FastAPI 只会返回普通文本。

### 5.2 缺少 Artifact SSE 数据流

前端已经等待以下数据事件：

- `data-id`
- `data-title`
- `data-kind`
- `data-clear`
- `data-textDelta`
- `data-codeDelta`
- `data-sheetDelta`
- `data-imageDelta`
- `data-finish`

但是 FastAPI 当前聊天流只发送：

- `start`
- `text-start`
- `text-delta`
- 工具调用事件
- `text-end`
- `finish`

因此前端的 `DataStreamHandler` 没有实际 Artifact 数据可以处理。

相关代码：

- 前端：`src/components/chat/dataStreamHandler.tsx`
- 后端：`app/api/routes/chat.py`

### 5.3 Artifact 元数据没有保存到聊天消息

FastAPI 保存 assistant 消息时，目前只保存：

```json
{
  "type": "text",
  "text": "..."
}
```

没有保存：

- `documentId`
- Artifact 类型
- Artifact 标题
- Artifact 相关消息 part

所以刷新页面或重新进入对话后，无法从聊天历史恢复 Artifact。

### 5.4 Artifact 预览没有接入当前消息渲染链路

前端存在 `DocumentPreview` 组件，但当前消息组件没有使用它，也没有现成的文档生成工具结果可以传给它。

相关代码：

- `src/components/chat/documentPreview.tsx`
- `src/components/chat/message.tsx`

当前消息渲染的主要内容仍然是：

- 普通文本
- `searchProductsTool`
- `searchContentTool`

### 5.5 遗留的 Next.js Server Artifact 代码没有接入 FastAPI

以下代码仍然存在：

- `src/lib/artifacts/server.ts`
- `src/artifacts/text/server.ts`
- `src/artifacts/code/server.ts`
- `src/artifacts/sheet/server.ts`

这些代码依赖旧的 Next.js Server Action、Drizzle 和旧 session 结构，不属于当前 FastAPI 运行时链路。它们不能替代 FastAPI 的 Artifact 生成实现。

### 5.6 前端编辑权限控制还不完整

后端会拒绝没有 `document.write` 权限的保存请求，但前端 Artifact 面板目前没有根据 `document.write` 隐藏或禁用编辑控件。

需要避免 viewer 用户看到可编辑状态后，在保存时才收到 403 错误。

### 5.7 FastAPI migration 没有明确创建 Document 表

FastAPI 的当前 migration 主要覆盖认证、workspace、knowledge 等能力。`documents.py` 直接查询现有的 `Document` 表，但没有对应的 FastAPI migration 创建该表。

需要确认：

- 生产数据库中的 `Document` 表由哪套 migration 创建
- FastAPI 是否需要接管该表的 schema migration
- `Document`、`Suggestion` 与用户/workspace 的外键和索引是否完整

## 6. 目标用户流程

```text
用户发送生成请求
        ↓
FastAPI 识别 Artifact 类型
        ↓
创建 documentId 和标题
        ↓
通过 SSE 推送 kind/title/id/content delta
        ↓
前端展示 Artifact 预览和编辑器
        ↓
FastAPI 持久化 Document 版本
        ↓
用户继续编辑或要求 AI 更新
        ↓
保存新版本并可恢复历史版本
```

## 7. MVP 功能需求

### 7.1 Artifact 创建

- 用户可以通过自然语言请求生成文本、代码或表格 Artifact。
- 后端必须返回唯一的 `documentId`。
- 后端必须返回 Artifact 类型和标题。
- 生成过程必须支持流式更新。
- 生成完成后必须保存文档内容。

### 7.2 Artifact 更新

- 用户可以在 Artifact 面板中手动编辑内容。
- 用户可以通过工具栏请求 AI 更新当前 Artifact。
- AI 更新必须生成新的文档版本。
- 手动编辑的权限必须由后端 `document.write` 决定。

### 7.3 Artifact 读取和恢复

- 重新进入对话时可以恢复 Artifact。
- 重新加载页面时可以根据 `documentId` 获取最新版本。
- 可以查看历史版本。
- 可以在历史版本之间切换。
- 可以恢复指定历史版本。

### 7.4 权限

- `document.read`：读取本人有权访问的 Artifact。
- `document.write`：创建、编辑、更新和恢复 Artifact。
- 后端必须始终执行 workspace、用户和权限校验。
- 前端必须根据权限隐藏或禁用对应编辑操作。

## 8. SSE 协议要求

Artifact 事件至少需要支持：

```text
data-id
data-title
data-kind
data-clear
data-textDelta / data-codeDelta / data-sheetDelta / data-imageDelta
data-finish
```

事件需要满足：

- 事件顺序稳定
- 中断后可以通过现有 stream resume 机制恢复
- 生成失败时返回明确错误
- 不把模型内部工具标记泄露给用户
- 最终内容和 `Document` 持久化结果一致

## 9. 验收标准

### 创建

- [ ] 输入“生成一份可编辑的文本报告”后，页面出现 Artifact 预览。
- [ ] 页面可以看到标题、类型和生成状态。
- [ ] 生成完成后，数据库存在对应 `Document` 记录。
- [ ] 浏览器网络中可以看到 Artifact SSE 事件和文档保存请求。

### 编辑

- [ ] editor/admin 可以编辑并保存 Artifact。
- [ ] viewer 不能保存 Artifact，且前端编辑入口被禁用或隐藏。
- [ ] AI 更新会产生新版本。
- [ ] 手动编辑不会破坏版本查询。

### 恢复

- [ ] 刷新页面后 Artifact 仍然可以恢复。
- [ ] 重新进入原对话后可以找到 Artifact。
- [ ] 可以切换历史版本并执行 Restore。

### 安全

- [ ] 不同用户无法读取其他用户的 Artifact。
- [ ] 不同 workspace 之间无法互相读取或修改 Artifact。
- [ ] 没有 `document.write` 权限的请求由后端拒绝。

## 10. 实现任务清单

- [ ] 设计并实现 FastAPI Artifact 创建/更新工具。
- [ ] 设计并实现 FastAPI Artifact SSE 事件。
- [ ] 将 Artifact 生成结果持久化到 `Document`。
- [ ] 将 Artifact 元数据写入聊天消息，支持历史恢复。
- [ ] 将 `DocumentPreview` 接入当前消息渲染链路，或实现等价组件。
- [ ] 将前端 Artifact 创建、打开、编辑和保存流程接到 FastAPI。
- [ ] 根据 `document.write` 完善前端权限控制。
- [ ] 明确 `Document` 和 `Suggestion` 的 migration 归属。
- [ ] 增加 FastAPI 与前端的端到端测试。
- [ ] 使用 Playwright 验证生成、编辑、刷新、恢复和权限拒绝流程。

## 11. 当前验证记录

- 前端 `bun run build`：通过。
- FastAPI 文档路由单测 `uv run pytest -q tests/test_documents.py`：6 个测试通过。
- Playwright 现有对话验证：只发现聊天消息请求，没有发现 `/api/v1/documents` 请求；页面内容为普通文本和内联 Markdown 表格。
