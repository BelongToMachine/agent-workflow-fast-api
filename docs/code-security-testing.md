# MVP 内部试用最小上线门槛测试计划

## 1. 目的和适用范围

本文档是 Asianode FastAPI 后端面向公司员工小范围内测时的最小上线门槛，不是完整的渗透测试、极限压测或生产级合规审计。

目标是在投入有限的情况下，优先排除会导致以下结果的问题：

- 未认证用户可以访问接口；
- 用户、workspace 或角色之间发生越权；
- 开发配置、管理接口或密钥进入内测环境；
- 文件、Chat 或 Agent 请求可以轻易耗尽 CPU、内存或连接；
- 外部模型、PostgreSQL 或 Redis 故障导致请求无限等待或服务崩溃；
- 没有可执行的备份、回滚和故障处理方案。

所有安全测试、压测和故障注入只允许针对自己管理的本地或测试环境执行。不得使用生产数据、生产 Token 或生产 API Key。

## 2. 通过规则

上线前必须满足：

1. 所有 P0 项通过；
2. P1 项如果延期，必须记录负责人、风险和完成时间；
3. 没有未解释的认证绕过、跨 workspace 越权、密钥泄漏或数据破坏问题；
4. 内测规模、单实例限制、未启用 Redis 等已知约束必须写入发布记录。

任何 P0 项失败，停止上线。

## 3. 测试环境和运行方式

### 3.1 最小环境

使用独立的测试数据库和测试数据，不要连接线上或共享数据库。至少准备：

- 两个测试用户：User A、User B；
- 两个 workspace：Workspace A、Workspace B；
- viewer、employee、editor 和管理员测试角色；
- 测试用知识库、聊天记录和文件；
- 仅用于测试的 Bearer Token。

项目的 `compose.yaml` 可以启动本地 PostgreSQL 和 Redis：

```bash
make infra-up
```

但是 `make dev` 只启动 FastAPI，不会自动启动 Redis。没有配置 `REDIS_URL` 时，当前限流实现会使用进程内 fallback。

### 3.2 MVP 推荐配置

内测服务不得使用 development 的匿名访问或 `--reload`：

```env
ENVIRONMENT=staging
DEBUG=false
AUTH_REQUIRED=true
RATE_LIMIT_ENABLED=true
SQLADMIN_ENABLED=false
CORS_ORIGINS=https://内测前端域名
```

如果使用多 worker、多实例或聊天 SSE 断线恢复，还必须配置测试 Redis：

```env
REDIS_URL=redis://127.0.0.1:6379/0
RATE_LIMIT_REDIS_ENABLED=true
```

如果本次内测是单实例、单 worker，且不依赖 SSE 恢复，可以暂时不启用 Redis，但必须在发布记录中注明“限流为进程内模式”。

启动测试服务时关闭 reload：

```bash
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1
```

## 4. P0：上线前必须执行

### 4.1 代码、配置和依赖门槛

```bash
make lint
make test
uvx pip-audit
```

检查结果要求：

- pytest 全部通过；
- Ruff 无错误；
- 没有未处理的高危或严重依赖漏洞；
- Git 工作区、`.env`、日志和响应中没有真实密钥；
- `ENVIRONMENT` 不是 `development`；
- `AUTH_REQUIRED=true`；
- `DEBUG=false`；
- `SQLADMIN_ENABLED=false`；
- `CORS_ORIGINS` 是明确的内测前端 origin，不能使用 `*`；
- 开发 OIDC token 接口在 staging/production 不可用；
- 服务通过 HTTPS 或受 HTTPS 反向代理保护。

### 4.2 基础健康检查

```bash
curl -i http://127.0.0.1:8000/
curl -i http://127.0.0.1:8000/api/v1/healthz
```

验证：

- 健康检查返回预期状态；
- 数据库不可用时健康状态不会错误地报告为完全正常；
- 服务启动失败时不会带着不安全配置继续运行；
- 错误响应不包含 traceback、SQL、文件绝对路径、Token 或 API Key。

