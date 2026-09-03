# Asianode FastAPI + Redis 同机隔离 Docker 部署计划

## 1. 文档信息

- 状态：Draft，待执行前复核
- 目标环境：现有阿里云中继 VPS
- 部署模式：同一台宿主机、独立 Docker 项目、单 FastAPI 实例、单 worker
- 访问范围：第一阶段仅本机回环地址与 SSH 隧道；验证稳定后再考虑 WireGuard 内网访问
- 目标用户：公司内部 MVP 试用，常态 2～3 人并发，企业最大约 10 人
- 本文不执行任何服务器变更，只定义部署、验证和回滚步骤

## 2. 结论与推荐方案

本方案可以在现有中继 VPS 上执行，但只能视为“进程、文件、端口和资源的逻辑隔离”，不是物理隔离。FastAPI、Redis 和中继服务仍然共享宿主机内核、CPU、内存、磁盘与网络接口。

推荐方案：

1. 不修改现有 WireGuard、中继路由、HTTP 转发器、SFTP 转发和防火墙规则。
2. 优先使用 `rootless Docker`，由独立 Linux 用户 `asianode` 运行。
3. 使用独立目录、独立 Compose 项目名、独立 Docker 网络和独立数据卷。
4. FastAPI 第一阶段只发布到 `127.0.0.1:18000`，通过 SSH 隧道访问。
5. Redis 不发布任何宿主机端口，只允许 FastAPI 容器通过 Docker 网络访问。
6. FastAPI 使用单实例、单 worker，关闭 `reload`。
7. PostgreSQL 暂不部署在这台 2 GB VPS 上，使用独立的 staging 数据库。
8. 知识库文件导入、Embedding 和聊天附件第一阶段保持关闭，避免文件解析引起内存峰值。

条件性结论：

- 如果部署前 VPS 空闲可用内存不少于约 800 MiB、磁盘可用空间不少于 10 GiB，并且中继链路基线稳定，可以继续。
- 如果 Docker 安装会改变现有 iptables/FORWARD 行为，或者安装后 WireGuard 中继出现丢包、断连、出口变化，应立即停止并回滚。
- 如果必须在同机运行 PostgreSQL，建议先将 VPS 升级到至少 4 GB 内存，再重新评估。

## 3. 已知环境、假设与待确认项

### 3.1 已知环境

根据当前基础设施文档，现有服务器具备以下特征：

- 云厂商：阿里云
- 地域：中国大陆
- 操作系统：Alibaba Cloud Linux 3
- 角色：WireGuard 中继与策略路由中心
- WireGuard 宿主机隧道地址：`10.0.0.1`
- 当前存在策略路由和转发规则，属于本次部署的保护对象

当前已占用或应当保留的端口：

| 端口 | 协议 | 当前用途 | 本次处理原则 |
| --- | --- | --- | --- |
| 22 | TCP | SSH 管理 | 保持不变 |
| 80 | TCP | 现有 HTTP/WebDAV/Jellyfin 路由 | 禁止占用或修改 |
| 443 | TCP | 曾用于 HTTPS 尝试，现状需复核 | 本阶段不使用 |
| 2222 | TCP | 现有 SFTP 转发 | 禁止占用或修改 |
| 51820 | UDP | WireGuard 中继 | 禁止占用或修改 |
| 8443 | TCP | 曾用于 HTTPS 尝试，现状需复核 | 本阶段不使用 |
| 18000 | TCP | 计划中的 FastAPI 回环端口 | 部署前确认未占用 |
| 6379 | TCP | Redis 默认端口 | 只在容器网络内使用，不发布到宿主机 |

### 3.2 容量假设

本文按以下 MVP 容量假设编制：

- CPU：2 vCPU
- 内存：2 GB
- FastAPI 并发：常态 2～3，预期上限 10
- FastAPI worker：1
- Redis：仅保存限流计数和带 TTL 的 SSE 恢复片段
- PostgreSQL：独立远程 staging 实例
- 模型：调用外部模型 API，不在 VPS 上运行本地模型

CPU、内存、磁盘和网络带宽必须在执行前通过实机命令确认，不能只依赖历史购买信息。

### 3.3 当前项目部署缺口

当前项目不能直接把已有 Docker 文件复制到 VPS 后启动：

