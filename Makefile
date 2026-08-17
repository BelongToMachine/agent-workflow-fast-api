.PHONY: setup dev test lint infra-up infra-down infra-status infra-logs migration-status migrate-knowledge-grants migrate-knowledge-ingestion migrate-knowledge-bases migrate-knowledge-embeddings

COMPOSE ?= docker compose
COMPOSE_FILE ?= compose.yaml

setup:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

infra-up:
	$(COMPOSE) -f $(COMPOSE_FILE) up -d postgres redis

infra-down:
	$(COMPOSE) -f $(COMPOSE_FILE) down

infra-status:
	$(COMPOSE) -f $(COMPOSE_FILE) ps

infra-logs:
	$(COMPOSE) -f $(COMPOSE_FILE) logs -f postgres redis

test:
	uv run pytest

lint:
	uv run ruff check .

migration-status:
	uv run python -m app.db.migration_status

migrate-knowledge-grants:
	uv run python -m app.db.migrate_knowledge_grants --apply

migrate-knowledge-ingestion:
	uv run python -m app.db.migrate_knowledge_ingestion --apply

migrate-knowledge-bases:
	uv run python -m app.db.migrate_knowledge_bases --apply

migrate-knowledge-embeddings:
	uv run python -m app.db.migrate_knowledge_embeddings --apply