### 4.3 认证和授权

使用受保护的 models、products、content、chat 或 workspace 接口执行以下矩阵：

| 场景 | 预期 |
| --- | --- |
| 无 `Authorization` Header | 401 |
| `Bearer` 格式错误 | 401 |
| 随机或伪造 Token | 401 |
| 过期、错误签名、错误 issuer/audience 的 Token | 401 |
| 合法 Token 但无所需权限 | 403 |
| 合法 Token 和正确权限 | 正常响应 |

至少验证以下越权场景：

- User A 使用自己的 Token 请求 Workspace B；
- 把 URL、query 或 body 中的 `workspace_id` 改成 Workspace B；
- User A 替换成 User B 的资源 ID；
- 客户端提交其他 `user_id`、`role` 或身份字段；
- viewer 调用创建、修改、删除、成员管理或授权接口；
- User A 读取或删除 User B 的聊天、文件和建议记录。

预期是拒绝访问，且不得通过错误信息泄漏 B 的资源是否存在或其敏感字段。

项目已有的重点回归测试可以先执行：

```bash
uv run pytest -q \
  tests/test_auth.py \
  tests/test_workspace_access.py \
  tests/test_knowledge_access.py \
  tests/test_api_errors.py \
  tests/test_config.py
```

### 4.4 输入和文件上传

对普通 JSON、路径参数和 query 参数验证：

- 缺少必填字段、错误类型、非法 UUID、负数和超长值返回明确 4xx；
- 空字符串、Unicode、路径穿越字符和 SQL 注入字符不会导致 5xx；
- 重复提交不会产生无法清理的大量资源；
- 错误响应不泄漏内部实现细节。

对附件和知识库文件至少验证：

- 文件大小超过配置上限返回 413；
- PNG/JPEG 的声明类型与 magic bytes 不匹配时被拒绝；
- 不支持的扩展名、MIME 类型和损坏文件被拒绝或安全失败；
- 文件名包含 `../`、绝对路径和控制字符时不会写出存储目录；
- User A 不能读取或删除 User B 的文件；
- 5 个并发的大文件上传不会导致 OOM、进程崩溃或持续满 CPU。

文件大小限制不是并发内存上限。当前上传代码会读取接近配置上限的内容，因此必须观察多个并发上传时的 RSS。

### 4.5 限流、超时和外部依赖失败

验证普通接口、Chat 和文件接口：

- 超过限流后返回 429；
- 返回合理的 `Retry-After`；
- 不同用户的计数不会互相污染；
- 更换无关 Header 不能绕过限流；
- Chat、Agent 和 embedding 的外部服务发生超时、429、500、连接失败或非法响应时，接口能够在有界时间内失败；
- 错误响应和日志不包含外部模型 API Key。

外部模型性能测试使用 Mock 或本地可控服务，模拟正常响应、延迟、429、500 和超时。真实模型服务只做少量冒烟测试，不用真实 API 做高并发压测。

### 4.6 最小并发和资源测试

根据预计同时使用人数确定并发量，最低使用预计峰值的 2 倍；如果预计人数很小，至少测试 10 个并发请求。运行 10～30 分钟，覆盖：

- `/api/v1/models` 等轻量接口；
- 一个数据库查询接口；
- 一个需要权限判断的接口；
- Chat 或 Agent；
- 文件上传；
- 如果启用 SSE，再测试多个同时连接和客户端断开。

记录以下指标：

- 请求总数、吞吐量、p50/p95/p99 延迟；
- 4xx、5xx 和超时比例；
- Chat 的首字节时间和完整响应时间；
- Python 进程 CPU、RSS、文件描述符；
- PostgreSQL 连接数和错误；
- Redis 连接数和错误（如果启用）。

最小通过标准：

- 无未解释的 5xx；
- 预期负载下没有持续超时或连接池耗尽；
- 普通接口 p95 以 1 秒作为初始参考线，若业务基线不同则记录实际 SLO；
- 内存经过预热后没有持续上升趋势；
- CPU 没有长时间接近饱和；
- 文件上传和 SSE 断开后资源可以回收。

