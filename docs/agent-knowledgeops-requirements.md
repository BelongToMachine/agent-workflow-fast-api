# Agent KnowledgeOps 产品需求文档

## 1. 文档状态

- 状态：Draft / 需求探索阶段
- 产品阶段：ToB Web MVP
- 后续方向：ToC App、Local-first、BYOK
- 文档目的：记录产品定位、核心能力、阶段范围和验证标准，作为后续产品设计与开发的共同依据。

## 2. 产品概述

### 2.1 产品愿景

让企业和个人可以持续创建、治理、迭代自己的知识，并把这些知识可靠地转化为可使用的 AI Agent。

产品不是单纯的“上传文件后聊天”，而是一个面向 Agent 的知识运营层：

```text
导入知识 → 整理与合并 → 权限与版本治理 → 创建 Agent → 部署使用 → 根据反馈持续改进
```

### 2.2 产品定位

```text
Category:
Agent Knowledge Platform / Agent KnowledgeOps

Tagline:
One knowledge base. Every AI agent. Anywhere.

Value proposition:
Build, govern, and deploy AI agents grounded in your organization’s knowledge.
```

### 2.3 当前切入点

第一阶段聚焦 ToB Web 系统，为有大量产品文档、内部资料或客服知识的团队提供：

- 中心化知识库
- 文件快速导入和持续更新
- 团队、角色和知识库权限
- 基于知识库创建 AI 助手或客服 Agent
- 来源引用、回答反馈和知识迭代

第一版不同时面向所有企业、个人用户和所有渠道，而是先验证一个可量化的企业场景。

## 3. 市场判断与机会

企业对 Agent 的需求正在从“能不能做 Demo”转向“能不能可靠地进入工作流”。当前市场已经有通用 Agent Builder、企业搜索、AI 客服和办公套件，因此“通用聊天机器人”不是主要差异化方向。

相对更有机会的产品价值包括：

- KnowledgeOps：知识的导入、合并、版本、审核、发布和持续更新
- Agent QA：知识库更新后的回归测试、回答质量和工具调用评估
- Agent Governance：权限、审批、审计、人工接管和数据隔离
- Agent Operations：运行监控、异常诊断、未回答问题和成本分析
- Vertical Automation：针对一个行业或岗位的文档和流程自动化

外部参考：