1. 当前 `Dockerfile` 只安装 FastAPI、Pydantic Settings 和 Uvicorn，没有安装 `asyncpg`、`redis`、`SQLAlchemy`、`httpx`、`boto3`、`pypdf`、`openpyxl` 等完整运行依赖。
2. 当前 `compose.yaml` 只定义 PostgreSQL 和 Redis，没有定义 FastAPI 服务。
3. 当前 Compose 将 `5432` 和 `6379` 发布到宿主机所有网卡，不适合公网 VPS。
4. 当前 `/api/v1/healthz` 只检查 FastAPI 进程能否响应，不检查 PostgreSQL、Redis 或模型服务。
5. 项目业务接口依赖 `POSTGRES_URL`；FastAPI + Redis 不能替代 PostgreSQL。

因此正式执行前需要新增服务器专用 Compose 文件，并修正生产镜像构建方式。

### 3.4 现有基础设施凭据风险

检查现有基础设施知识文档时发现其中包含明文服务凭据。本计划不复述这些值，也不在本次部署中自动修改现有服务。该问题应作为独立安全任务处理：限制文档仓库访问、将凭据移出版本控制，并在单独维护窗口内轮换相关凭据。为避免影响中继，本次 Docker 部署不得与凭据轮换合并执行。

## 4. 部署目标与非目标

### 4.1 本次目标

- 在同一 VPS 上启动独立的 FastAPI 和 Redis 容器。
- 保证中继服务的端口、路由表、WireGuard 配置和公网入口不发生变化。
- Redis 不对公网或宿主机其他服务开放。
- FastAPI 第一阶段不对公网开放。
- 配置 staging 级认证、CORS、限流与密钥管理。
- 完成项目 P0 测试、真实 Redis 连通测试、数据库连通测试和中继回归测试。
- 建立明确的停止、回滚和资源告警条件。

### 4.2 本次非目标

- 不部署多实例或多 worker。
- 不在本机部署 PostgreSQL。
- 不占用现有 80/443 入口。
- 不修改现有 WireGuard peer、策略路由或 NAT 规则。
- 不立即提供公网 API 域名。
- 不立即让 Vercel 服务端直接访问私网 FastAPI。
- 不启用知识库文件入库、Embedding、聊天附件和本地对象存储。
- 不实施 Kubernetes、Swarm、Prometheus 或复杂日志平台。

## 5. 最大风险：Docker 与中继网络的相互影响

### 5.1 风险说明

标准 rootful Docker 会创建 bridge、NAT 和 FORWARD 规则，并可能调整宿主机的转发策略。当前 VPS 是 WireGuard 中继并使用策略路由，因此“安装 Docker”本身就是本次部署风险最高的步骤，风险高于启动 FastAPI 或 Redis。

可能出现的问题包括：

- Docker 把 `FORWARD` 默认策略改为 `DROP`，导致 WireGuard 转发中断。
- Docker 新建的 NAT 链与现有中继 NAT 顺序产生冲突。
- 容器流量被错误送入现有 WireGuard 策略路由表。
- Docker 重启时重建规则，造成短暂网络抖动。
- 错误的 `docker compose down`、`docker system prune` 或全局 Docker 操作影响其他容器。

### 5.2 推荐选择：rootless Docker

优先使用 rootless Docker，原因是：

- Docker daemon 运行在普通用户空间。
- 默认不接管宿主机 iptables/FORWARD。
- 可以绑定 `18000` 这类非特权端口。
- 项目容器、镜像、网络和数据存放在独立用户目录。
- 停止 rootless Docker 不会停止宿主机其他用户的系统服务。

代价：

- 网络性能比 rootful bridge 略低，但对 2～3 人 FastAPI 内测影响很小。
- 需要系统支持 user namespace、RootlessKit、slirp4netns/fuse-overlayfs 等依赖。
- cgroup 资源限制能力需要实机确认。

### 5.3 备选选择：已有 rootful Docker

如果 VPS 已经安装并稳定运行 rootful Docker，可以使用独立 Compose 项目，但必须：

- 先保存 iptables、路由表、WireGuard 和现有容器基线。
- 使用独立项目名 `asianode-preview`。
- 不复用任何现有 Docker network 或 volume。
- 启动前后执行完整中继回归测试。
- 不设置全局 Docker daemon 参数，尤其不要未经评审直接设置 `iptables=false`。

如果 VPS 尚未安装 Docker，不应在没有阿里云控制台/VNC 兜底和维护窗口的情况下直接安装 rootful Docker。

## 6. 目标架构

第一阶段：

