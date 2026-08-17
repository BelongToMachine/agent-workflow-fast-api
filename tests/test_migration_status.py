from app.core.config import Settings
from app.db.knowledge_integrity import KNOWLEDGE_INTEGRITY_QUERY, build_integrity_checks
from app.db.migrate_knowledge import (
    MIGRATION_NAMES,
    MIGRATION_PATHS,
    pending_migration_paths,
)
from app.db.migration_status import (
    MIGRATION_STATUS_QUERY,
    MigrationStatus,
    build_migration_statuses,
)
from app.db.migration_utils import get_migration_target, migration_apply_error


def test_local_migration_target_is_allowed() -> None:
    target = get_migration_target(
        Settings(postgres_url="postgresql://user:password@127.0.0.1:5432/asianode")
    )

    assert target.is_local is True
    assert target.display_name == "127.0.0.1:5432/asianode"
    assert migration_apply_error(
        Settings(
            environment="development",
            postgres_url="postgresql://user:password@127.0.0.1:5432/asianode",
        )
    ) is None


def test_remote_development_migration_requires_explicit_opt_in() -> None:
    settings = Settings(
        environment="development",
        postgres_url="postgresql://user:password@db.example.com:5432/asianode",
    )

    error = migration_apply_error(settings)
    assert error is not None
    assert "remote target db.example.com:5432/asianode" in error
    assert migration_apply_error(settings, allow_remote=True) is None


def test_staging_migration_is_always_rejected() -> None:
    settings = Settings(
        environment="staging",
        postgres_url="postgresql://user:password@127.0.0.1:5432/asianode",
    )

    assert "staging/production" in (migration_apply_error(settings) or "")
    assert "staging/production" in (migration_apply_error(settings, allow_remote=True) or "")


def test_migration_status_requires_all_entity_dependencies() -> None:
    row = {
        "grants_table": True,
        "grants_required_columns": True,
        "grants_indexes": True,
        "grants_workspace_fk": True,
        "grants_knowledge_base_fk": True,
        "files_table": True,
        "files_required_columns": True,
        "files_indexes": True,
        "files_knowledge_base_fk": True,
        "files_uploaded_by_fk": True,
        "files_workspace_fk": True,
        "chunks_table": True,
        "chunks_required_columns": True,
        "chunks_indexes": True,
        "chunks_file_fk": True,
        "chunks_knowledge_base_fk": True,
        "chunks_workspace_fk": True,
        "vector_extension": True,
        "embedding_column": True,
        "embedding_index": True,
        "embedding_index_valid": True,
        "knowledge_base_table": True,
        "knowledge_base_required_columns": True,
        "knowledge_base_indexes": True,
        "knowledge_base_workspace_fk": True,
        "grants_repointed": True,
        "files_repointed": False,
        "chunks_repointed": True,
    }

    statuses = build_migration_statuses(row)

    assert [status.applied for status in statuses] == [True, True, True, False]
    assert statuses[-1].name == "0004_knowledge_bases"


def test_migration_status_rejects_a_partial_schema() -> None:
    row = {
        "grants_table": True,
        "grants_required_columns": True,
        "grants_indexes": False,
        "grants_workspace_fk": True,
        "grants_knowledge_base_fk": True,
    }

    statuses = build_migration_statuses(row)

    assert statuses[0].applied is False


def test_migration_status_query_covers_schema_capabilities() -> None:
    sql = str(MIGRATION_STATUS_QUERY)

    assert "grants_required_columns" in sql
    assert "files_required_columns" in sql
    assert "chunks_required_columns" in sql
    assert "embedding_index_valid" in sql
    assert "knowledge_base_required_columns" in sql
    assert "conrelid = to_regclass" in sql


def test_knowledge_integrity_query_checks_cross_scope_relationships() -> None:
    sql = str(KNOWLEDGE_INTEGRITY_QUERY)

    assert 'grant_record."workspaceId" <> knowledge_base."workspaceId"' in sql
    assert 'knowledge_file."workspaceId" <> knowledge_base."workspaceId"' in sql
    assert 'chunk."knowledgeBaseId" <> knowledge_file."knowledgeBaseId"' in sql
    assert 'source."workspaceId"' in sql


def test_knowledge_integrity_checks_pass_for_zero_violations() -> None:
    checks = build_integrity_checks({})

    assert checks
    assert all(check.passed for check in checks)


def test_knowledge_integrity_checks_report_each_violation() -> None:
    checks = build_integrity_checks(
        {
            "grants_without_knowledge_base": 1,
            "chunk_file_scope_mismatches": 2,
        }
    )

    assert checks[0].violations == 1
    assert checks[0].passed is False
    assert checks[7].violations == 2
    assert checks[7].passed is False
    assert sum(not check.passed for check in checks) == 2


def test_knowledge_migration_runner_uses_dependency_order() -> None:
    assert [path.stem for path in MIGRATION_PATHS] == list(MIGRATION_NAMES)
    assert all(path.is_file() for path in MIGRATION_PATHS)


def test_knowledge_migration_runner_only_selects_pending_migrations() -> None:
    statuses = [
        MigrationStatus(name=name, applied=index < 2, details="test")
        for index, name in enumerate(MIGRATION_NAMES)
    ]

    assert [path.stem for path in pending_migration_paths(statuses)] == list(
        MIGRATION_NAMES[2:]
    )
