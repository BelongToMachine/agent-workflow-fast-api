.PHONY: setup dev test lint migration-status migrate-knowledge-grants migrate-knowledge-ingestion migrate-knowledge-bases migrate-knowledge-embeddings

setup:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

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
