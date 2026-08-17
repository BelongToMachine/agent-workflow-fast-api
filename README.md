# Asianode FastAPI

Asianode Agent 的独立 FastAPI 后端项目。当前版本已经接管聊天生成链路，后续逐步加入认证、企业隔离、知识库和 AI Agent 能力。

## 技术栈

- Python 3.12+
- FastAPI
- Pydantic Settings
- Uvicorn
- Pytest
- Ruff

## 本地运行

推荐使用 [uv](https://docs.astral.sh/uv/) 管理环境和依赖：

```bash
make setup
make dev
```

后续日常启动直接执行：

```bash
make dev
```

服务启动后访问：

- API 根路径：http://127.0.0.1:8000/
- 健康检查：http://127.0.0.1:8000/api/v1/healthz
- 商品查询：`GET http://127.0.0.1:8000/api/v1/products?workspace_id={workspace_id}`
- 聊天接口：`POST http://127.0.0.1:8000/api/v1/chat`
- Swagger：http://127.0.0.1:8000/docs

本地运行时，FastAPI 会读取仓库根目录的 `.env.local`，因此可以复用现有的
`DEEPSEEK_API_KEY`。部署到其他环境时，请通过环境变量提供 API Key。

## 当前前端切换状态

当根目录 `.env.local` 中设置以下变量时，Web 端聊天请求会进入 FastAPI：

```env
USE_FASTAPI_BACKEND=1
NEXT_PUBLIC_USE_FASTAPI_BACKEND=1
FASTAPI_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FASTAPI_BASE_URL=http://127.0.0.1:8000
```

聊天请求会由浏览器直接发送到 FastAPI `8000` 端口，FastAPI 负责模型调用和 SSE 返回。当前本地聊天接口还未接入正式 Token 验证，因此只适合开发环境；生产环境接入 Logto 后再开放跨域访问。

## 测试和代码检查

```bash
make test
make lint
```

## 当前目录结构

```text
app/
├── api/
│   ├── routes/
│   │   ├── chat.py
│   │   └── health.py
│   └── router.py
├── core/
│   └── config.py
└── main.py
tests/
└── test_health.py
```

## 后续建设顺序

1. 补齐商品高级过滤，并与 Next.js 查询结果做对比。
2. 迁移内容查询接口。
3. 接入 Logto Token 验证。
4. 增加企业、成员、角色和知识库权限模型。
5. 增加文件上传、解析、向量检索和 AI Agent 接口。

商品查询当前已完成基础只读版本，支持 `workspace_id`、`query`、`category` 和 `limit`；价格、运营状态、知识源文件等高级过滤将在后续对照 Next.js 查询逻辑继续迁移。

当前聊天接口还未迁移消息持久化、工具调用和 FastAPI 侧的用户权限验证；这些能力会在后续迁移阶段补齐。当前多轮上下文由 Web 前端暂时随请求传给 FastAPI，因此刷新页面后仍依赖现有 Next.js 消息接口。