```text
开发者电脑
  -> SSH LocalForward
  -> VPS 127.0.0.1:18000
  -> rootless Docker published port
  -> FastAPI container :8000
       -> Redis container :6379（独立 Docker 网络）
       -> staging PostgreSQL（外部 TLS 连接）
       -> DeepSeek / Logto JWKS（正常出站 HTTPS）

现有中继链路
  -> WireGuard UDP 51820
  -> 现有策略路由 / NAT
  -> 保持完全不变
```

第二阶段，在第一阶段稳定后才评估：

```text
已接入 WireGuard 的内部客户端
  -> VPS WireGuard IP:18000
  -> FastAPI container :8000
```

第二阶段仍不开放 Redis，也不在阿里云安全组中向公网放行 `18000`。

## 7. 资源预算

### 7.1 推荐容器限制

| 服务 | CPU 上限 | 内存上限 | 进程限制 | 说明 |
| --- | ---: | ---: | ---: | --- |
| FastAPI | 1.0 vCPU | 768 MiB | 256 | 单 worker，主要等待数据库和模型 I/O |
| Redis | 0.25 vCPU | 256 MiB | 128 | 数据全部是可丢弃的限流/SSE TTL 数据 |

建议 Redis 内部限制：

- `maxmemory 128mb`
- `maxmemory-policy allkeys-lru`
- MVP 第一阶段可以关闭 AOF；Redis 重启后丢失限流计数和短期 SSE 片段是可接受的降级
- 如果后续要求 Redis 重启后仍保留 SSE 恢复数据，再启用 AOF 并评估磁盘写入和 rewrite 峰值

### 7.2 宿主机资源门槛

部署前 GO 条件：

- `MemAvailable` 建议不少于 800 MiB。
- 根分区可用空间不少于 10 GiB。
- 宿主机没有持续 swap 抖动。
- 中继空闲时 CPU load 没有持续接近 2 vCPU 上限。
- 当前服务日志没有持续增长或磁盘占满风险。

停止或回滚条件：

- FastAPI 启动后宿主机可用内存持续低于 300～400 MiB。
- VPS 出现 OOM kill。
- 中继链路丢包、握手异常、延迟明显上升或出口路径变化。
- 根分区使用率达到 85%。
- FastAPI 容器频繁重启或持续超过内存上限。

### 7.3 日志限制

每个容器使用 Docker JSON 日志轮转：

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

禁止无限制增长的默认容器日志。

## 8. 计划新增的部署文件

执行部署实现时，建议新增以下文件，不改动本地开发 Compose 的行为：

```text
asianode-fastapi/
├── Dockerfile
├── compose.yaml                    # 继续用于本地开发基础设施
├── compose.preview.yaml            # 新增：VPS 内测部署
├── .env.preview.example            # 新增：无真实密钥的模板
└── docs/
    └── ALIYUN_VPS_DOCKER_DEPLOYMENT_PLAN.md
```

服务器目录：

```text
/srv/asianode-preview/
├── app/                             # Git checkout 或发布包
├── .env.preview                     # chmod 600，不进入 Git
├── data/                            # 仅在需要持久化时使用
├── logs/                            # 如需宿主机日志导出
└── release-info                     # commit、镜像 tag、部署时间
```

rootless Docker 使用时，`/srv/asianode-preview` 应归 `asianode` 用户所有；也可以直接放在 `/home/asianode/asianode-preview`。

## 9. 生产镜像改造要求

### 9.1 当前镜像必须修复

生产镜像应满足：

- 使用 Python 3.12 slim 基础镜像。
- 根据 `pyproject.toml` 和 `uv.lock` 安装全部生产依赖。
- 使用冻结 lockfile，避免服务器每次构建得到不同依赖版本。
- 不安装 pytest、Ruff 等开发依赖。
- 不复制 `.env`、`.env.local`、测试缓存和 Git 元数据。
- 创建非 root 用户运行 FastAPI。
- 使用单 worker，不使用 `--reload`。
- 正确处理 SIGTERM，并给 SSE 请求预留优雅停止时间。
- 镜像内不包含 API Key、数据库密码或 Redis 密码。

推荐运行形态：

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

或者在 `pyproject.toml` 声明 FastAPI entrypoint 后使用 `fastapi run`。无论使用哪种方式，都必须保持单 worker。

### 9.2 镜像构建原则

