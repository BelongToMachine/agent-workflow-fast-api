.PHONY: setup dev test test-integration lint infra-up infra-down infra-status infra-logs migration-status auth-migration-status knowledge-integrity migrate-knowledge migrate-auth-identity migrate-knowledge-grants migrate-knowledge-ingestion migrate-knowledge-bases migrate-knowledge-embeddings

COMPOSE ?= docker compose
COMPOSE_FILE ?= compose.yaml
SQLADMIN_ENABLED ?= false
SQLADMIN_USERNAME ?= admin
SQLADMIN_PASSWORD ?=
SQLADMIN_SECRET_KEY ?=

setup:
	uv sync

dev:
	SQLADMIN_ENABLED=$(SQLADMIN_ENABLED) \
	SQLADMIN_USERNAME=$(SQLADMIN_USERNAME) \
	SQLADMIN_PASSWORD=$(SQLADMIN_PASSWORD) \
	SQLADMIN_SECRET_KEY=$(SQLADMIN_SECRET_KEY) \
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

test-integration:
	uv run pytest -m integration

lint:
	uv run ruff check .

migration-status:
	uv run python -m app.db.migration_status

auth-migration-status:
	uv run python -m app.db.auth_identity_status

knowledge-integrity:
	uv run python -m app.db.knowledge_integrity

migrate-knowledge:
	uv run python -m app.db.migrate_knowledge --apply

migrate-auth-identity:
	uv run python -m app.db.migrate_auth_identity --apply

migrate-knowledge-grants:
	uv run python -m app.db.migrate_knowledge_grants --apply

migrate-knowledge-ingestion:
	uv run python -m app.db.migrate_knowledge_ingestion --apply

migrate-knowledge-bases:
	uv run python -m app.db.migrate_knowledge_bases --apply

migrate-knowledge-embeddings:
	uv run python -m app.db.migrate_knowledge_embeddings --apply
