# Asianode 环境与 CI/CD 流程规范

## 1. 文档目的

本文定义 Asianode 的 staging 和 production 环境边界、域名规划、配置隔离、分支策略、CI/CD 流程、数据库迁移、回滚和上线验收标准。

本文是长期维护规范。具体的 GitHub Actions、VPS 初始化脚本和 Cloudflare 配置属于实施任务，应按照本文执行；现有的 `CICD_AUTOMATION_IMPLEMENTATION_PLAN.md` 是此前的 draft，后续必须按本文修订其中冲突的 staging 部署和数据库配置。

> **当前阶段说明（2026-09-12）**：CI/CD 管道尚未完成，staging 和 production 暂时采用 VPS 上的源码部署方式。源码部署是过渡方案；CI/CD 建成后，应切换为“CI 构建一次 Docker 镜像，staging 验证后使用同一镜像发布 production”的镜像部署方式。

> **当前 VPS 角色切换说明（2026-09-14）**：物理机器角色已重新分配：`sg-vps` 承载 production，原 production VPS（SSH 别名 `asianode-vps`）承载 staging。环境变量、数据库、Redis、文件存储、Compose project 和 Cloudflare Tunnel 必须随逻辑环境重新配置，不能通过直接重命名旧目录或 `.env` 文件完成切换。

## 2. 基本原则

1. staging 和 production 部署在不同 VPS 上，且不能共用运行栈、数据库、Redis、文件存储或密钥。
2. production 只能从受保护的 `main` 分支发布，并需要人工审批。
3. staging 用于完整联调和发布前验证；动态 PR Preview 只用于页面、构建和视觉检查。
4. CI/CD 建立后，production 发布必须复用已经构建并在 staging 验证过的镜像，不在 production 服务器重新构建源码；在当前过渡阶段，允许目标 VPS 拉取指定源码并在本机完成构建。
5. 数据库迁移必须显式执行，不能在应用启动时自动修改 production 数据库。
6. 所有环境变量和外部服务都必须明确标注所属环境，staging 永远不能持有 production 凭据。
7. 所有公网 API 只允许通过 HTTPS 和受控的反向代理或 Cloudflare Tunnel 暴露。

## 3. 环境定义

本文使用 `<domain>` 表示当前已经注册的主域名。例如当前 production API 如果使用 `api.asianodeatlas.com`，则 `<domain>` 为 `asianodeatlas.com`。

| 环境 | 前端地址 | API 地址 | 用途 |
| --- | --- | --- | --- |
| Production | `https://<domain>` | `https://api.<domain>` | 真实用户和正式数据 |
| Staging | `https://staging.<domain>` | `https://api-staging.<domain>` | 完整联调、验收和发布前验证 |
| PR Preview | 不部署 VPS，仅执行前端 CI 构建校验 | 不保证完整 API/登录联调 | 页面、构建和视觉检查 |

只有一个主域名不影响上述规划。DNS 可以在同一个主域名下创建多个子域名，不需要购买第二个域名。

### 3.1 当前仓库基线

- 后端是独立的 FastAPI 仓库，使用 Python 3.12、Docker 和 GitHub Actions。
- 前端是独立的 React/Vite 仓库，使用 Bun 构建、Nginx 容器提供静态文件，并部署在对应环境的 VPS 上。
- 当前仓库已经存在 `compose.preview.yaml`，使用回环端口 `18000`、独立 Redis 和外部 PostgreSQL。
- `/api/v1/healthz` 是进程存活检查，`/api/v1/readyz` 会额外检查数据库连接。
- 当前配置已经支持 `ENVIRONMENT`、`CORS_ORIGINS`、`AUTH_FRONTEND_URL`、`AUTH_SECRET` 等环境隔离变量。
- 当前数据库迁移工具会拒绝直接对 staging/production 执行本地迁移，需要在部署流程中使用经过审查的迁移方式。
- 当前 `.gitignore` 只覆盖 `.env` 和 `.env.local`，正式增加 production 配置前必须补充 `.env.*` 规则。

### 3.2 角色切换后的 VPS 映射

| 逻辑环境 | 新 SSH 别名 | 机器原角色 | 角色切换后的要求 |
| --- | --- | --- | --- |
| Production | `sg-vps` | 原 staging | 使用 production Compose、production secrets、production API/前端和 production 数据库连接；不能继续使用 `asianode_staging` 或 staging 密钥。 |
| Staging | `asianode-vps` | 原 production | 使用 staging Compose、staging secrets、staging API/前端和 staging 数据库；原 production 数据、密钥和 Tunnel 配置必须先隔离。 |

`sg-vps` 上现有的 rootless Docker、staging API/前端和本机 PostgreSQL 只是旧 staging 的运行状态，不能直接视为 production 已就绪。`asianode-vps` 上原有的 production 服务也不能直接视为 staging 已就绪。角色切换必须分别完成备份、停旧栈、建立新环境目录、生成对应环境文件、核对数据库连接和更新路由。

逻辑环境的数据库策略不变：production 使用正式 production 数据库（当前规划为 Supabase），由 `sg-vps` 上的 production API 访问；staging 使用 `asianode-vps` 上独立的本机 PostgreSQL。staging 的本机数据库迁移和用户数据不能自动复制到 production。

## 4. 目标部署拓扑

### 4.1 前端

前端与 FastAPI 使用独立的源码仓库和 Compose project。前端在目标 VPS 上从对应 commit 构建，构建产物只存在于不可变的 Docker image 中；Nginx 容器只提供静态文件，不连接数据库或 Redis。

| Git 事件 | VPS 行为 | 构建配置范围 |
| --- | --- | --- |
| PR / feature branch | 执行 `bun install --frozen-lockfile`、lint、build，不发布 VPS | 无环境 secret |
| 合并到 `staging` | 在 `asianode-vps` 创建前端 release，构建并启动 `asianode-staging-frontend` | `frontend.build.env` 的 staging 公共构建变量 |
| 合并到 `main` | 在 `sg-vps` 创建前端 release，经审批后切换 Tunnel upstream | `frontend.build.env` 的 production 公共构建变量 |

staging 和 production 分别绑定稳定域名 `https://staging.<domain>`、`https://<domain>`。不要使用临时动态域名完成登录联调，因为 CORS、session cookie 和 API URL 必须与固定环境一致。

### 4.2 后端

production 部署在新的 production VPS `sg-vps` 上，staging 部署在新的 staging VPS `asianode-vps` 上。两边都使用独立的 Compose project：

```text
asianode-staging
asianode-production
```

staging VPS `asianode-vps` 上建议端口规划：