- 镜像 tag 至少包含 Git commit 短 SHA。
- 发布前在 CI 或本地执行 lint、pytest 和依赖审计。
- 服务器部署时使用已验证的 commit，不从未提交工作区直接打包。
- 构建日志不得输出环境变量和密钥。
- 不在 Docker build argument 中传递运行时密钥。

## 10. Compose 目标形态

以下配置只展示目标结构，实际部署文件需要在执行阶段结合 rootless Docker 支持情况生成并验证：

```yaml
name: asianode-preview

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env.preview
    ports:
      - "127.0.0.1:18000:8000"
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    init: true
    cpus: 1.0
    mem_limit: 768m
    pids_limit: 256
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=64m,mode=1777
    stop_grace_period: 30s
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - >-
          import urllib.request;
          urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz', timeout=3)
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - asianode_internal

  redis:
    image: redis:7-alpine
    command:
      - redis-server
      - --appendonly
      - "no"
      - --maxmemory
      - 128mb
      - --maxmemory-policy
      - allkeys-lru
    restart: unless-stopped
    cpus: 0.25
    mem_limit: 256m
    pids_limit: 128
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - asianode_internal

networks:
  asianode_internal:
    name: asianode-preview-internal
```

关键限制：

- Redis 没有 `ports`，宿主机和公网都不能直接连接 `6379`。
- API 只绑定宿主机回环地址，不进入阿里云公网入口。
- 不使用 `network_mode: host`。
- 不复用中继服务现有 Docker 网络。
- 第一阶段功能开关关闭后，API 根文件系统可以设置只读；如果以后启用本地附件或知识库存储，需要只给指定目录挂载可写 volume。
- 如果启用 Redis ACL/密码，应使用独立 secret 文件或受限环境文件，不能把密码写进 Git。

## 11. staging 环境变量基线

服务器环境文件命名为 `.env.preview`，权限必须为 `600`。不得复制本地 `.env.local`，必须重新填写 staging 专用值。

示例：

```env
ASIANODE_APP_NAME=Asianode FastAPI Preview
ASIANODE_ENVIRONMENT=staging
ASIANODE_DEBUG=false

DEEPSEEK_API_KEY=<staging-model-api-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER_TIMEOUT_SECONDS=60

POSTGRES_URL=<dedicated-staging-postgres-url>
REDIS_URL=redis://redis:6379/0
RESUMABLE_STREAM_TTL_SECONDS=86400

CORS_ORIGINS=<explicit-preview-frontend-origin>

AUTH_REQUIRED=true
AUTH_ISSUER=<https-logto-issuer>
AUTH_AUDIENCE=<preview-api-audience>
AUTH_JWKS_URL=<https-logto-jwks-url>
AUTH_ALGORITHMS=RS256
AUTH_SECRET=<random-secret-at-least-32-characters>

RATE_LIMIT_ENABLED=true
RATE_LIMIT_REDIS_ENABLED=true
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60

SQLADMIN_ENABLED=false
SINGLE_WORKSPACE_MODE=true
DEFAULT_WORKSPACE_ID=<preview-workspace-id>
DEFAULT_WORKSPACE_ROLE=viewer

KNOWLEDGE_BASE_ENTITY_ENABLED=false
KNOWLEDGE_GRANTS_ENABLED=false
KNOWLEDGE_INGESTION_ENABLED=false
KNOWLEDGE_EMBEDDINGS_ENABLED=false
CHAT_ATTACHMENTS_ENABLED=false
```

要求：

- 不设置开发 direct token secret。
- 不使用 `development` 环境。
- CORS 不允许 `*`。
- Logto issuer 必须是 HTTPS。
- `AUTH_SECRET` 至少 32 字符，即使主要使用 RS256 校验也要满足当前启动检查。
- 模型 Key、数据库连接串和认证 secret 使用 preview 专用值。
- 如果未来使用 Redis 密码，`REDIS_URL` 应同步改为带认证的内部地址。

## 12. PostgreSQL 策略

### 12.1 推荐方案

使用独立 staging PostgreSQL，不在当前 2 GB 中继 VPS 内运行 PostgreSQL。

原因：

- PostgreSQL/pgvector 会额外消耗常驻内存和磁盘缓存。
- 数据库磁盘写入和 checkpoint 可能与中继、日志和 Redis 争用 I/O。
- 数据库与应用同机降低故障隔离程度。
- 当前服务器承担网络中继，不适合再成为唯一业务数据库节点。

### 12.2 数据库上线前要求

