import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.db.migration_status import (
    MIGRATION_STATUS_QUERY,
    MigrationStatus,
    build_migration_statuses,
)
from app.db.migration_utils import migration_apply_error
from app.db.session import get_db_connection

MIGRATION_NAMES = (
    "0001_knowledge_base_grants",
    "0002_knowledge_ingestion",
    "0003_knowledge_embeddings",
    "0004_knowledge_bases",
)
MIGRATION_PATHS = tuple(
    Path(__file__).resolve().parents[2] / "migrations" / f"{name}.sql"
    for name in MIGRATION_NAMES
)


def pending_migration_paths(
    statuses: list[MigrationStatus],
) -> tuple[Path, ...]:
    applied_by_name = {status.name: status.applied for status in statuses}
    return tuple(
        path for path in MIGRATION_PATHS if not applied_by_name.get(path.stem, False)
    )


async def _read_status(connection) -> list[MigrationStatus]:
    result = await connection.execute(MIGRATION_STATUS_QUERY)
    return build_migration_statuses(dict(result.mappings().one()))


def _print_status(statuses: list[MigrationStatus]) -> None:
    for status in statuses:
        state = "applied" if status.applied else "pending"
        print(f"{status.name}: {state} ({status.details})")


async def _run(*, apply: bool, allow_remote: bool = False) -> int:
    missing_files = [path for path in MIGRATION_PATHS if not path.is_file()]
    if missing_files:
        for path in missing_files:
            print(f"Migration file not found: {path}")
        return 1

    settings = get_settings()
    if apply:
        if error := migration_apply_error(settings, allow_remote=allow_remote):
            print(error)
            return 1

    async with get_db_connection() as connection:
        statuses = await _read_status(connection)
        pending_paths = pending_migration_paths(statuses)
        if not pending_paths:
            _print_status(statuses)
            print("All knowledge migrations are already applied.")
            return 0

        if not apply:
            _print_status(statuses)
            print("Run with --apply to execute pending knowledge migrations.")
            return 2

        # The status query opens an implicit SQLAlchemy transaction. Close it
        # before starting the all-or-nothing migration transaction below.
        await connection.rollback()
        async with connection.begin():
            for path in pending_paths:
                await connection.exec_driver_sql(path.read_text(encoding="utf-8"))
                print(f"Applied {path.stem}.")

        statuses = await _read_status(connection)
        _print_status(statuses)
        if not all(status.applied for status in statuses):
            print("Knowledge migrations remain pending after apply.")
            return 2
        print("All knowledge migrations applied successfully.")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect or apply all knowledge migrations in dependency order."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply pending migrations in one transaction.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow apply against a reviewed non-local development database.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(apply=args.apply, allow_remote=args.allow_remote)))


if __name__ == "__main__":
    main()
