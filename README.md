# Asianode FastAPI

Asianode Agent 的独立 FastAPI 后端项目。当前版本只提供最小可运行骨架，后续逐步加入认证、企业隔离、知识库和 AI Agent 能力。

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
uv sync
uv run uvicorn app.main:app --reload
```

服务启动后访问：

- API 根路径：http://127.0.0.1:8000/
- 健康检查：http://127.0.0.1:8000/api/v1/healthz
- Swagger：http://127.0.0.1:8000/docs

## 测试和代码检查

```bash
uv run pytest
uv run ruff check .
```

## 当前目录结构

```text
app/
├── api/
│   ├── routes/
│   │   └── health.py
│   └── router.py
├── core/
│   └── config.py
└── main.py
tests/
└── test_health.py
```

## 后续建设顺序

1. 接入 PostgreSQL 和数据库迁移。
2. 接入 Logto Token 验证。
3. 增加企业、成员、角色和知识库权限模型。
4. 增加文件上传、解析和异步入库任务。
5. 增加向量检索和 AI Agent 接口。