```text
staging API     127.0.0.1:18000 -> container:8000

production VPS `sg-vps` 上继续使用 production 专用端口，例如：

production API  127.0.0.1:18000 -> container:8000
```

两套 Compose 必须分别拥有：

- 独立 API 容器和容器生命周期；
- 独立 Redis 容器、网络和数据目录；
- 独立 `.env.staging` / `.env.production`；
- 独立知识库和附件存储目录或 bucket；
- 独立日志、健康检查和部署记录。

正式 CI/CD 阶段的 production Compose 使用 `image:`，不使用 `build:`。当前 CI/CD 尚未建立时，staging 和 production 都从各自目标 VPS 的源码 checkout 使用 `build:`；接入正式 CI/CD 后再切换为 CI 构建的不可变镜像。

### 4.3 公网路由

如果使用 Cloudflare Tunnel，分别配置两条固定路由，指向不同 VPS：

```text
api.<domain>         -> production VPS `sg-vps` / http://127.0.0.1:18000
api-staging.<domain> -> staging VPS `asianode-vps` / http://127.0.0.1:18000
```

Tunnel、反向代理和公网 DNS 只负责转发，不负责环境选择。环境选择由 hostname 和对应的后端栈决定。

## 5. 环境隔离规范

### 5.1 数据库

staging 使用 `asianode-vps` 上的本机 PostgreSQL 18，不依赖外部托管数据库；production 由 `sg-vps` 上的 production API 连接正式 production 数据库（当前规划为 Supabase）。两套环境不得共用数据库连接字符串、数据库用户或数据库实例。

staging 的目标数据库和角色为：

```text
database: asianode_staging
role:     asianode_staging
```

无论 production 采用哪种数据库服务：

- staging 用户不能访问 production database；
- staging 的 migration 只能连接 staging；
- staging PostgreSQL 只监听回环地址和 `asianode-vps` 私网地址，并由 UFW/云防火墙拒绝公网 `5432/tcp`；
- production 发布前必须完成备份和 migration preflight；
- 不允许把 production 数据库 URL 放入 PR、Preview 或 staging secret；
- 生产数据复制到 staging 前必须脱敏，并记录复制时间和数据范围。

### 5.2 Redis

staging 和 production 使用不同的 Redis URL、实例或 database。优先使用不同 Redis 实例；如果必须共用实例，也要使用不同账号和明确的隔离 namespace。

生产发布默认只重建 API，不重启 production Redis，也不触碰 staging Redis。

### 5.3 文件和对象存储

知识库文件和聊天附件必须按环境隔离：

```text
staging bucket/prefix
production bucket/prefix
```

如果使用本地存储，必须挂载明确的持久化目录，并确认容器用户 UID `10001` 有权限。不能把业务文件留在容器可写层，否则重建 API 容器可能造成数据丢失。

如果暂时不能提供可靠的持久化存储，staging 和 production 都应保持文件上传功能关闭。

### 5.4 密钥和第三方服务

下列配置必须按环境使用不同值：

- `POSTGRES_URL`
- `REDIS_URL`
- `AUTH_SECRET`
- `DEFAULT_WORKSPACE_ID`
- `DEEPSEEK_API_KEY` 及其他模型服务密钥
- embedding 服务密钥
- S3-compatible storage credentials

staging 可以使用额度受限的模型 API key、较小的文件限制和较低的资源配额。production 密钥只保存在 production Environment 或 VPS 的受限文件中，不从 GitHub 仓库复制到服务器。

## 6. 域名、认证和浏览器安全

### 6.1 CORS 和前端回调

Production 后端的 `CORS_ORIGINS` 只允许 production 前端 origin；staging 后端只允许 staging 前端 origin。禁止使用 `*` 绕过配置问题。

示例：

```env
# staging
CORS_ORIGINS=https://staging.<domain>
AUTH_FRONTEND_URL=https://staging.<domain>

# production
CORS_ORIGINS=https://<domain>
AUTH_FRONTEND_URL=https://<domain>
```

当前认证只使用 FastAPI 的本地 session 模式。前端不保存或注入认证 secret，浏览器通过 API origin 的 HttpOnly session cookie 完成登录。

### 6.2 Session Cookie

当前服务使用 `__Host-asianode_session` HttpOnly Cookie。该 Cookie 不设置 Domain，只对当前 API host 生效，因此：

- staging 登录只应在 `api-staging.<domain>` 下产生 session；
- production 登录只应在 `api.<domain>` 下产生 session；
- 不要把 Cookie Domain 配置为 `.<domain>` 或其他跨环境范围；
- staging 和 production 必须使用不同的 `AUTH_SECRET` 和数据库。

两套环境都必须启用 Secure、HttpOnly、SameSite 和 CSRF 防护。staging 如果对公网开放，建议额外使用 Cloudflare Access 或 VPN 限制访问。

## 7. 分支和发布策略

### 7.1 分支模型

```text
feature/*
    -> Pull Request
    -> staging
    -> staging 验收
    -> main
    -> production 审批和发布
```

- `staging` 是稳定联调分支，允许团队合并已评审的功能。
- `main` 是 production 分支，禁止直接 push。
- PR 必须通过 CI 和代码 review 才能合并到 `staging`。
- `main` 只能通过 Pull Request 或明确的 release promotion 更新。
- 紧急修复也必须补回 `staging`，避免两个环境长期分叉。

前后端是两个仓库时，分别维护同名的 `staging` 和 `main` 分支，并在发布记录中记录前端 commit、后端 commit/image digest 及数据库 migration 版本。

### 7.1.1 当前源码部署方式

在 CI/CD 管道完成前，源码构建发生在准备部署的目标 VPS 上，不从本地 Mac 构建，也不从另一台环境复制源码或镜像。VPS 上允许从指定分支或 commit 拉取源码并部署。建议将源码 checkout 和运行配置分开：

```text
production VPS `sg-vps`:
/home/asianode/src/agent-workflow-fast-api/  # production 源码 checkout
/home/asianode/asianode-production/          # production Compose 和环境配置
/home/asianode/src/asianodeagent-front/      # production 前端源码 checkout
/home/asianode/asianode-production/frontend/ # production 前端 Compose 和发布配置

staging VPS `asianode-vps`:
/home/asianode/src/agent-workflow-fast-api/  # staging 源码 checkout
/home/asianode/asianode-staging/             # staging Compose 和环境配置
/home/asianode/src/asianodeagent-front/      # staging 前端源码 checkout
/home/asianode/asianode-staging/frontend/   # staging 前端 Compose 和发布配置
```

