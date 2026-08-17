from app.core.config import Settings
from app.db.migration_status import build_migration_statuses
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
        "files_table": True,
        "chunks_table": True,
        "vector_extension": True,
        "embedding_column": True,
        "embedding_index": True,
        "knowledge_base_table": True,
        "grants_repointed": True,
        "files_repointed": False,
        "chunks_repointed": True,
    }

    statuses = build_migration_statuses(row)

    assert [status.applied for status in statuses] == [True, True, True, False]
    assert statuses[-1].name == "0004_knowledge_bases"