- 创建独立数据库、独立账号和最小权限。
- 不连接生产数据库，不复用本地开发数据库。
- 应用迁移前完成数据库备份。
- 按顺序审核并应用 `migrations/` 中的 SQL。
- 迁移完成后运行只读 migration status 和 integrity 检查。
- 不在 staging/production 上直接执行本地开发用途的 `make migrate-*` 命令；当前 runner 对远程和 staging/production 有保护，应通过正式、经过复核的 SQL 迁移流程执行。
- 记录数据库连接延迟、连接数上限和失败恢复方式。

## 13. 分阶段执行计划

### 阶段 0：只读预检

目标：确认容量、端口和中继基线，不做任何修改。

建议采集：

```bash
cat /etc/os-release
uname -a
nproc
free -h
swapon --show
df -h
df -i
uptime
ss -lntup
ip -brief address
ip rule show
ip route show table all
sudo wg show
systemctl --failed
docker version
docker compose version
```

同时记录：

- WireGuard 最近握手时间。
- 当前中继链路延迟、出口和连通性。
- 现有 HTTP 入口能否访问。
- 现有 SFTP 转发能否连接。
- 当前端口占用。
- 当前内存、swap、CPU load 和磁盘使用。
- VPS 是否已经安装 Docker，以及是 rootful 还是 rootless。

阶段 0 任何一项不清楚时，不进入安装阶段。

### 阶段 1：备份与恢复准备

在网络相关变更前完成：

1. 创建阿里云系统盘快照。
2. 保存 `ip rule`、所有路由表、iptables/nftables 和 WireGuard 当前状态。
3. 保存现有中继服务的 systemd unit 与配置备份。
4. 确认阿里云控制台/VNC 可以登录，避免 SSH 断开后无法恢复。
5. 记录中继测试步骤和预期出口结果。

建议备份对象：

```text
/etc/wireguard/
/etc/systemd/system/ 中与中继有关的 unit
iptables-save 输出
nft list ruleset 输出（如果使用 nftables）
ip rule show 输出
ip route show table all 输出
现有 HTTP/SFTP 转发器配置
```

备份中可能包含私钥和凭据，文件权限必须为 `600`，不得提交到 Git 或发送到聊天中。

### 阶段 2：建立独立运行用户

建立不具备中继配置写权限的用户 `asianode`：

- 不加入可修改 WireGuard 配置的专用组。
- 不把应用目录放进中继项目目录。
- rootless Docker 数据目录与现有服务目录分开。
- 环境文件只有 `asianode` 用户可读。
- 启用 user service linger，使 rootless Docker 可以在服务器重启后自动启动。

### 阶段 3：安装或确认 Docker

优先顺序：

1. 如果 rootless Docker 已可用，直接使用并验证。
2. 如果 Docker 未安装，按 Alibaba Cloud Linux 3 和当前 Docker 官方文档安装固定版本组件，再配置 rootless mode。
3. 不使用来源不明的一键安装脚本。
4. 如果 rootless prerequisites 不满足，暂停部署并重新评估，不自动切换成 rootful 安装。

rootless Docker 安装后验证：

```bash
docker info
docker compose version
systemctl --user status docker
docker run --rm hello-world
```

验证后立即重复阶段 0 的 WireGuard、中继、HTTP 和 SFTP 检查。任何回归都先停止 Docker，再排查，不继续部署应用。

### 阶段 4：准备发布版本

1. 选择已通过测试的 Git commit。
2. 确认工作区没有将 `.env`、Token 或数据库连接串纳入版本控制。
3. 修正 Dockerfile 完整依赖安装和非 root 运行方式。
4. 新增 `compose.preview.yaml` 和 `.env.preview.example`。
5. 运行 Compose 静态展开检查：

```bash
docker compose \
  --project-name asianode-preview \
  --env-file .env.preview \
  -f compose.preview.yaml \
  config
```

检查展开输出中不得出现意外公网端口、错误 volume 或真实 secret 日志。

### 阶段 5：部署 Redis

先单独启动 Redis：

```bash
docker compose \
  --project-name asianode-preview \
  --env-file .env.preview \
  -f compose.preview.yaml \
  up -d redis
```

验证：

```bash
docker compose \
  --project-name asianode-preview \
  -f compose.preview.yaml \
  ps

docker compose \
  --project-name asianode-preview \
  -f compose.preview.yaml \
  exec redis redis-cli ping

ss -lntup | grep 6379
```

预期结果：

