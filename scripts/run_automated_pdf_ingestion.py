"""Run the knowledge-base automated ingestion flow for root-level PDF files.

The command is intentionally dry-run by default.  Use ``--execute`` only after
reviewing the preflight list.  Processing is performed through the existing
knowledge-file upload route and ``process_knowledge_file`` service so that
workspace permissions, storage, parsing, chunking, and embeddings stay on the
same code path as the Automated Flow page.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import Headers

from app.api.routes.knowledge_files import process_knowledge_file, upload_knowledge_file
from app.core.auth import AuthenticatedUser
from app.core.config import MAX_KNOWLEDGE_FILE_BYTES, Settings, get_settings
from app.db.errors import DatabaseServiceError
from app.db.session import get_db_connection

LOGGER = logging.getLogger(__name__)

MAX_PDF_BYTES = MAX_KNOWLEDGE_FILE_BYTES
DEFAULT_SOURCE_DIR = Path("/Users/mac/Downloads/asianode/files")
DEFAULT_EMAIL = "owner@example.com"


class RunnerError(RuntimeError):
    """Raised when the batch runner cannot safely process a file or target."""


@dataclass(frozen=True)
class ProcessingResult:
    completed: bool
    detail: str
    file_id: UUID | None = None


@dataclass
class BatchSummary:
    completed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    dry_run: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunnerContext:
    user_id: UUID
    email: str
    workspace_id: UUID
    workspace_role: str
    knowledge_base_id: UUID
    knowledge_base_name: str

    def authenticated_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=str(self.user_id),
            email=self.email,
            auth_provider="local",
            workspace_id=str(self.workspace_id),
            role=self.workspace_role,
            roles=[self.workspace_role],
            is_development=False,
        )


OWNER_CONTEXT_QUERY = text(
    """
    SELECT
        user_record."id" AS user_id,
        user_record."email" AS email,
        user_record."status" AS user_status,
        member."workspaceId" AS workspace_id,
        member."role" AS workspace_role,
        member."status" AS membership_status
    FROM "User" AS user_record
    INNER JOIN "WorkspaceMember" AS member
        ON member."userId" = user_record."id"
    WHERE lower(btrim(user_record."email")) = :email
      AND user_record."status" = 'active'
      AND member."status" = 'active'
      AND member."workspaceId" = :workspace_id
    LIMIT 1
    """
)

KNOWLEDGE_BASE_BY_ID_QUERY = text(
    """
    SELECT
        "id" AS knowledge_base_id,
        "displayName" AS knowledge_base_name,
        "status" AS knowledge_base_status
    FROM "KnowledgeBase"
    WHERE "id" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
      AND "status" = 'ready'
    LIMIT 1
    """
)

KNOWLEDGE_BASE_LIST_QUERY = text(
    """
    SELECT
        "id" AS knowledge_base_id,
        "displayName" AS knowledge_base_name,
        "status" AS knowledge_base_status
    FROM "KnowledgeBase"
    WHERE "workspaceId" = :workspace_id
      AND "status" = 'ready'
    ORDER BY "displayName" ASC, "id" ASC
    """
)

FILE_BY_HASH_QUERY = text(
    """
    SELECT
        "id" AS file_id,
        "status" AS file_status,
        "originalName" AS original_name
    FROM "KnowledgeFile"
    WHERE "fileHash" = :file_hash
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

FILE_COMPLETION_QUERY = text(
    """
    SELECT
        file."status" AS file_status,
        file."errorMessage" AS file_error_message,
        parsed."chunkStatus" AS chunk_status,
        parsed."chunkErrorMessage" AS chunk_error_message,
        COUNT(chunk."id") AS chunk_count,
        COUNT(chunk."embedding") AS embedded_chunk_count,
        COUNT(chunk."id") FILTER (
            WHERE chunk."embedding" IS NOT NULL
              AND chunk."embeddingModel" = :embedding_model
        ) AS current_embedded_chunk_count
    FROM "KnowledgeFile" AS file
    LEFT JOIN "KnowledgeParsedDocument" AS parsed
        ON parsed."fileId" = file."id"
       AND parsed."knowledgeBaseId" = file."knowledgeBaseId"
       AND parsed."workspaceId" = file."workspaceId"
    LEFT JOIN "KnowledgeChunk" AS chunk
        ON chunk."fileId" = file."id"
       AND chunk."knowledgeBaseId" = file."knowledgeBaseId"
       AND chunk."workspaceId" = file."workspaceId"
    WHERE file."id" = :file_id
      AND file."knowledgeBaseId" = :knowledge_base_id
      AND file."workspaceId" = :workspace_id
    GROUP BY
        file."status",
        file."errorMessage",
        parsed."chunkStatus",
        parsed."chunkErrorMessage"
    LIMIT 1
    """
)