源码部署必须记录 commit SHA，并在部署后执行 health/readiness 和业务 smoke test。不得使用未记录的工作树直接部署，也不得让 staging VPS 和 production VPS 互相复制源码或环境配置。CI/CD 建成后，源码目录不再是运行依赖，Compose 改为使用固定的镜像 tag 或 image digest。

### 7.1.2 目标目录结构

两台 VPS 使用相同的目录模型，只替换环境名。`src` 是 Git 工作区，负责拉取源码；`releases` 是实际 Docker build context；`shared` 保存环境专属配置和持久化数据。真实 secret 不进入源码 release，也不进入 Git。以下树形图按逻辑合并展示；实际每台主机只创建自身对应的 environment root，不会在同一台机器上同时创建两套根目录。

```text
/home/asianode/
├── src/
│   ├── agent-workflow-fast-api/             # 后端 Git checkout
│   └── asianodeagent-front/                 # 前端 Git checkout
├── asianode-production/                    # production root on sg-vps
│   ├── releases/
│   │   └── <full-commit-sha>/               # git archive 或干净 checkout 的源码快照
│   │       ├── Dockerfile
│   │       ├── compose.production.yaml
│   │       ├── app/
│   │       ├── .deploy-commit              # 该 release 的 commit
│   │       └── release-info                # 来源、时间、构建和结果
│   ├── current -> releases/<full-commit-sha> # 当前成功 release 的指针
│   ├── shared/
│   │   ├── env/.env.production              # runtime 环境变量和 secret，0600
│   │   ├── build/build.env                  # 构建参数，不放 runtime secret
│   │   ├── storage/knowledge/
│   │   ├── storage/attachments/
│   │   ├── backups/
│   │   └── logs/
│   ├── deploy/
│   │   ├── deploy.sh
│   │   ├── rollback.sh
│   │   └── deploy.lock
│   └── frontend/
│       ├── releases/
│       │   └── <frontend-commit-sha>/        # 前端源码 release 快照
│       │       ├── Dockerfile
│       │       ├── compose.production.yaml
│       │       ├── deploy/nginx.conf
│       │       ├── .deploy-commit
│       │       └── release-info
│       ├── current -> releases/<frontend-commit-sha>
│       ├── shared/
│       │   └── build/frontend.build.env      # 公共前端构建变量，非 runtime secret
│       └── deploy/
│           ├── deploy-frontend-production.sh
│           └── deploy.lock
└── asianode-staging/                         # staging root on asianode-vps，同样的结构
    ├── releases/                             # 后端 release
    ├── current -> releases/<full-commit-sha>
    ├── shared/
    │   ├── env/.env.staging
    │   ├── build/build.env
    │   ├── storage/knowledge/
    │   ├── storage/attachments/
    │   ├── backups/
    │   └── logs/
    ├── deploy/
    │   ├── deploy-staging.sh
    │   └── deploy.lock
    └── frontend/
        ├── releases/
        │   └── <frontend-commit-sha>/
        │       ├── Dockerfile
        │       ├── compose.staging.yaml
        │       ├── deploy/nginx.conf
        │       ├── .deploy-commit
        │       └── release-info
        ├── current -> releases/<frontend-commit-sha>
        ├── shared/
        │   └── build/frontend.build.env
        └── deploy/
            ├── deploy-frontend-staging.sh
            └── deploy.lock
```

目录职责必须保持稳定：

- `src/` 可以更新，但不能作为正在运行服务的 bind mount。
- `releases/<sha>/` 一旦开始构建就不再修改；保留最近若干成功 release 供回滚。
- `current` 只指向最近一次通过健康检查的 release，不作为 Docker volume 挂载。
- `shared/env/`、`shared/storage/` 和 `shared/backups/` 永远位于 release 之外，发布时不能被源码归档覆盖。
- `app-backup-*`、`app-failed-*` 和无主的临时 `build.*` 不作为标准目录；如需保留现场，应统一放入 `releases/` 或 `shared/logs/` 并带 commit 和时间戳。

角色切换前，不直接重命名任一台机器当前正在使用的 `/home/asianode/asianode-preview` 或旧环境目录。应在新的逻辑环境 root 下建立新 release，验证成功后再切换反向代理和 Compose project；旧目录至少保留一个回滚周期。

原 production VPS（现在规划为 staging 的 `asianode-vps`）的旧目录可能还运行着独立的 SPA 静态服务（`spa_server.py` + `frontend-dist-clean-*`）。它不是新的 staging Docker release 的一部分；迁移时应先备份并隔离原 production 数据和 secrets，再用 staging 的 `frontend/releases/<frontend-commit-sha>/` 构建并验证 Nginx 容器，确认 staging 路由后再切换 upstream；旧进程至少保留一个回滚周期。

首次建立新角色目录时只创建下面的空目录骨架。production 骨架在 `sg-vps` 创建，staging 骨架在 `asianode-vps` 创建：

```text
/home/asianode/src/agent-workflow-fast-api/
/home/asianode/src/asianodeagent-front/
/home/asianode/asianode-production/releases/
/home/asianode/asianode-production/shared/env/
/home/asianode/asianode-production/shared/build/
/home/asianode/asianode-production/shared/storage/knowledge/
/home/asianode/asianode-production/shared/storage/attachments/
/home/asianode/asianode-production/shared/backups/
/home/asianode/asianode-production/shared/logs/
/home/asianode/asianode-production/deploy/
/home/asianode/asianode-production/frontend/releases/
/home/asianode/asianode-production/frontend/shared/build/
/home/asianode/asianode-production/frontend/deploy/

# 在 asianode-vps 上另外创建 staging 骨架
/home/asianode/asianode-staging/releases/
/home/asianode/asianode-staging/shared/env/
/home/asianode/asianode-staging/shared/build/
/home/asianode/asianode-staging/shared/storage/knowledge/
/home/asianode/asianode-staging/shared/storage/attachments/
/home/asianode/asianode-staging/shared/backups/
/home/asianode/asianode-staging/shared/logs/
/home/asianode/asianode-staging/deploy/
/home/asianode/asianode-staging/frontend/releases/
/home/asianode/asianode-staging/frontend/shared/build/
/home/asianode/asianode-staging/frontend/deploy/
```

在第一个 release 成功构建并通过健康检查前，不创建 `current` 指针；不复制或移动现有 `asianode-preview` 目录，不覆盖现有 `.env.preview`、容器、镜像、网络和备份。两台机器都必须按新的逻辑环境生成独立的 `.env.staging` 或 `.env.production`。