- `redis-cli ping` 返回 `PONG`。
- 宿主机 `ss` 不应看到对外监听的 `0.0.0.0:6379`、`[::]:6379` 或 `127.0.0.1:6379`。
- Redis 内存上限和 maxmemory 配置生效。
- 中继链路保持正常。

### 阶段 6：构建并启动 FastAPI

构建：

```bash
docker compose \
  --project-name asianode-preview \
  --env-file .env.preview \
  -f compose.preview.yaml \
  build --pull api
```

启动：

```bash
docker compose \
  --project-name asianode-preview \
  --env-file .env.preview \
  -f compose.preview.yaml \
  up -d api
```

检查：

```bash
docker compose \
  --project-name asianode-preview \
  -f compose.preview.yaml \
  ps

docker compose \
  --project-name asianode-preview \
  -f compose.preview.yaml \
  logs --tail=200 api redis

curl --fail --show-error \
  http://127.0.0.1:18000/api/v1/healthz
```

预期结果：

- API 容器 healthy。
- 健康检查返回 `staging` 环境。
- API 只监听 `127.0.0.1:18000`。
- Redis 不监听宿主机端口。
- 日志中没有 secret、traceback、数据库认证失败或持续重试。
- 中继链路保持正常。

### 阶段 7：SSH 隧道内测

从测试电脑建立隧道：

```bash
ssh -N \
  -L 18000:127.0.0.1:18000 \
  <ssh-user>@<vps-host>
```

本机访问：

```bash
curl -i http://127.0.0.1:18000/api/v1/healthz
```

这一阶段不需要修改阿里云安全组，也不需要开放新的公网端口。

### 阶段 8：可选的 WireGuard 内网访问

只有阶段 7 稳定后才执行：

1. 确认需要访问 API 的员工设备已经安全加入 WireGuard。
2. 将 FastAPI 端口绑定从 `127.0.0.1:18000` 改为宿主机 WireGuard 地址，例如 `10.0.0.1:18000`。
3. 只允许明确的 WireGuard peer 地址访问该端口。
4. 不向阿里云公网安全组开放 `18000`。
5. 从公网网络验证 `18000` 不可达，从授权 WireGuard peer 验证可达。
6. 再次确认没有改变现有中继流量的策略路由和出口。

注意：如果 Vercel 前端页面要由浏览器直接请求私网 API，员工浏览器必须能路由到该 WireGuard 地址；同时 HTTPS 页面请求 HTTP API 还会遇到 mixed-content 限制。Vercel 服务端本身也无法直接访问 WireGuard 私网地址。前端正式接入前需要单独设计内部 HTTPS、BFF 或零信任入口，不属于本阶段。

## 14. 上线验证计划

### 14.1 代码门槛

在发布 commit 上执行：

```bash
make lint
make test
uvx pip-audit
```

要求：

- Ruff 通过。
- pytest 全部通过。
- 没有未处理的高危或严重依赖漏洞。
- 不包含真实密钥。
- Docker 镜像可以从空环境启动。

### 14.2 Redis 集成测试

至少验证：

- PING。
- 带 TTL 的 set/get/delete。
- 限流 key 自动过期。
- SSE chunk 写入、读取和 TTL。
- Redis 停止时 FastAPI 降级为进程内限流，普通聊天请求不应因此崩溃。

可以在独立测试环境显式运行：

```bash
FASTAPI_TEST_REDIS_URL=redis://redis:6379/0 \
make test-integration
```

如果测试命令在宿主机而不是 Compose 网络运行，应改用 `docker compose exec api`，不要为了测试发布 Redis 宿主机端口。

### 14.3 PostgreSQL 验证

至少验证：

- DNS 和 TLS 连接正常。
- migration status 全部符合预期。
- 关键表读取正常。
- 创建测试聊天、消息和用户映射正常。
- 数据库不可用时 API 请求能在合理时间内失败，不无限挂起。
- 使用独立测试数据，不写入生产或共享数据。

远程 integration target 只有经过明确复核后才能设置 `FASTAPI_ALLOW_REMOTE_INTEGRATION=1`，避免测试误连接共享数据库。

### 14.4 认证与权限验证

必须验证：

- 无 Token 请求业务接口返回 401。
- 过期、错误 issuer、错误 audience 和错误签名 Token 被拒绝。
- User A 不能访问 User B 的聊天和文件。
- Workspace A 不能越权访问 Workspace B。
- viewer、employee、editor 和管理员权限符合预期。
- staging 环境不可访问开发 OIDC token 接口。
- SQLAdmin 关闭。
- CORS 只允许明确的内测前端 origin。