def discover_pdf_files(
    source_dir: Path,
    *,
    max_bytes: int = MAX_PDF_BYTES,
) -> list[Path]:
    """Return only regular, root-level PDF files smaller than ``max_bytes``."""
    if not source_dir.exists():
        raise RunnerError(f"Source directory does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise RunnerError(f"Source path is not a directory: {source_dir}")

    files: list[Path] = []
    for entry in source_dir.iterdir():
        if entry.is_symlink() or not entry.is_file():
            continue
        if entry.suffix.lower() != ".pdf":
            continue
        if entry.stat().st_size >= max_bytes:
            continue
        files.append(entry)
    return sorted(files, key=lambda path: (path.name.casefold(), path.name))


def limit_pdf_files(files: list[Path], max_files: int | None) -> list[Path]:
    """Limit a selected file list without changing its deterministic order."""
    if max_files is None:
        return files
    if max_files < 1:
        raise ValueError("max_files must be at least 1")
    return files[:max_files]


def move_to_archive(source: Path, archive_dir: Path) -> Path:
    """Move one completed source file without overwriting an archived file."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / source.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Archive destination already exists: {destination}")
    source.replace(destination)
    return destination


async def run_batch(
    files: list[Path],
    *,
    archive_dir: Path,
    process_file: Callable[[Path], Awaitable[ProcessingResult]],
    execute: bool,
) -> BatchSummary:
    """Process files serially and archive each one only after verification."""
    summary = BatchSummary()
    for path in files:
        if not execute:
            summary.dry_run.append(path.name)
            continue

        try:
            result = await process_file(path)
            if not result.completed:
                summary.failed.append((path.name, result.detail))
                continue
            move_to_archive(path, archive_dir)
            summary.completed.append(path.name)
        except Exception as error:  # keep later files independent of one failure
            LOGGER.exception("Automated PDF ingestion failed for %s", path)
            summary.failed.append((path.name, str(error)))
    return summary


async def _fetch_runner_context(
    *,
    email: str,
    workspace_id: UUID,
    knowledge_base_id: UUID | None,
) -> RunnerContext:
    normalized_email = email.strip().casefold()
    if not normalized_email:
        raise RunnerError("The owner email cannot be empty.")

    try:
        async with get_db_connection() as connection:
            owner_result = await connection.execute(
                OWNER_CONTEXT_QUERY,
                {"email": normalized_email, "workspace_id": workspace_id},
            )
            owner = owner_result.mappings().first()
            if owner is None:
                raise RunnerError(
                    f"Active account {email!r} has no active membership in workspace "
                    f"{workspace_id}."
                )

            if knowledge_base_id is None:
                base_result = await connection.execute(
                    KNOWLEDGE_BASE_LIST_QUERY,
                    {"workspace_id": workspace_id},
                )
                bases = base_result.mappings().all()
                if len(bases) != 1:
                    names = ", ".join(str(row["knowledge_base_name"]) for row in bases)
                    raise RunnerError(
                        "Specify --knowledge-base-id because the workspace has "
                        f"{len(bases)} ready knowledge bases{f': {names}' if names else ''}."
                    )
                knowledge_base = bases[0]
            else:
                base_result = await connection.execute(
                    KNOWLEDGE_BASE_BY_ID_QUERY,
                    {
                        "knowledge_base_id": knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                knowledge_base = base_result.mappings().first()
                if knowledge_base is None:
                    raise RunnerError(
                        f"Ready knowledge base {knowledge_base_id} was not found in "
                        f"workspace {workspace_id}."
                    )
    except RunnerError:
        raise
    except (DatabaseServiceError, RuntimeError, SQLAlchemyError) as error:
        raise RunnerError(
            f"Could not resolve the runner target from the database: {error}"
        ) from error

    return RunnerContext(
        user_id=UUID(str(owner["user_id"])),
        email=str(owner["email"]),
        workspace_id=UUID(str(owner["workspace_id"])),
        workspace_role=str(owner["workspace_role"]),
        knowledge_base_id=UUID(str(knowledge_base["knowledge_base_id"])),
        knowledge_base_name=str(knowledge_base["knowledge_base_name"]),
    )


async def _find_existing_file(
    *,
    file_hash: str,
    context: RunnerContext,
) -> UUID | None:
    async with get_db_connection() as connection:
        result = await connection.execute(
            FILE_BY_HASH_QUERY,
            {
                "file_hash": file_hash,
                "knowledge_base_id": context.knowledge_base_id,
                "workspace_id": context.workspace_id,
            },
        )
        row = result.mappings().first()
    return UUID(str(row["file_id"])) if row is not None else None


def _json_response_payload(response: JSONResponse) -> object:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return response.body


async def _verify_file_completion(
    *,
    file_id: UUID,
    context: RunnerContext,
    settings: Settings,
) -> ProcessingResult:
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                FILE_COMPLETION_QUERY,
                {
                    "embedding_model": settings.embedding_model,
                    "file_id": file_id,
                    "knowledge_base_id": context.knowledge_base_id,
                    "workspace_id": context.workspace_id,
                },
            )
            row = result.mappings().first()
    except (DatabaseServiceError, RuntimeError, SQLAlchemyError) as error:
        return ProcessingResult(False, f"Could not verify completion in the database: {error}")

    if row is None:
        return ProcessingResult(False, f"Knowledge file {file_id} was not found after processing.")

    file_status = str(row["file_status"])
    chunk_status = str(row["chunk_status"]) if row["chunk_status"] is not None else "missing"
    chunk_count = int(row["chunk_count"])
    embedded_count = int(row["embedded_chunk_count"])
    current_embedded_count = int(row["current_embedded_chunk_count"])
    if (
        file_status != "ready"
        or chunk_status != "ready"
        or chunk_count == 0
        or embedded_count != chunk_count
        or current_embedded_count != chunk_count
    ):
        details = (
            f"fileStatus={file_status}, chunkStatus={chunk_status}, "
            f"chunks={chunk_count}, embedded={embedded_count}, "
            f"currentModelEmbedded={current_embedded_count}"
        )
        if row["file_error_message"]:
            details += f", fileError={row['file_error_message']}"
        if row["chunk_error_message"]:
            details += f", chunkError={row['chunk_error_message']}"
        return ProcessingResult(False, f"Automated flow is incomplete: {details}", file_id)

    return ProcessingResult(
        True,
        f"ready; {chunk_count} chunks embedded with {settings.embedding_model}",
        file_id,
    )


async def process_pdf_file(
    path: Path,
    *,
    context: RunnerContext,
    settings: Settings,
) -> ProcessingResult:
    """Upload one PDF through the Automated Flow path and verify its final state."""
    content = path.read_bytes()
    if len(content) >= MAX_PDF_BYTES:
        return ProcessingResult(False, f"File is not smaller than 100 MiB: {path.name}")

    file_hash = hashlib.sha256(content).hexdigest()
    existing_file_id = await _find_existing_file(file_hash=file_hash, context=context)
    if existing_file_id is not None:
        await process_knowledge_file(
            existing_file_id,
            context.workspace_id,
            create_chunks=True,
            create_embeddings=True,
        )
        result = await _verify_file_completion(
            file_id=existing_file_id,
            context=context,
            settings=settings,
        )
        if result.completed:
            return ProcessingResult(
                True,
                f"reprocessed existing file {existing_file_id}; {result.detail}",
                existing_file_id,
            )
        return result

    background_tasks = BackgroundTasks()
    upload = UploadFile(
        file=io.BytesIO(content),
        filename=path.name,
        headers=Headers({"content-type": "application/pdf"}),
    )
    try:
        try:
            response = await upload_knowledge_file(
                knowledge_base_id=context.knowledge_base_id,
                background_tasks=background_tasks,
                file=upload,
                workspace_id=context.workspace_id,
                current_user=context.authenticated_user(),
                settings=settings,
                automation=True,
            )
        except HTTPException as error:
            raise RunnerError(
                f"Automated upload rejected with HTTP {error.status_code}: {error.detail}"
            ) from error
    finally:
        await upload.close()

    if isinstance(response, JSONResponse):
        raise RunnerError(
            f"Automated upload failed with HTTP {response.status_code}: "
            f"{_json_response_payload(response)}"
        )

    file_summary = response.get("file") if isinstance(response, dict) else None
    raw_file_id = getattr(file_summary, "file_id", None)
    if raw_file_id is None:
        raise RunnerError("Automated upload returned no knowledge file ID.")
    file_id = UUID(str(raw_file_id))

    # Calling the service explicitly keeps this runner serial: the route queues
    # the same task for an HTTP request, while this command waits for completion
    # before it allows the source file to be archived.
    await process_knowledge_file(
        file_id,
        context.workspace_id,
        create_chunks=True,
        create_embeddings=True,
    )
    return await _verify_file_completion(
        file_id=file_id,
        context=context,
        settings=settings,
    )


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Automated Flow for root-level PDF files and archive successes."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Root directory containing PDFs (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Archive directory (default: <source-dir>/archived)",
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--workspace-id", type=UUID, default=None)
    parser.add_argument(
        "--knowledge-base-id",
        type=UUID,
        default=None,
        help="Required only when the workspace has multiple ready knowledge bases.",
    )
    parser.add_argument(
        "--max-files",
        type=_positive_int,
        default=None,
        help="Process at most this many selected PDFs (use 1 for a single-file trial).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually upload, process, vectorize, and archive files. Default is dry-run.",
    )
    return parser


async def run_from_args(args: argparse.Namespace) -> BatchSummary:
    settings = get_settings()
    workspace_id = args.workspace_id or settings.default_workspace_id
    archive_dir = args.archive_dir or args.source_dir / "archived"
    files = limit_pdf_files(
        discover_pdf_files(args.source_dir),
        args.max_files,
    )
    context = await _fetch_runner_context(
        email=args.email,
        workspace_id=workspace_id,
        knowledge_base_id=args.knowledge_base_id,
    )

    if settings.knowledge_max_file_bytes < MAX_PDF_BYTES:
        raise RunnerError(
            "KNOWLEDGE_MAX_FILE_BYTES is lower than the requested 100 MiB limit; "
            "the runner refuses to process files that the API would reject."
        )
    if not settings.knowledge_ingestion_enabled:
        raise RunnerError("KNOWLEDGE_INGESTION_ENABLED is disabled.")
    if not settings.knowledge_embeddings_enabled:
        raise RunnerError("KNOWLEDGE_EMBEDDINGS_ENABLED is disabled.")

    print(f"Account: {context.email} ({context.workspace_role})")
    print(f"Workspace: {context.workspace_id}")
    print(f"Knowledge base: {context.knowledge_base_name} ({context.knowledge_base_id})")
    print(f"Source: {args.source_dir}")
    print(f"Archive: {archive_dir}")
    print(f"PDF files selected: {len(files)}")
    for path in files:
        print(f"  - {path.name} ({path.stat().st_size} bytes)")

    async def process(path: Path) -> ProcessingResult:
        print(f"Processing: {path.name}")
        result = await process_pdf_file(path, context=context, settings=settings)
        print(f"  {result.detail}")
        return result

    return await run_batch(
        files,
        archive_dir=archive_dir,
        process_file=process,
        execute=args.execute,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()
    try:
        summary = asyncio.run(run_from_args(args))
    except RunnerError as error:
        print(f"Runner stopped before processing: {error}")
        raise SystemExit(1) from error

    if summary.dry_run:
        print(f"Dry-run only; no files changed. Selected {len(summary.dry_run)} PDF file(s).")
    else:
        print(f"Completed and archived: {len(summary.completed)}")
        print(f"Failed and left in place: {len(summary.failed)}")
        for filename, detail in summary.failed:
            print(f"  - {filename}: {detail}")
    raise SystemExit(1 if summary.failed else 0)


if __name__ == "__main__":
    main()