- [McKinsey — The state of AI in 2025](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)
- [Microsoft Copilot Studio — Knowledge sources](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/knowledge-sources-overview)
- [Microsoft Copilot Studio — Agent evaluation](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-intro)
- [Atlassian Rovo — Agents](https://support.atlassian.com/rovo/docs/agents/)

## 4. 目标用户

### 4.1 MVP 目标用户

优先面向 10–200 人规模的 SaaS、技术服务或数字化团队，具备以下特征：

- 有产品文档、内部 Wiki、FAQ、操作手册或客服资料
- 团队成员经常重复回答相似问题
- 文档分散、过期或难以维护
- 希望使用 AI，但无法接受不可控的公开聊天机器人
- 需要按团队、角色或客户范围限制知识访问

### 4.2 优先场景

MVP 优先验证以下场景之一，不同时展开：

1. 产品文档驱动的 AI 客服 Agent
2. 企业内部知识和员工 onboarding Agent
3. 技术团队的项目、运维和 SOP 助手

建议首选“产品文档驱动的 AI 客服 Agent”，因为更容易衡量响应时间、人工转接率、问题解决率和知识缺口。

### 4.3 未来用户

- 个人知识管理用户
- 独立开发者和技术用户
- 需要本地数据存储的隐私敏感用户
- 希望自带模型 API Key 的高级用户

## 5. 产品原则

1. 知识是可运营资产，不是一次性上传的附件。
2. Agent 的回答必须能够追溯到知识来源。
3. 权限检查必须在数据访问层执行，不能只依赖 Prompt。
4. 高风险操作默认需要人工确认。
5. 先解决一个完整工作流，再扩展到更多渠道。
6. ToB Cloud 和 ToC Local-first 共享核心能力，但使用不同的产品包装和默认体验。

## 6. MVP 范围

### 6.1 P0：知识库生命周期

#### 文件导入

- 支持拖拽或选择文件上传
- 支持 PDF、Word、Excel、CSV、Markdown 等常见格式
- 显示文件解析和入库状态
- 失败时提供可理解的错误信息
- 支持文件 hash 或稳定 key，避免重复导入

#### 知识库管理

- 创建、重命名、归档和删除知识库
- 查看文件数量、状态、更新时间和版本
- 将多个文件加入同一个知识库
- 显示文件来源和文档数量
- 支持知识库级别的默认 Agent 配置

#### 合并与迭代

- 检测重复文件或相似内容
- 支持将多个来源合并到一个知识库
- 保留来源文件和版本信息
- 支持查看新增、删除和修改内容
- 支持草稿、审核中、已发布状态
- 支持回滚到上一版本

用户界面可以使用“合并、更新、发布”等词；内部实现可以保留类似 Git 的 version、diff 和 merge 概念。

### 6.2 P0：基于知识库的 Agent

- 为知识库创建一个 Agent
- 配置 Agent 名称、描述、系统指令和语气
- 指定 Agent 可以使用的知识库和文件范围
- 配置模型和基础参数
- 支持回答来源引用
- 支持“找不到答案时明确说明”
- 支持将 Agent 设为内部使用或公开访问
- 支持简单的 Web Chat 使用方式

### 6.3 P0：企业和权限

- Workspace / Organization 作为数据隔离边界
- 成员邀请和成员状态管理
- Owner、Admin、Member 等基础角色
- 用户级或角色级知识库授权
- Agent 继承或显式配置知识库权限
- 查询、文件、Agent 和管理操作分别执行权限检查
- 记录关键管理操作的审计日志

权限模型：

```text
Workspace
  ├── Members / Roles
  ├── Knowledge Bases
  │     ├── Files
  │     ├── Documents / Chunks
  │     └── Versions
  └── Agents
        ├── Knowledge scope
        ├── Tools
        └── Deployment settings
```

### 6.4 P1：知识质量和 Agent 反馈

- 用户对回答标记有帮助或无帮助
- 收集 Agent 未能回答的问题
- 将失败问题归类为：缺少知识、权限问题、检索问题、模型问题或工具问题
- 根据未回答问题生成知识更新建议
- 支持人工审核后将建议写入知识库
- 支持对关键问题建立固定测试集
- 知识库更新后运行基础回归测试

### 6.5 P1：Agent 评测和运行分析

- 上传或手动创建测试问题
- 对回答进行准确性、来源一致性和拒答质量评估
- 检查 Agent 是否调用了预期工具
- 记录模型、耗时、token、成本和错误
- 查看常见失败问题
- 查看人工转接和用户反馈
- 支持发布前测试和版本对比

### 6.6 P2：部署和集成

- 可嵌入网页的 Chat Widget
- REST API
- MCP Server / MCP Resource
- Slack、Microsoft Teams、Discord 等协作渠道
- Webhook 和事件通知
- 对接 Notion、Google Drive、Confluence、SharePoint、Zendesk 等数据源

“Anywhere”只有在至少提供 Web、API 和一个第三方渠道后，才作为主要营销承诺使用。

## 7. 关键用户流程

### 7.1 建立知识库

```text
创建 Workspace
→ 创建 Knowledge Base
→ 拖拽上传文件
→ 系统解析并显示状态
→ 检测重复或冲突内容
→ 预览来源和切片
→ 发布知识库
```

### 7.2 创建内部 Agent

```text
选择 Knowledge Base
→ 配置 Agent 目标和行为
→ 配置知识范围与权限
→ 使用测试问题验证
→ 发布为内部 Agent
→ 收集反馈和失败问题
```

### 7.3 创建客服 Agent

```text
选择产品知识库
→ 设置客服语气和拒答规则
→ 配置来源引用
→ 配置人工转接条件
→ 发布 Web Widget / API
→ 观察问题解决率和知识缺口
```

### 7.4 知识持续迭代

```text
Agent 产生未回答问题
→ 管理员查看问题聚类
→ 生成知识更新建议
→ 人工审核和修改
→ 发布新版本
→ 回归测试
→ 继续观察线上反馈
```

## 8. 非目标范围

当前阶段暂不做：

- 通用 AI Agent Marketplace
- 面向所有行业的自动化平台
- 多 Agent 自主协作网络
- 自研基础模型
- 大量第三方集成同时上线
- ToB 和 ToC 同时作为同一个入口推广
- 复杂的计费、营销自动化和 CRM 系统
- 全局启用纯静态导出，影响现有 API、认证和数据库能力

## 9. ToC / Local-first 后续方向

未来可以基于相同核心能力推出 Personal / Local 版本：

- 本地保存文件和索引
- 用户自填 API Key / BYOK
- 支持个人笔记、代码、PDF 和浏览器内容
- 桌面端或移动端使用
- 支持离线或低网络依赖
- 强调隐私和数据控制

ToC 版本不应简单复制 ToB 的组织、成员和审批流程，而应以“个人知识系统 + 私有 AI 工作流”为核心。

## 10. 关键指标

### 激活指标

- 用户从注册到创建第一个知识库的时间
- 用户从上传文件到得到第一个有效回答的时间
- 首次回答是否包含有效来源引用
- 用户是否完成第一个 Agent 发布

### 质量指标

- 回答有帮助率
- 来源引用正确率
- 未回答问题比例
- 人工转接率
- 知识库更新后的回归失败率
- 权限误放行和权限误拒绝次数

### 商业指标

- 每个 Workspace 的月活跃用户
- 每个 Workspace 的知识库和 Agent 数量
- 试用到付费转化率
- 每个 Workspace 的模型与存储成本
- 客服问题减少或响应时间改善
- 用户是否愿意将 Agent 放入真实工作流

## 11. MVP 验证标准

在大规模开发前，完成以下验证：

- 访谈至少 10 个目标团队
- 至少 3 个团队使用真实文件测试
- 至少 1 个团队将 Agent 放入真实客服或内部流程
- 至少 1 个团队愿意支付 Pilot 费用
- 至少 1 个核心场景可以用业务指标证明价值
- 用户能够说清楚为什么需要本产品，而不只是“想试试 AI”

## 12. 主要风险与应对

| 风险 | 影响 | 应对方式 |
|---|---|---|
| 文件上传加问答容易同质化 | 高 | 强化版本、合并、权限、反馈闭环 |
| 企业已有 Microsoft、Atlassian 或客服平台 | 高 | 先服务没有完整平台的小中型团队，或切入垂直场景 |
| 企业知识质量低 | 高 | 提供冲突检测、来源引用、审核和知识缺口分析 |
| Agent 输出不稳定 | 高 | 测试集、回归评测、人工审批和明确拒答 |
| ToB 销售周期长 | 中高 | 先做短周期 Pilot，人工协助导入真实数据 |
| 第三方集成复杂 | 中高 | MVP 先支持文件上传和一个部署渠道，逐步增加连接器 |
| ToB 与 ToC 需求分散 | 高 | 共享核心引擎，分开产品包装、官网和路线图 |

## 13. 推荐开发顺序

```text
阶段 1：Knowledge Base MVP
  文件导入、知识库、来源、版本、基础检索

阶段 2：Permission-aware Agent
  Agent 配置、知识范围、权限、引用、Web Chat

阶段 3：KnowledgeOps
  合并、diff、审核、发布、回滚、知识更新建议

阶段 4：Agent QA / Operations
  测试集、回归评测、反馈分析、失败诊断、成本监控

阶段 5：Deployment Layer
  API、MCP、Web Widget、Slack/Teams 等渠道

阶段 6：Personal / Local-first
  BYOK、本地存储、桌面端或移动端
```

## 14. 当前决策

当前继续推进该方向，但产品叙事从：

```text
AI knowledge base with agents
```

调整为：

```text
KnowledgeOps and quality control for AI agents.
```

第一版产品优先证明：

> 一个团队能否用这套系统，把真实知识整理成一个可靠、可控、可持续更新的 AI Agent，并在实际工作流中使用。