### 14.5 并发与资源测试

最低测试：

- 10 个并发健康/普通 API 请求。
- 5 个并发短聊天请求，模型可以使用 mock 避免费用和外部波动。
- 2～3 个真实模型 SSE 请求。
- 运行 10～30 分钟，记录 p50、p95、p99、5xx、timeout、CPU 和 RSS。

通过标准：

- 没有 OOM、容器重启或连接泄漏。
- FastAPI RSS 峰值不触发 768 MiB 上限。
- Redis 内存稳定在 128 MiB maxmemory 以下。
- 中继链路的握手、延迟和吞吐没有明显退化。

### 14.6 中继服务回归测试

以下时点都要测试一次：

1. Docker 安装前。
2. Docker 安装后。
3. Redis 启动后。
4. FastAPI 启动后。
5. 10～30 分钟并发测试期间。
6. VPS 重启后。

检查项：

- WireGuard peer 最近握手时间正常。
- 原有远程工作流量出口与基线一致。
- 现有 HTTP 服务正常。
- 现有 SFTP 转发正常。
- 51820/UDP、80/TCP、2222/TCP 等端口状态没有改变。
- `ip rule`、关键路由表和中继 NAT 规则没有意外变化。

## 15. 监控与日常运维

### 15.1 MVP 最小监控

每日或故障时检查：

```bash
free -h
df -h
uptime
sudo wg show
docker stats --no-stream
docker compose \
  --project-name asianode-preview \
  -f compose.preview.yaml \
  ps
docker compose \
  --project-name asianode-preview \
  -f compose.preview.yaml \
  logs --since=30m --tail=500 api redis
```

观察指标：

- 宿主机 MemAvailable、swap 和 OOM 日志。
- API CPU、RSS、容器重启次数。
- Redis used_memory、evicted_keys 和连接数。
- API 5xx、429、模型 timeout 和数据库错误。
- 根分区与 Docker 数据目录容量。
- WireGuard 握手和中继延迟。

### 15.2 重启策略

- API 和 Redis 使用 `restart: unless-stopped`。
- rootless Docker 使用用户级 systemd 自动启动。
- 启用 linger 后执行一次 VPS 重启演练。
- 重启演练必须同时验证中继服务和 Asianode 服务。

## 16. 备份策略

### 16.1 必须备份

- 独立 staging PostgreSQL，按数据库服务提供的备份机制执行。
- `.env.preview` 的加密备份，不能进入 Git。
- 当前部署 commit、镜像 tag 和部署时间。
- 阿里云系统盘快照，至少在首次安装 Docker 前创建。

### 16.2 Redis 处理

当前 Redis 数据仅用于限流和短期 SSE 恢复，可视为可重建缓存。第一阶段关闭 AOF 时无需备份 Redis 数据。

### 16.3 本地文件存储

第一阶段关闭知识库文件和附件，因此不产生必须备份的本地业务文件。后续启用时必须单独增加持久卷、对象存储和恢复演练，不能默认写入容器可写层。

## 17. 回滚方案

### 17.1 应用级回滚

停止 Asianode 项目：

```bash
docker compose \
  --project-name asianode-preview \
  --env-file .env.preview \
  -f compose.preview.yaml \
  down
```

注意：

- 不添加 `-v`，避免删除未来可能存在的数据卷。
- 不执行 `docker system prune`。
- 不停止其他用户或其他 Compose 项目的容器。
- 不删除中继服务目录。

回滚到上一镜像：

1. 将 API 镜像 tag 改回上一个已验证 commit。
2. `docker compose up -d api`。
3. 重做健康、认证、数据库、Redis 和中继回归测试。

### 17.2 Docker 层回滚

rootless Docker 造成问题时：

1. 停止 `asianode-preview` Compose 项目。
2. 停止 `asianode` 用户的 Docker user service。
3. 重新验证 WireGuard、中继 HTTP 和 SFTP。
4. 不需要修改宿主机 iptables，除非预检证明它发生了变化。

rootful Docker 安装导致中继异常时：

1. 使用阿里云控制台/VNC，而不是只依赖 SSH。
2. 停止并禁用 Docker daemon。
3. 对比部署前保存的 iptables、路由和 FORWARD 状态。
4. 只在确认差异后恢复经过验证的规则备份。
5. 重新验证完整中继路径。