可使用 k6、Locust 或其他 HTTP 压测工具；工具不属于当前项目依赖，不应为了临时 MVP 测试改动业务代码。

### 4.7 备份、回滚和关闭服务

上线前必须确认：

- 数据库备份可以成功生成；
- 至少恢复一份测试备份并验证关键表；
- 数据库迁移有明确的回滚或前向修复方案；
- 可以快速关闭入口或回滚到上一版本；
- 已指定发现数据泄漏、持续 5xx 或资源耗尽时的处理人。

## 5. P1：按部署方式执行

以下项目不是所有单实例 MVP 都必须完成，但满足条件时必须执行：

| 条件 | 额外门槛 |
| --- | --- |
| 多 worker 或多实例 | 启用 Redis，验证多个进程共享限流计数 |
| 使用 SSE 断线恢复 | 启用 Redis，验证断开、重连、TTL 和清理 |
| 使用真实知识库解析 | 测试 PDF、XLSX 和大文件解析的 CPU、内存和失败恢复 |
| 员工会上传敏感文件 | 增加文件读取、删除、下载 URL 和 workspace 隔离测试 |
| 暴露给公司网络以外 | 增加 HTTPS、反向代理 body limit、来源限制和访问日志检查 |
| 预计并发快速增长 | 增加 30～60 分钟稳态压测和数据库连接池观察 |

Redis 相关集成测试必须显式指定测试地址，避免误连共享环境：

```bash
FASTAPI_TEST_POSTGRES_URL=postgresql://... \
FASTAPI_TEST_REDIS_URL=redis://127.0.0.1:6379/0 \
make test-integration
```

未启用 Redis 时，不应把 Redis 集成测试标记为通过；应记录为 `N/A`，并说明本次部署是单实例、进程内限流。

## 6. 可以延期到 MVP 之后

以下工作不作为小范围内部试用的第一道门槛，但在扩大用户范围、启用多实例或处理更敏感数据前应补齐：

- Schemathesis 全量 API fuzz；
- OWASP ZAP 全量扫描和人工渗透测试；
- 多小时 soak test；
- 破坏点和极限并发测试；
- 多实例故障切换和完整 chaos test；
- Prometheus/OpenTelemetry 全量可观测性；
- 真实外部模型服务的高并发压测。

延期项目必须建立 issue，记录负责人和目标日期，不能无限期遗忘。

## 7. 上线前检查表

- [ ] `make lint` 通过
- [ ] `make test` 通过
- [ ] `pip-audit` 没有未处理的高危或严重漏洞
- [ ] staging-like 配置启动成功
- [ ] `AUTH_REQUIRED=true`，没有匿名访问
- [ ] 开发 OIDC、SQLAdmin 和 debug 已关闭
- [ ] CORS 只允许内测前端 origin
- [ ] User A/B 和 Workspace A/B 越权测试通过
- [ ] viewer/editor/管理员边界测试通过
- [ ] 文件大小、类型、magic bytes 和路径测试通过
- [ ] 限流、429、Retry-After 和超时测试通过
- [ ] 外部模型使用 Mock 完成失败场景测试
- [ ] 预计峰值 2 倍并发运行 10～30 分钟无明显异常
- [ ] CPU、RSS、5xx、超时和数据库连接已记录
- [ ] Redis 是否启用、单实例限制和 SSE 能力已记录
- [ ] 备份恢复和回滚方案已验证
- [ ] 已指定内测期间的故障处理人

## 8. 测试结果记录模板

```text
测试日期：
代码版本/commit：
部署环境：local / staging-like
服务进程数：
Redis：enabled / disabled / N/A
数据库：测试实例标识
认证配置：

通过项：
失败项：
延期项及负责人：
测试并发：
p50 / p95 / p99：
5xx / timeout：
CPU 峰值：
RSS 峰值：
数据库连接峰值：

结论：GO / NO-GO
备注：
```
