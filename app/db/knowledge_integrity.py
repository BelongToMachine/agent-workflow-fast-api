import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from app.db.migration_status import MIGRATION_STATUS_QUERY, build_migration_statuses
from app.db.session import get_db_connection

KNOWLEDGE_INTEGRITY_QUERY = text(
    """
    SELECT
        (
            SELECT COUNT(*)
            FROM "KnowledgeBaseGrant" AS grant_record
            LEFT JOIN "KnowledgeBase" AS knowledge_base
                ON knowledge_base."id" = grant_record."knowledgeBaseId"
            WHERE knowledge_base."id" IS NULL
        ) AS grants_without_knowledge_base,
        (
            SELECT COUNT(*)
            FROM "KnowledgeBaseGrant" AS grant_record
            INNER JOIN "KnowledgeBase" AS knowledge_base
                ON knowledge_base."id" = grant_record."knowledgeBaseId"
            WHERE grant_record."workspaceId" <> knowledge_base."workspaceId"
        ) AS grant_workspace_mismatches,
        (
            SELECT COUNT(*)
            FROM "KnowledgeFile" AS knowledge_file
            LEFT JOIN "KnowledgeBase" AS knowledge_base
                ON knowledge_base."id" = knowledge_file."knowledgeBaseId"
            WHERE knowledge_base."id" IS NULL
        ) AS files_without_knowledge_base,
        (
            SELECT COUNT(*)
            FROM "KnowledgeFile" AS knowledge_file
            INNER JOIN "KnowledgeBase" AS knowledge_base
                ON knowledge_base."id" = knowledge_file."knowledgeBaseId"
            WHERE knowledge_file."workspaceId" <> knowledge_base."workspaceId"
        ) AS file_workspace_mismatches,
        (
            SELECT COUNT(*)
            FROM "KnowledgeChunk" AS chunk
            LEFT JOIN "KnowledgeFile" AS knowledge_file
                ON knowledge_file."id" = chunk."fileId"
            WHERE knowledge_file."id" IS NULL
        ) AS chunks_without_file,
        (
            SELECT COUNT(*)
            FROM "KnowledgeChunk" AS chunk
            LEFT JOIN "KnowledgeBase" AS knowledge_base
                ON knowledge_base."id" = chunk."knowledgeBaseId"
            WHERE knowledge_base."id" IS NULL
        ) AS chunks_without_knowledge_base,
        (
            SELECT COUNT(*)
            FROM "KnowledgeChunk" AS chunk
            INNER JOIN "KnowledgeBase" AS knowledge_base
                ON knowledge_base."id" = chunk."knowledgeBaseId"
            WHERE chunk."workspaceId" <> knowledge_base."workspaceId"
        ) AS chunk_workspace_mismatches,
        (
            SELECT COUNT(*)
            FROM "KnowledgeChunk" AS chunk
            INNER JOIN "KnowledgeFile" AS knowledge_file
                ON knowledge_file."id" = chunk."fileId"
            WHERE chunk."workspaceId" <> knowledge_file."workspaceId"
               OR chunk."knowledgeBaseId" <> knowledge_file."knowledgeBaseId"
        ) AS chunk_file_scope_mismatches,
        (
            SELECT COUNT(*)
            FROM "KnowledgeBase" AS knowledge_base
            INNER JOIN "KnowledgeSource" AS source
                ON source."id" = knowledge_base."id"
            WHERE knowledge_base."workspaceId" <> source."workspaceId"
        ) AS backfilled_workspace_mismatches
    """
)


@dataclass(frozen=True)
class IntegrityCheck:
    name: str
    violations: int
    details: str

    @property
    def passed(self) -> bool:
        return self.violations == 0


def _violation_count(row: Mapping[str, object], key: str) -> int:
    value = row.get(key, 0)
    return int(value or 0)


def build_integrity_checks(row: Mapping[str, object]) -> list[IntegrityCheck]:
    return [
        IntegrityCheck(
            "grants_without_knowledge_base",
            _violation_count(row, "grants_without_knowledge_base"),
            "every grant references an existing KnowledgeBase",
        ),
        IntegrityCheck(
            "grant_workspace_mismatches",
            _violation_count(row, "grant_workspace_mismatches"),
            "grant and KnowledgeBase workspaceId values match",
        ),
        IntegrityCheck(
            "files_without_knowledge_base",
            _violation_count(row, "files_without_knowledge_base"),
            "every KnowledgeFile references an existing KnowledgeBase",
        ),
        IntegrityCheck(
            "file_workspace_mismatches",
            _violation_count(row, "file_workspace_mismatches"),
            "file and KnowledgeBase workspaceId values match",
        ),
        IntegrityCheck(
            "chunks_without_file",
            _violation_count(row, "chunks_without_file"),
            "every KnowledgeChunk references an existing KnowledgeFile",
        ),
        IntegrityCheck(
            "chunks_without_knowledge_base",
            _violation_count(row, "chunks_without_knowledge_base"),
            "every KnowledgeChunk references an existing KnowledgeBase",
        ),
        IntegrityCheck(
            "chunk_workspace_mismatches",
            _violation_count(row, "chunk_workspace_mismatches"),
            "chunk and KnowledgeBase workspaceId values match",
        ),
        IntegrityCheck(
            "chunk_file_scope_mismatches",
            _violation_count(row, "chunk_file_scope_mismatches"),
            "chunk workspace and knowledgeBaseId values match its file",
        ),
        IntegrityCheck(
            "backfilled_workspace_mismatches",
            _violation_count(row, "backfilled_workspace_mismatches"),
            "backfilled KnowledgeBase rows preserve the source workspace",
        ),
    ]


async def _run() -> int:
    async with get_db_connection() as connection:
        migration_result = await connection.execute(MIGRATION_STATUS_QUERY)
        migration_statuses = build_migration_statuses(
            dict(migration_result.mappings().one())
        )
        if not all(status.applied for status in migration_statuses):
            pending = ", ".join(
                status.name for status in migration_statuses if not status.applied
            )
            print(f"Knowledge migrations are incomplete; run migration-status first: {pending}")
            return 2

        integrity_result = await connection.execute(KNOWLEDGE_INTEGRITY_QUERY)
        checks = build_integrity_checks(dict(integrity_result.mappings().one()))

    for check in checks:
        state = "ok" if check.passed else f"failed ({check.violations} violation(s))"
        print(f"{check.name}: {state} ({check.details})")
    return 0 if all(check.passed for check in checks) else 3


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check knowledge-base workspace and relationship integrity."
    )
    parser.parse_args()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