不要在没有控制台兜底时从远程 SSH 会话盲目执行整套 `iptables-restore`。

### 17.3 数据库回滚

- 数据库迁移必须有备份或前向修复方案。
- 应用回滚不等于数据库自动回滚。
- 破坏性 migration 不应与第一次同机部署同时执行。

## 18. GO / NO-GO 门槛

### 18.1 GO 条件

- [ ] 已确认 VPS 是目标主机，容量与假设一致
- [ ] 空闲可用内存和磁盘达到门槛
- [ ] 已创建阿里云系统盘快照
- [ ] 已保存 WireGuard、iptables、路由和现有服务基线
- [ ] 阿里云控制台/VNC 可用
- [ ] rootless Docker 可用，或已有 rootful Docker 已证明不影响中继
- [ ] Docker 安装后中继回归通过
- [ ] 当前 Dockerfile 完整安装生产依赖
- [ ] Compose 没有发布 Redis 端口
- [ ] API 第一阶段只绑定 `127.0.0.1:18000`
- [ ] 使用独立 staging PostgreSQL
- [ ] staging 认证、CORS、限流和 SQLAdmin 配置正确
- [ ] `make lint`、`make test`、依赖审计通过
- [ ] Redis、数据库、认证、SSE 和真实模型 smoke test 通过
- [ ] 10～30 分钟并发测试未影响中继
- [ ] 应用停止和镜像回滚演练通过
- [ ] VPS 重启后中继与 Asianode 都能恢复

### 18.2 NO-GO 条件

出现任一项即停止：

- Docker 安装或启动改变中继出口、WireGuard 连通性或策略路由结果。
- Redis 出现在公网或宿主机对外监听列表中。
- API 使用 development、匿名认证、`DEBUG=true` 或 wildcard CORS。
- API 容器无法在资源上限内稳定运行。
- PostgreSQL 指向生产、共享或未经备份的数据库。
- 真实密钥进入镜像、Git 或日志。
- 无法通过阿里云控制台恢复网络。
- P0 测试存在未解释失败。

## 19. 推荐执行顺序与停顿点

```text
只读预检
  -> 中继基线
  -> 阿里云快照
  -> rootless Docker
  -> 中继回归（停顿点 1）
  -> 仅启动 Redis
  -> 中继回归（停顿点 2）
  -> 启动 FastAPI，仅 loopback
  -> SSH 隧道 smoke test
  -> P0 + Redis/PostgreSQL integration
  -> 并发与资源测试
  -> 中继回归（停顿点 3）
  -> VPS 重启演练
  -> 观察 24 小时
  -> 再决定是否开放 WireGuard 内网访问
```

每个停顿点都必须先确认中继链路没有变化，才能继续下一步。

## 20. 发布记录模板

```text
部署日期：
执行人：
VPS 规格：
操作系统：
Docker 模式：rootless / existing rootful
Docker 版本：
Compose 版本：
代码 commit：
API 镜像 tag：
FastAPI worker：1
FastAPI 端口绑定：127.0.0.1:18000 / WireGuard IP:18000
Redis：enabled，no host port
Redis maxmemory：
PostgreSQL：staging 实例标识
认证 issuer/audience 标识：

部署前中继基线：
部署后中继结果：
lint/test/audit：
Redis integration：
PostgreSQL integration：
认证/越权测试：
并发测试：
p50 / p95 / p99：
API CPU 峰值：
API RSS 峰值：
Redis 内存峰值：
宿主机 MemAvailable 最低值：
5xx / timeout：

回滚演练：
已知限制：
结论：GO / NO-GO
```

## 21. 后续阶段

内部 loopback/SSH 模式稳定后，再分别规划：

1. WireGuard 内网员工访问。
2. 内部 HTTPS 和可信证书。
3. Vercel 前端与私网后端之间的 BFF/零信任入口。
4. 公网域名、备案与合规边界。
5. 启用知识库、Embedding、附件和对象存储。
6. PostgreSQL 备份恢复、监控和迁移自动化。
7. 从同机部署迁移到独立 VPS 的触发条件。

建议迁移到独立 VPS 的触发条件包括：

- 内部用户超过 10 人或并发显著增长。
- FastAPI 需要多 worker 或多实例。
- 启用大量 PDF/XLSX 文件解析。
- API 容器持续接近资源上限。
- 中继服务对稳定性要求提高。
- 需要公网 HTTPS、正式 SLA 或更严格的故障隔离。