迁移旧部署时，旧环境文件只能先保存为候选配置，不能因为文件名从 `.env.preview` 改成 `.env.staging` 或 `.env.production` 就直接启用。必须逐项复核 `ENVIRONMENT`、数据库 URL、Redis、CORS、前端地址、认证密钥和文件存储，并为新角色生成正式环境文件后，才能启动对应 Compose project。

### 7.1.3 构建镜像与环境专属构建配置

两台机器都从目标 VPS 上的源码 release 构建镜像，但构建配置与运行配置分开。Compose 文件应将运行时环境文件和构建参数显式区分：

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        PYPI_INDEX_URL: ${PYPI_INDEX_URL:-https://pypi.org/simple}
    env_file:
      - ${RUNTIME_ENV_FILE}
```

production 的 `/home/asianode/asianode-production/shared/build/build.env` 可以是：

```env
RUNTIME_ENV_FILE=/home/asianode/asianode-production/shared/env/.env.production
PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

staging 使用自己的 `build.env`，至少定义自己的 `RUNTIME_ENV_FILE`。当前两个环境共用项目提交的 `uv.lock`，因此构建时使用同一套已锁定的依赖版本和下载来源。

项目根目录的 `pyproject.toml` 已声明阿里云为项目级默认 index：

```toml
[[tool.uv.index]]
name = "aliyun"
url = "https://mirrors.aliyun.com/pypi/simple/"
default = true
```

这意味着在本地、staging 和 production 中执行 `uv lock`、`uv sync` 或其他需要解析项目依赖的 uv 命令时，默认都会使用阿里云。当前 `uv.lock` 也已经在该 index 下重新生成：锁文件中的 registry、sdist 和 wheel 地址均指向 `mirrors.aliyun.com`，所以 Dockerfile 的 `uv sync --frozen` 会直接使用这些已锁定的阿里云地址，不再根据默认 PyPI 重新解析。

`PYPI_INDEX_URL` 仍保留在各环境的 `build.env` 中，用于通过 Compose build arg 配置 Dockerfile 内的 `pip install uv`，并兼容当前 Dockerfile 导出的 `PIP_INDEX_URL`/`UV_INDEX_URL`。它不属于 runtime `.env`，也不包含应用 secret。命令行参数或环境变量可以有意覆盖项目默认 index，但必须重新检查 lockfile 来源，不能让不同环境静默使用不同依赖来源。uv 的项目级 index 配置和优先级见官方文档。[uv index 配置](https://docs.astral.sh/uv/concepts/indexes/)

公共镜像地址不属于 secret，可以放在 `build.env`；如果将来使用需要认证的私有镜像，不能把用户名密码放进 Docker `ARG` 或 URL，应改用 BuildKit secret、keyring 或服务器上的受限凭据文件。

Dockerfile 的基础镜像和 Python 依赖是两条不同的下载链路。项目级 uv index 和 `PYPI_INDEX_URL` 只影响 Python 依赖，不影响 `FROM python:3.12-slim` 的 Docker 基础镜像来源。当前 production VPS `sg-vps` 使用 rootless Docker，因此必须检查执行部署用户所连接的 Docker daemon，而不能只检查 rootful Docker 的镜像缓存。

源码构建采用基础镜像的本地优先、远端 fallback 策略：

1. 从 release 内的 Dockerfile 识别基础镜像。
2. 使用当前 Docker daemon 执行 `docker image inspect <base-image>`。
3. 本机已有镜像时执行 `docker compose build api`，不使用 `--pull`，避免无谓访问 Docker Hub。
4. 本机没有镜像时执行 `docker compose build --pull api`，允许从配置的 registry 或远端仓库下载。
5. 若远端仓库仍然不可达，构建失败并保留 release；不能把不存在的基础镜像假装成已构建。

生产部署脚本会把 `base_image`、`base_image_source` 和 `build_pull` 写入 `release-info`。这些字段不包含密钥，便于判断本次构建是使用本地缓存还是远端下载。

前端使用独立的 `frontend.build.env`，因为 Vite 配置是在构建阶段编译进浏览器 bundle 的；Nginx 运行容器不读取数据库、Redis 或认证 secret。该文件只允许包含浏览器必须知道的公共值：

```env
FRONTEND_ENVIRONMENT=staging
# Current SSH-only staging build; replace with the staging API hostname after
# the staging Tunnel/domain is provisioned.
FRONTEND_API_URL=http://127.0.0.1:18000
VITE_WORKSPACE_ID=00000000-0000-0000-0000-000000000001
VITE_SINGLE_WORKSPACE_MODE=true
NEXT_PUBLIC_API_MODE=fastapi-direct
NEXT_PUBLIC_USE_FASTAPI_BACKEND=1
FRONTEND_BIND_ADDRESS=127.0.0.1
FRONTEND_HOST_PORT=18100
```

production 将 `FRONTEND_ENVIRONMENT` 改为 `production`，并将 `FRONTEND_API_URL` 改为 `https://api.<domain>`。前端项目当前使用 Bun 1.3.11 和 `bun.lock`，构建固定执行：

```text
bun install --frozen-lockfile
bun run lint
bun run build
```

前端 Dockerfile 使用 `oven/bun:1.3.11-alpine` 构建 `dist/`，再将产物复制到 `nginx:1.27-alpine`。Nginx 监听容器端口 `8080`，提供 `/healthz` 和 React Router 的 `/index.html` fallback。Compose 默认只绑定 VPS 回环地址 `127.0.0.1:18100`；Cloudflare Tunnel 只有在验证完成后才允许指向该端口。

前端发布同样使用本地优先、远端 fallback：部署脚本会同时检查 Bun 和 Nginx 两个基础镜像，只要有一个基础镜像不在目标 VPS 使用的 Docker daemon 中，就为本次 build 加上 `--pull`。脚本把两个基础镜像、来源和 `build_pull` 写入前端 release 的 `release-info`。

### 7.2 事件与动作矩阵

| 事件 | 必须执行 | 是否发布 production |
| --- | --- | --- |
| PR 创建或更新 | 后端测试、前端 lint/build、Docker build validation，不发布 VPS | 否 |
| 合并到 `staging` | 发布后端和前端 staging release，执行健康检查和业务 smoke test | 否 |
| 合并到 `main` | staging 验证后分别审批后端和前端 production release，再切换流量 | 审批后是 |
| `workflow_dispatch` | 指定后端/前端 SHA 重新部署或回滚 | 审批后是 |

## 8. CI/CD 流程规范

### 8.1 Pull Request CI

PR workflow 不得读取 production secrets，不得连接 production 数据库，不得向 GHCR 推送镜像。

后端至少执行：

```text
uv sync --frozen
ruff check .
pytest -m "not integration"
docker build
```

前端至少执行：

```text
bun install --frozen-lockfile
bun run lint
bun run build
```

第三方 GitHub Actions 应锁定到完整 commit SHA，并通过 branch protection 设置为 required checks。

### 8.2 Staging 发布

合并到 `staging` 后：

当前 CI/CD 尚未完成时，执行以下过渡流程：

1. 在 staging VPS `asianode-vps` 的 `/home/asianode/src/agent-workflow-fast-api` 拉取指定的 `staging` 分支或 commit。
2. 确认工作树干净，使用 `git pull --ff-only` 更新，记录完整 commit SHA。
3. 使用 `git archive` 将该 commit 导出到 `/home/asianode/asianode-staging/releases/<full-sha>/`，不带 `.git`、`.env` 和任何 secret。
4. 在 release 目录写入 `.deploy-commit` 和 `release-info`，确认 `shared/env/.env.staging`、`shared/build/build.env` 存在且权限正确。
5. 使用 staging 的 Compose project 在目标 VPS 构建并启动：

   ```bash
   STAGING_ROOT=/home/asianode/asianode-staging
   RELEASE="$STAGING_ROOT/releases/<full-sha>"

   BASE_IMAGE=python:3.12-slim
   if docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
     docker compose \
       --project-name asianode-staging \
       --env-file "$STAGING_ROOT/shared/build/build.env" \
       -f "$RELEASE/compose.staging.yaml" \
       build api
   else
     docker compose \
       --project-name asianode-staging \
       --env-file "$STAGING_ROOT/shared/build/build.env" \
       -f "$RELEASE/compose.staging.yaml" \
       build --pull api
   fi

   docker compose \
     --project-name asianode-staging \
     --env-file "$STAGING_ROOT/shared/build/build.env" \
     -f "$RELEASE/compose.staging.yaml" \
     up -d redis api
   ```

6. API 健康检查通过后，才更新 `current` 指针；失败时保留该 release 和日志，不覆盖上一份成功 release。
7. 执行本地 `/api/v1/healthz`、`/api/v1/readyz` 和公网 API 检查。
8. 执行登录、CSRF、核心业务请求、数据库读写和 Redis 相关 smoke test。
9. 记录部署时间、commit SHA、构建 index、配置变更和测试结果。

CI/CD 完成后，再切换为下面的镜像流程：

1. 使用当前 commit 构建 Docker 镜像。
2. 推送带完整 commit SHA 的镜像到 GHCR。
3. 使用 staging 专用 Compose project 拉取该镜像。
4. 只重建 staging API，除非有明确的 Redis 或基础设施变更。
5. 执行本地 `/api/v1/healthz`、`/api/v1/readyz` 和公网 API 检查。
6. 执行登录、CSRF、核心业务请求、数据库读写和 Redis 相关 smoke test。
7. 将后端镜像引用、前端 commit/image 信息和 migration 版本记录到部署结果中。

#### 8.2.1 前端 staging 发布

前端使用独立的源码 checkout 和 release 根目录：

```text
/home/asianode/src/asianodeagent-front/       # asianode-vps
/home/asianode/asianode-staging/frontend/    # asianode-vps
```

部署用户先在 release 之外创建 `frontend.build.env`，只写入公共构建变量，不写入 API key、数据库密码或其他 secret：

```text
/home/asianode/asianode-staging/frontend/shared/build/frontend.build.env
```

当前源码部署阶段执行：

```bash
BRANCH=staging \
  bash /home/asianode/src/asianodeagent-front/deploy/deploy-frontend-staging.sh
```

脚本会依次执行：

1. 检查 staging 前端构建变量和 rootless Docker；
2. 拉取并确认干净的 `staging` 分支，记录前端完整 commit SHA；
3. 使用 `git archive` 创建 `/home/asianode/asianode-staging/frontend/releases/<frontend-sha>/`；
4. 用 `oven/bun:1.3.11-alpine` 构建 Vite `dist/`，再生成 Nginx 静态服务镜像；
5. 启动 `asianode-staging-frontend`，检查容器 healthcheck 和 `http://127.0.0.1:18100/healthz`；
6. 检查通过后更新 `frontend/current` 并写入 `.deploy-commit`、`release-info`。

staging 前端默认只绑定 `127.0.0.1:18100`，不会自动创建 Cloudflare Tunnel 或公网路由。前端浏览器实际访问的 `FRONTEND_API_URL` 必须是浏览器可访问的 staging API 地址；当前 SSH-only 测试使用 `http://127.0.0.1:18000`，必须同时转发前端和 API 端口。由于前端 `18100` 与 API `18000` 是不同 origin，staging 的 `CORS_ORIGINS` 必须包含 `http://127.0.0.1:18100` 和 `http://localhost:18100`（取决于浏览器打开的地址），否则浏览器会出现 HTTP 200 但 JavaScript 读取失败的 CORS 错误。

### 8.3 Production 发布

当前 CI/CD 尚未完成时，production 也采用源码部署，但必须由人工执行，并完成数据库备份、commit SHA 记录、配置复核和发布后的 health/readiness 及业务 smoke test。production 目标 VPS 为 `sg-vps`，staging 目标 VPS 为 `asianode-vps`；两者必须分别从各自 VPS 上的源码 checkout 和环境配置部署，不能跨环境复制运行目录或 secret。

Production 的人工源码发布流程：

1. 在 production VPS `sg-vps` 的 `/home/asianode/src/agent-workflow-fast-api` 只拉取已经批准的 `main` commit，并确认工作树干净。
2. 将该 commit 导出到 `/home/asianode/asianode-production/releases/<full-sha>/`，不把 `.env.production`、数据库密码或其他 secret 放入 release。
3. 检查 production 的 `/home/asianode/asianode-production/shared/build/build.env`。`PYPI_INDEX_URL` 用于 Docker build；项目 `pyproject.toml` 和已提交的 `uv.lock` 共同保证 Python 依赖默认从阿里云获取。该配置不作为应用 runtime 环境变量。
4. 先执行数据库备份和 migration preflight，再构建镜像：

   ```bash
   PRODUCTION_ROOT=/home/asianode/asianode-production
   RELEASE="$PRODUCTION_ROOT/releases/<full-sha>"

   BASE_IMAGE=python:3.12-slim
   if docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
     echo "Using local base image: $BASE_IMAGE"
     docker compose \
       --project-name asianode-production \
       --env-file "$PRODUCTION_ROOT/shared/build/build.env" \
       -f "$RELEASE/compose.production.yaml" \
       build api
   else
     echo "Local base image missing; pulling: $BASE_IMAGE"
     docker compose \
       --project-name asianode-production \
       --env-file "$PRODUCTION_ROOT/shared/build/build.env" \
       -f "$RELEASE/compose.production.yaml" \
       build --pull api
   fi
   ```

5. 确认构建成功后，只停止旧 `asianode-preview` project 的 API/Redis，不执行全局 `docker compose down`、`docker system prune`，也不触碰无关容器、volume 或数据库：

   ```bash
   docker compose \
     --project-name asianode-preview \
     -f /home/asianode/asianode-preview/app/compose.preview.yaml \
     stop api redis

   docker compose \
     --project-name asianode-production \
     --env-file "$PRODUCTION_ROOT/shared/build/build.env" \
     -f "$RELEASE/compose.production.yaml" \
     up -d redis

   docker compose \
     --project-name asianode-production \
     --env-file "$PRODUCTION_ROOT/shared/build/build.env" \
     -f "$RELEASE/compose.production.yaml" \
     up -d --no-deps api
   ```

6. 通过容器、本机回环地址和公网域名三层检查后，更新 `current` 指针并写入完整 `release-info`。production 继续使用 `127.0.0.1:18000`，因此切换前必须先停止旧 `asianode-preview` API，再启动新的 `asianode-production` API；Cloudflare Tunnel 的 origin 不需要修改，但切换期间会有短暂中断。

当前过渡阶段使用 production VPS `sg-vps` 上的自动化脚本：

```bash
bash /home/asianode/asianode-production/deploy/deploy-production.sh
```

脚本会从 `main` 拉取源码、按完整 commit 创建或复用 release、运行 Compose 配置预检、构建 API 镜像、停止旧 `asianode-preview` API/Redis、启动新的 `asianode-production` Redis/API，并检查容器 healthcheck、本机 `healthz`/`readyz` 和公网 `api.<domain>/api/v1/healthz`。所有检查通过后才更新 `current`；停止旧服务后任一步失败，脚本会尝试恢复旧容器。脚本不执行数据库 migration，migration 必须作为独立的备份和 preflight 步骤完成。

`compose.production.yaml` 已进入 Git。脚本要求拉取的 commit 中存在该文件，并只使用 `git archive` 导出的 release 内版本，避免把服务器上的旧 Compose 模板与新源码混用。

#### 8.3.1 当前 production 手工部署命令

以下命令在 production VPS `sg-vps` 上以 `asianode` 用户、同一个 shell 会话执行。`<full-sha>` 必须替换为已经准备好的 release commit；例如当前 release 使用 `d653130cb971042fc9a580ce7dda12091abcdb68`。该流程只切换指定的 Asianode 服务，不执行全局清理。

1. 设置 release 变量并确认文件存在：

   ```bash
   PRODUCTION_ROOT=/home/asianode/asianode-production
   SHA=<full-sha>
   BUILD_ENV="$PRODUCTION_ROOT/shared/build/build.env"
   RELEASE="$PRODUCTION_ROOT/releases/$SHA"

   test -f "$RELEASE/Dockerfile"
   test -f "$RELEASE/compose.production.yaml"
   test -f "$BUILD_ENV"
   test -f "$PRODUCTION_ROOT/shared/env/.env.production"
   ```

2. 验证 Compose 展开结果。该命令不会启动服务：

   ```bash
   docker compose \
     --project-name asianode-production \
     --env-file "$BUILD_ENV" \
     -f "$RELEASE/compose.production.yaml" \
     config -q
   ```

3. 构建 API image。当前 `python:3.12-slim` 已在 production VPS `sg-vps` 的 rootless Docker 中缓存，因此优先不访问 Docker Hub；如果本机没有基础镜像，才使用 `--pull` 下载。`BUILDKIT_PROGRESS=plain` 配合 Dockerfile 中的 `uv sync -vv` 输出构建和依赖请求细节：

   ```bash
   BASE_IMAGE=python:3.12-slim

   if docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
     echo "Using local base image: $BASE_IMAGE"
     BUILDKIT_PROGRESS=plain docker compose \
       --project-name asianode-production \
       --env-file "$BUILD_ENV" \
       -f "$RELEASE/compose.production.yaml" \
       build api
   else
     echo "Local base image missing; pulling: $BASE_IMAGE"
     BUILDKIT_PROGRESS=plain docker compose \
       --project-name asianode-production \
       --env-file "$BUILD_ENV" \
       -f "$RELEASE/compose.production.yaml" \
       build --pull api
   fi
   ```

   构建成功后不要立即运行 `docker compose down` 或 `docker system prune`。如果本次 release 包含数据库 migration，必须在停止旧服务前完成已审查的备份和 migration preflight；部署脚本不会自动执行 migration。

4. 停止旧的 API 和 Redis。因为新旧 Compose 都使用 `127.0.0.1:18000`，这一步会造成短暂中断；Cloudflare Tunnel 的 upstream 不需要修改：

   ```bash
   docker compose \
     --project-name asianode-preview \
     -f /home/asianode/asianode-preview/app/compose.preview.yaml \
     stop api redis
   ```

5. 启动新的 production Redis 和 API。Redis 使用 Compose 中的预构建 `redis:7-alpine` image，不需要执行 `build`；API 才使用刚刚构建的本地 image：

   ```bash
   docker compose \
     --project-name asianode-production \
     --env-file "$BUILD_ENV" \
     -f "$RELEASE/compose.production.yaml" \
     up -d redis

   docker compose \
     --project-name asianode-production \
     --env-file "$BUILD_ENV" \
     -f "$RELEASE/compose.production.yaml" \
     up -d --no-deps api
   ```

6. 检查容器状态、本机 health/readiness 和公网 health：

   ```bash
   docker compose \
     --project-name asianode-production \
     --env-file "$BUILD_ENV" \
     -f "$RELEASE/compose.production.yaml" \
     ps

   API_CONTAINER="$(docker compose \
     --project-name asianode-production \
     --env-file "$BUILD_ENV" \
     -f "$RELEASE/compose.production.yaml" \
     ps -q api)"

   docker inspect \
     --format '{{.State.Health.Status}}' \
     "$API_CONTAINER"

   curl --fail --silent --show-error \
     http://127.0.0.1:18000/api/v1/healthz
   curl --fail --silent --show-error \
     http://127.0.0.1:18000/api/v1/readyz
   curl --fail --silent --show-error \
     https://api.asianodeatlas.com/api/v1/healthz
   ```

   容器必须为 `healthy`，三个 HTTP 检查都成功后，继续执行下一步；之后还要完成人工登录、CSRF、核心业务、数据库读写和 Redis smoke test。

7. 所有检查通过后，才更新成功 release 指针和发布记录：

   ```bash
   ln -sfn "$RELEASE" "$PRODUCTION_ROOT/current"
   sed -i 's/^status=.*/status=successful/' "$RELEASE/release-info"
   printf 'deployed_at=%s\n' \
     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
     >> "$RELEASE/release-info"

   readlink "$PRODUCTION_ROOT/current"
   sed -n '1,30p' "$RELEASE/release-info"
   ```

8. 任一步失败时，保留失败 release 和日志，停止新服务并恢复旧服务：

   ```bash
   sed -i 's/^status=.*/status=failed/' "$RELEASE/release-info"

   docker compose \
     --project-name asianode-production \
     --env-file "$BUILD_ENV" \
     -f "$RELEASE/compose.production.yaml" \
     stop api redis

   docker compose \
     --project-name asianode-preview \
     -f /home/asianode/asianode-preview/app/compose.preview.yaml \
     start api redis
   ```

   回滚后确认旧 API 已恢复 healthy，再调查新 release；不要删除 release、镜像、volume 或旧 Compose project 的容器。

CI/CD 建成后，production 再切换为复用 staging 已验证镜像的发布流程。

Production 发布必须满足：

- `main` 已通过 branch protection；
- production Environment 至少一名 reviewer 审批；
- 使用 staging 已验证的同一个镜像 digest；
- 当前 production 数据库已有备份；
- migration 已在 staging 成功验证；
- 部署具有串行 concurrency，不能同时执行多个 production deploy。

发布动作：

1. 拉取指定 image digest，不使用 `latest`。
2. 如有数据库变更，先执行已审查的 production migration。
3. 执行 `docker compose up -d --no-deps api`，不执行 `compose down`，不清理无关容器或 volume。
4. 执行容器内、本机回环地址和公网域名三层健康检查。
5. 执行登录、核心业务、数据库和 Redis smoke test。
6. 成功后记录当前 image digest 为 `last-successful-image`。

#### 8.3.2 前端 production 发布

production 前端与后端分别发布，目标 VPS 为 `sg-vps`，使用独立的前端 root：

```text
/home/asianode/src/asianodeagent-front/
/home/asianode/asianode-production/frontend/
```

确认 `frontend.build.env` 中的 `FRONTEND_ENVIRONMENT=production` 和 `FRONTEND_API_URL=https://api.<domain>` 正确后执行：

```bash
BRANCH=main \
  bash /home/asianode/src/asianodeagent-front/deploy/deploy-frontend-production.sh
```

该脚本不会停止旧的 `spa_server.py`，也不会修改 Cloudflare Tunnel。新 Nginx 容器在 `127.0.0.1:18100` 健康检查通过后，再由人工将 production 前端 hostname 的 Tunnel upstream 切换到该端口；切换完成并通过登录和核心页面 smoke test 后，旧静态服务才进入回滚保留周期。

### 8.4 镜像命名

推荐使用：

```text
ghcr.io/<org>/asianode-fastapi:sha-<full-git-sha>
```

长期生产部署优先使用 digest：

```text
ghcr.io/<org>/asianode-fastapi@sha256:<digest>
```

`latest` 只能作为人工浏览别名，不得用于 production 发布或回滚。

## 9. 环境配置文件规范

仓库只提交示例文件，不提交真实配置：

```text
.env.staging.example
.env.production.example
```

真实配置只存在于对应部署环境，例如：

```text
VPS: /home/asianode/asianode-staging/shared/env/.env.staging
VPS: /home/asianode/asianode-production/shared/env/.env.production
```

真实 runtime 文件权限应为 `0600`，所有者为部署用户。构建参数文件不包含密钥，可以是 `0640`，但仍只放在目标 VPS。`.gitignore` 应至少包含：

```gitignore
.env
.env.*
!.env.example
!.env.*.example
```

`build.env` 不属于应用 runtime `.env`，也不复制到 Docker 镜像。它只提供 Compose build interpolation，例如：

```text
/home/asianode/asianode-staging/shared/build/build.env
/home/asianode/asianode-production/shared/build/build.env
```

前端使用独立的 build env，放在前端 release 根目录之外：

```text
/home/asianode/asianode-staging/frontend/shared/build/frontend.build.env
/home/asianode/asianode-production/frontend/shared/build/frontend.build.env
```

前端 build env 只允许包含会被 Vite 编译到浏览器 bundle 的公共配置：

```env
FRONTEND_ENVIRONMENT=staging
FRONTEND_API_URL=https://api-staging.<domain>
VITE_WORKSPACE_ID=00000000-0000-0000-0000-000000000001
VITE_SINGLE_WORKSPACE_MODE=true
NEXT_PUBLIC_API_MODE=fastapi-direct
NEXT_PUBLIC_USE_FASTAPI_BACKEND=1
FRONTEND_BIND_ADDRESS=127.0.0.1
FRONTEND_HOST_PORT=18100
```

前端不能把 `POSTGRES_URL`、`REDIS_URL`、`AUTH_SECRET`、模型 API key 或任何其他 secret 放进这个文件。当前前端生产构建采用 direct mode，因此 `FRONTEND_API_URL` 必须是浏览器可访问的 API origin；它不是 Docker 容器内部地址。当前 SSH-only staging 使用浏览器本机的 `http://127.0.0.1:18000`，需要同时转发 API 和前端端口；启用 staging Tunnel/domain 后，重新构建并改为 `api-staging.<domain>`，production 使用 `api.<domain>`。

staging 配置示例：

```env
APP_NAME=Asianode FastAPI Staging
ENVIRONMENT=staging
DEBUG=false
AUTH_REQUIRED=true
AUTH_MODE=local_session
POSTGRES_URL=<staging-database-url>
REDIS_URL=<staging-redis-url>
CORS_ORIGINS=https://staging.<domain>
AUTH_FRONTEND_URL=https://staging.<domain>
AUTH_SECRET=<staging-only-random-secret>
DEFAULT_WORKSPACE_ID=<staging-workspace-uuid>
SQLADMIN_ENABLED=false
```

production 使用相同的变量集合，但必须替换为 production 数据库、Redis、域名、workspace 和密钥。生产环境必须 `DEBUG=false`、`AUTH_REQUIRED=true`、启用限流，并禁止启用 SQLAdmin 预览。

## 10. 数据库 Migration 规范

数据库 migration 流程：

```text
SQL review
    -> staging preflight
    -> staging apply
    -> staging smoke test
    -> production backup
    -> production preflight
    -> production apply
    -> production deploy
```

要求：

- migration 必须可重复执行或明确检测已执行状态；
- 破坏性 migration 必须单独评审、备份并安排维护窗口；
- 不允许应用启动自动执行 migration；
- 不允许在本地命令中默认指向远程 staging/production；
- 不能依赖数据库降级回滚，优先使用向前修复 migration；
- 部署记录必须包含 migration 文件名和执行结果。

当前仓库的迁移工具会拒绝直接对 staging/production 执行本地 migration。后续应实现一个受控的 deployment migration runner，或由运维在目标数据库上执行已审查 SQL，并保留审计记录。

## 11. 回滚规范

### 11.1 应用回滚

应用发布失败时：

1. 停止继续发布。
2. 保留失败容器日志和 health check 结果。
3. 将 API 镜像恢复为 `last-successful-image`。
4. 只重建 API，不删除 Redis、数据库或持久化 volume。
5. 重新执行 readiness 和核心业务 smoke test。

### 11.2 配置回滚

环境变量变更失败时，仅回滚镜像无效。必须恢复上一份 `.env` 备份，再重新创建 API 容器，并重新执行健康检查。

### 11.3 数据库回滚

数据库 migration 默认不做物理降级。出现问题时优先：

- 停止相关功能开关；
- 发布向前修复 migration；
- 必要时按备份恢复，并执行明确的数据恢复方案。

## 12. 监控和安全要求

- `/api/v1/healthz` 用于 liveness；`/api/v1/readyz` 用于数据库 readiness。
- 监控必须区分 staging 和 production 的 hostname、service、environment 和 deployment SHA。
- API 只监听回环端口，由 Tunnel 或反向代理对外提供 HTTPS。
- VPS 部署使用非 root 用户和 rootless Docker；部署用户不能通过 workflow 执行任意 sudo 命令。
- SSH 使用独立的 CI 专用密钥，并固定已核验的 `known_hosts`。
- staging 日志和测试数据中不得包含 production 用户、Token、API key 或未脱敏业务数据。
- production 发布和回滚都必须保留 commit、镜像 digest、操作者、审批人和结果。

## 13. 当前项目的实施顺序

### P0：先建立环境边界

- [ ] 将 `compose.preview.yaml` 复制或演进为 `compose.staging.yaml`。
- [ ] 将 `.env.preview.example` 演进为 `.env.staging.example`。
- [ ] 在新的 production VPS `sg-vps` 创建 `src`、`releases`、`shared`、`deploy` 空目录骨架；首个新角色 release 成功前不创建 `current`。
- [ ] 在新的 staging VPS `asianode-vps` 创建 `src`、`releases`、`shared`、`deploy` 空目录骨架；首个新角色 release 成功前不创建 `current`。
- [ ] 为两个环境创建独立的 `shared/build/build.env`，并把 package index 与 runtime `.env` 分离。
- [ ] 确认 `sg-vps` 上的 `asianode-production` project、network、Redis、production 数据库连接和端口 `18000`。
- [ ] 在 `asianode-vps` 创建本机 PostgreSQL、`asianode_staging` database/user 和 pgvector 扩展。
- [ ] 创建 staging 独立 workspace。
- [ ] 创建 `staging.<domain>`、`api-staging.<domain>` DNS/Tunnel 路由。
- [ ] 修正 `.gitignore`，确保 `.env.production` 和 `.env.staging` 不会入库。

### P1：建立 production 发布单元

- [ ] 新增 `compose.production.yaml`，API 只使用 `image:`。
- [ ] 确认 production Supabase 数据库连接、Redis、文件存储和 `.env.production`。
- [ ] 建立 production image digest、health check 和自动回滚脚本。
- [ ] 确认 production 与 staging 的端口、网络和 volume 不冲突。

### P2：接入 GitHub Actions 和 VPS 前端发布

- [ ] PR workflow 完成测试、Lint 和 Docker build validation。
- [ ] `staging` 分支合并后自动发布 staging。
- [ ] `main` 分支合并后构建并推送 SHA 镜像。
- [ ] 创建 GitHub `production` Environment 和 required reviewer。
- [ ] production deploy 使用同一个已在 staging 验证的镜像 digest。
- [ ] 前端 `staging` 分支合并后在 `asianode-vps` 构建并发布 `asianode-staging-frontend`。
- [ ] 前端 `main` 分支合并后在 `sg-vps` 构建并发布 `asianode-production-frontend`。
- [ ] 前端发布记录前端 commit、构建变量摘要、基础镜像来源和 Nginx healthcheck 结果。

### P3：上线前演练

- [ ] 完成 staging 登录、CSRF、核心 API、数据库和 Redis smoke test。
- [ ] 完成 production 首次部署但不立即切换流量。
- [ ] 演练镜像回滚、配置回滚和 migration 失败处理。
- [ ] 演练 VPS 重启后的 rootless Docker、API、Redis 和 Tunnel 恢复。
- [ ] 记录所有域名、secret、镜像、migration 和回滚操作。

## 14. 上线验收清单

### 域名和路由

- [ ] `https://staging.<domain>` 可以访问 staging 前端。
- [ ] `https://staging.<domain>/healthz` 返回 `ok`，且前端 API URL 指向 `api-staging.<domain>`。
- [ ] `https://<domain>/healthz` 返回 `ok`，且前端 API URL 指向 `api.<domain>`。
- [ ] `https://api-staging.<domain>/api/v1/healthz` 返回 `environment=staging`。
- [ ] `https://api.<domain>/api/v1/healthz` 返回 `environment=production`。
- [ ] staging 和 production 的 Tunnel upstream 不指向同一端口。

### 隔离

- [ ] staging 和 production 使用不同数据库连接、Redis、workspace、文件存储和 `AUTH_SECRET`。
- [ ] staging 无法访问 production database 或 production storage。
- [ ] 浏览器不会在 staging 和 production 之间复用认证 Cookie。
- [ ] CORS 只允许对应前端域名。

### 发布

- [ ] PR 未通过 CI 不能合并。
- [ ] staging 发布成功后才允许 production promotion。
- [ ] production 需要人工审批，并使用 staging 验证过的 image digest。
- [ ] production deploy 不会重启 staging 或无关 Redis。
- [ ] 失败发布可以恢复到上一份可用镜像。

### 数据和恢复

- [ ] production migration 前有备份和 preflight 记录。
- [ ] 文件存储有明确的持久化方案和备份策略。
- [ ] 已完成镜像、配置、数据库 migration 和 VPS 重启恢复演练。
