import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.dev_identity import ensure_development_identity, get_persistence_user_id
from app.core.knowledge_access import require_knowledge_base_permission
from app.db.session import get_db_connection
from app.services.business_import_application import (
    BusinessImportApplicationError,
    BusinessImportConflictError,
    apply_approved_import_job,
)
from app.services.business_imports import (
    PROMPT_VERSION,
    BusinessImportProviderError,
    BusinessImportValidationError,
    build_business_import_messages,
    parse_and_validate_agent_output,
    stream_provider_completion,
)
from app.services.document_parsing import ParsedDocument

router = APIRouter(tags=["business-imports"])

PROFILE_NAME = "product_and_price"


class BusinessImportAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    profile: Literal["product_and_price"] = PROFILE_NAME


class BusinessImportDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    review_comment: str | None = Field(default=None, alias="reviewComment", max_length=4_000)


class BusinessImportProposalResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    applied_at: str | None = Field(alias="appliedAt")
    candidate_ref: str = Field(alias="candidateRef")
    created_at: str = Field(alias="createdAt")
    error_message: str | None = Field(alias="errorMessage")
    operation: str
    patch: dict[str, Any]
    proposal_id: str = Field(alias="proposalId")
    review_comment: str | None = Field(alias="reviewComment")
    review_explanation: dict[str, Any] = Field(alias="reviewExplanation")
    reviewed_at: str | None = Field(alias="reviewedAt")
    source_references: list[dict[str, Any]] = Field(alias="sourceReferences")
    status: str
    target_entity_type: str = Field(alias="targetEntityType")
    updated_at: str = Field(alias="updatedAt")


class BusinessImportJobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_at: str = Field(alias="createdAt")
    error_message: str | None = Field(alias="errorMessage")
    finished_at: str | None = Field(alias="finishedAt")
    job_id: str = Field(alias="jobId")
    model: str
    parsed_document_id: str = Field(alias="parsedDocumentId")
    profile: str
    prompt_version: str = Field(alias="promptVersion")
    proposals: list[BusinessImportProposalResponse]
    raw_provider_output: str | None = Field(alias="rawProviderOutput")
    review_report: dict[str, Any] | None = Field(alias="reviewReport")
    schema_version: str = Field(alias="schemaVersion")
    source_file_id: str = Field(alias="sourceFileId")
    status: str
    updated_at: str = Field(alias="updatedAt")


class BusinessImportJobListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobs: list[BusinessImportJobResponse]


PARSED_DOCUMENT_FOR_IMPORT_QUERY = text(
    """
    SELECT parsed."document" AS document,
           parsed."fileHash" AS file_hash,
           parsed."fileId" AS file_id,
           parsed."id" AS parsed_document_id,
           parsed."knowledgeBaseId" AS knowledge_base_id,
           parsed."workspaceId" AS workspace_id
    FROM "KnowledgeParsedDocument" AS parsed
    INNER JOIN "KnowledgeFile" AS file ON file."id" = parsed."fileId"
    WHERE parsed."id" = :parsed_document_id
      AND parsed."knowledgeBaseId" = :knowledge_base_id
      AND parsed."workspaceId" = :workspace_id
      AND file."workspaceId" = :workspace_id
      AND file."knowledgeBaseId" = :knowledge_base_id
      AND file."status" = 'ready'
    LIMIT 1
    """
)

INSERT_IMPORT_JOB_QUERY = text(
    """
    INSERT INTO "ImportJob" (
        "workspaceId", "knowledgeBaseId", "sourceFileId", "parsedDocumentId", "profile",
        "schemaVersion", "promptVersion", "model", "status", "createdBy"
    ) VALUES (
        :workspace_id, :knowledge_base_id, :source_file_id, :parsed_document_id, :profile,
        :schema_version, :prompt_version, :model, 'analyzing', :created_by
    )
    RETURNING "id"
    """
)

SET_IMPORT_JOB_RESULT_QUERY = text(
    """
    UPDATE "ImportJob"
    SET "status" = 'awaiting_review', "reviewReport" = CAST(:review_report AS jsonb),
        "rawProviderOutput" = :raw_provider_output, "errorMessage" = NULL,
        "finishedAt" = CURRENT_TIMESTAMP, "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :job_id AND "workspaceId" = :workspace_id
    """
)

SET_IMPORT_JOB_FAILURE_QUERY = text(
    """
    UPDATE "ImportJob"
    SET "status" = :status, "errorMessage" = :error_message,
        "reviewReport" = CAST(:review_report AS jsonb),
        "rawProviderOutput" = :raw_provider_output, "finishedAt" = CURRENT_TIMESTAMP,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :job_id AND "workspaceId" = :workspace_id
    """
)

INSERT_IMPORT_PROPOSAL_QUERY = text(
    """
    INSERT INTO "ImportProposal" (
        "jobId", "workspaceId", "candidateRef", "targetEntityType", "operation", "patch",
        "sourceReferences", "reviewExplanation", "status"
    ) VALUES (
        :job_id, :workspace_id, :candidate_ref, 'product', 'insert', CAST(:patch AS jsonb),
        CAST(:source_references AS jsonb), CAST(:review_explanation AS jsonb), :proposal_status
    )
    """
)

JOB_LIST_QUERY = text(
    """
    SELECT "id" AS job_id, "sourceFileId" AS source_file_id,
           "parsedDocumentId" AS parsed_document_id, "profile", "schemaVersion" AS schema_version,
           "promptVersion" AS prompt_version, "model", "status", "reviewReport" AS review_report,
           "rawProviderOutput" AS raw_provider_output, "errorMessage" AS error_message,
           "createdAt" AS created_at, "updatedAt" AS updated_at,
           "finishedAt" AS finished_at
    FROM "ImportJob"
    WHERE "workspaceId" = :workspace_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "parsedDocumentId" = :parsed_document_id
    ORDER BY "createdAt" DESC, "id" DESC
    LIMIT 20
    """
)

IMPORT_JOB_SCOPE_QUERY = text(
    """
    SELECT "knowledgeBaseId" AS knowledge_base_id
    FROM "ImportJob"
    WHERE "id" = :job_id AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

PROPOSALS_FOR_JOBS_QUERY = text(
    """
    SELECT "id" AS proposal_id, "jobId" AS job_id, "candidateRef" AS candidate_ref,
           "targetEntityType" AS target_entity_type, "operation", "patch",
           "sourceReferences" AS source_references, "reviewExplanation" AS review_explanation,
           "status", "reviewComment" AS review_comment, "reviewedAt" AS reviewed_at,
           "appliedAt" AS applied_at, "errorMessage" AS error_message,
           "createdAt" AS created_at, "updatedAt" AS updated_at
    FROM "ImportProposal"
    WHERE "workspaceId" = :workspace_id
      AND "jobId" IN :job_ids
    ORDER BY "createdAt" ASC, "id" ASC
    """
).bindparams(bindparam("job_ids", expanding=True))

DECIDE_PROPOSAL_QUERY = text(
    """
    UPDATE "ImportProposal"
    SET "status" = :proposal_status, "reviewComment" = :review_comment,
        "reviewedBy" = :reviewed_by, "reviewedAt" = CURRENT_TIMESTAMP,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :proposal_id
      AND "workspaceId" = :workspace_id
      AND "jobId" = :job_id
      AND "status" = 'pending'
    RETURNING "id"
    """
)

AUDIT_IMPORT_EVENT_QUERY = text(
    """
    INSERT INTO "AuditLog" ("action", "actorUserId", "metadata", "workspaceId")
    VALUES (:action, :actor_user_id, CAST(:metadata AS jsonb), :workspace_id)
    """
)


def _sse_event(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _json_object(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _json_list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def _iso_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _proposal_response(row: dict[str, object]) -> BusinessImportProposalResponse:
    return BusinessImportProposalResponse(
        appliedAt=_iso_timestamp(row["applied_at"]),
        candidateRef=str(row["candidate_ref"]),
        createdAt=_iso_timestamp(row["created_at"]) or "",
        errorMessage=row["error_message"] if isinstance(row["error_message"], str) else None,
        operation=str(row["operation"]),
        patch=_json_object(row["patch"]) or {},
        proposalId=str(row["proposal_id"]),
        reviewComment=row["review_comment"] if isinstance(row["review_comment"], str) else None,
        reviewExplanation=_json_object(row["review_explanation"]) or {},
        reviewedAt=_iso_timestamp(row["reviewed_at"]),
        sourceReferences=_json_list(row["source_references"]),
        status=str(row["status"]),
        targetEntityType=str(row["target_entity_type"]),
        updatedAt=_iso_timestamp(row["updated_at"]) or "",
    )


def _job_response(
    row: dict[str, object],
    proposals: list[BusinessImportProposalResponse],
) -> BusinessImportJobResponse:
    return BusinessImportJobResponse(
        createdAt=_iso_timestamp(row["created_at"]) or "",
        errorMessage=row["error_message"] if isinstance(row["error_message"], str) else None,
        finishedAt=_iso_timestamp(row["finished_at"]),
        jobId=str(row["job_id"]),
        model=str(row["model"]),
        parsedDocumentId=str(row["parsed_document_id"]),
        profile=str(row["profile"]),
        promptVersion=str(row["prompt_version"]),
        proposals=proposals,
        rawProviderOutput=(
            row["raw_provider_output"]
            if isinstance(row["raw_provider_output"], str)
            else None
        ),
        reviewReport=_json_object(row["review_report"]),
        schemaVersion=str(row["schema_version"]),
        sourceFileId=str(row["source_file_id"]),
        status=str(row["status"]),
        updatedAt=_iso_timestamp(row["updated_at"]) or "",
    )


async def _load_parsed_document(
    *,
    knowledge_base_id: UUID,
    parsed_document_id: UUID,
    workspace_id: UUID,
) -> tuple[dict[str, object], ParsedDocument]:
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                PARSED_DOCUMENT_FOR_IMPORT_QUERY,
                {
                    "knowledge_base_id": knowledge_base_id,
                    "parsed_document_id": parsed_document_id,
                    "workspace_id": workspace_id,
                },
            )
            row = result.mappings().first()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not load the ParsedDocument for business import.",
        ) from error
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ParsedDocument not found or its source file is not ready.",
        )
    raw_document = _json_object(row["document"])
    if raw_document is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The persisted ParsedDocument is invalid and cannot be analyzed.",
        )
    try:
        document = ParsedDocument.model_validate(raw_document)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The persisted ParsedDocument is invalid and cannot be analyzed.",
        ) from error
    return dict(row), document


async def _require_import_job_manage_permission(
    *,
    current_user: AuthenticatedUser,
    job_id: UUID,
    workspace_id: UUID,
) -> UUID:
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                IMPORT_JOB_SCOPE_QUERY,
                {"job_id": job_id, "workspace_id": workspace_id},
            )
            row = result.mappings().first()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not load the business import job scope.",
        ) from error
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business import job not found in this workspace.",
        )
    knowledge_base_id = UUID(str(row["knowledge_base_id"]))
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    return knowledge_base_id


async def _create_import_job(
    *,
    current_user: AuthenticatedUser,
    knowledge_base_id: UUID,
    parsed_row: dict[str, object],
    profile: str,
    schema_version: str,
    model: str,
    workspace_id: UUID,
) -> UUID:
    try:
        actor_user_id = get_persistence_user_id(current_user)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                if current_user.is_development:
                    await ensure_development_identity(connection, current_user, workspace_id)
                result = await connection.execute(
                    INSERT_IMPORT_JOB_QUERY,
                    {
                        "created_by": actor_user_id,
                        "knowledge_base_id": knowledge_base_id,
                        "model": model,
                        "parsed_document_id": parsed_row["parsed_document_id"],
                        "profile": profile,
                        "prompt_version": PROMPT_VERSION,
                        "schema_version": schema_version,
                        "source_file_id": parsed_row["file_id"],
                        "workspace_id": workspace_id,
                    },
                )
                return UUID(str(result.scalar_one()))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not create the business import job.",
        ) from error


async def _persist_analysis_result(
    *,
    analysis: Any,
    job_id: UUID,
    raw_provider_output: str,
    workspace_id: UUID,
) -> None:
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                for proposal in analysis.proposals:
                    proposal_status = (
                        "schema_review_required"
                        if proposal.review_explanation["status"] == "out_of_scope"
                        else "pending"
                    )
                    await connection.execute(
                        INSERT_IMPORT_PROPOSAL_QUERY,
                        {
                            "candidate_ref": proposal.candidate_ref,
                            "job_id": job_id,
                            "patch": json.dumps(proposal.patch, ensure_ascii=False),
                            "proposal_status": proposal_status,
                            "review_explanation": json.dumps(
                                proposal.review_explanation,
                                ensure_ascii=False,
                            ),
                            "source_references": json.dumps(
                                [
                                    item.model_dump(by_alias=True, mode="json")
                                    for item in proposal.source_references
                                ],
                                ensure_ascii=False,
                            ),
                            "workspace_id": workspace_id,
                        },
                    )
                await connection.execute(
                    SET_IMPORT_JOB_RESULT_QUERY,
                    {
                        "job_id": job_id,
                        "raw_provider_output": raw_provider_output,
                        "review_report": json.dumps(
                            analysis.review_report.model_dump(by_alias=True, mode="json"),
                            ensure_ascii=False,
                        ),
                        "workspace_id": workspace_id,
                    },
                )
    except SQLAlchemyError as error:
        raise BusinessImportValidationError(
            "FastAPI could not persist the agent review result."
        ) from error


async def _mark_job_failed(
    *,
    job_id: UUID,
    raw_provider_output: str,
    status_value: Literal["failed", "schema_review_required"],
    message: str,
    review_report: dict[str, Any],
    workspace_id: UUID,
) -> None:
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(
                    SET_IMPORT_JOB_FAILURE_QUERY,
                    {
                        "error_message": message[:4_000],
                        "job_id": job_id,
                        "raw_provider_output": raw_provider_output,
                        "review_report": json.dumps(review_report, ensure_ascii=False),
                        "status": status_value,
                        "workspace_id": workspace_id,
                    },
                )
    except SQLAlchemyError:
        return


def _failure_review_report(
    error: BusinessImportProviderError | BusinessImportValidationError,
    *,
    raw_provider_output: str,
) -> dict[str, Any]:
    diagnostics = (
        error.diagnostics
        if isinstance(error, BusinessImportValidationError) and error.diagnostics is not None
        else {}
    )
    details = diagnostics.get("details")
    if not isinstance(details, dict):
        details = {}
    details = {
        **details,
        "rawProviderOutputCharacters": len(raw_provider_output),
    }
    is_provider_error = isinstance(error, BusinessImportProviderError)
    return {
        "diagnostics": {
            "outcome": "rejected",
            "stage": diagnostics.get(
                "stage", "provider" if is_provider_error else "validation"
            ),
            "code": diagnostics.get(
                "code",
                (
                    "business_import.provider_failed"
                    if is_provider_error
                    else "business_import.validation_failed"
                ),
            ),
            "message": str(error),
            "details": details,
            "checks": [
                {
                    "name": "provider_response",
                    "status": "passed" if raw_provider_output else "not_available",
                },
                {
                    "name": "candidate_validation",
                    "status": "failed" if not is_provider_error else "not_run",
                },
            ],
        }
    }


@router.post(
    "/knowledge-bases/{knowledge_base_id}/parsed-documents/{parsed_document_id}/business-imports/stream",
    response_model=None,
)
async def stream_business_import_analysis(
    knowledge_base_id: UUID,
    parsed_document_id: UUID,
    payload: BusinessImportAnalyzeRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    api_key, base_url, model = settings.resolved_business_import_provider()
    if not api_key:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "business_import:provider_unavailable",
                "message": "Configure BUSINESS_IMPORT_API_KEY or DEEPSEEK_API_KEY.",
            },
        )
    parsed_row, document = await _load_parsed_document(
        knowledge_base_id=knowledge_base_id,
        parsed_document_id=parsed_document_id,
        workspace_id=workspace_id,
    )
    block_payloads = [block.model_dump(by_alias=True) for block in document.blocks]
    messages = build_business_import_messages(
        blocks=block_payloads,
        profile_name=payload.profile,
    )
    job_id = await _create_import_job(
        current_user=current_user,
        knowledge_base_id=knowledge_base_id,
        model=model,
        parsed_row=parsed_row,
        profile=payload.profile,
        schema_version=document.schema_version,
        workspace_id=workspace_id,
    )

    async def event_stream() -> AsyncIterator[str]:
        raw_provider_parts: list[str] = []
        yield _sse_event({"type": "status", "jobId": str(job_id), "stage": "analyzing"})
        try:
            async for delta in stream_provider_completion(
                api_key=api_key,
                base_url=base_url,
                messages=messages,
                model=model,
                on_raw_delta=raw_provider_parts.append,
                timeout_seconds=settings.chat_provider_timeout_seconds,
            ):
                yield _sse_event({"type": "text-delta", "delta": delta})
            raw_provider_output = "".join(raw_provider_parts)
            yield _sse_event({"type": "status", "jobId": str(job_id), "stage": "validating"})
            analysis = parse_and_validate_agent_output(
                raw_provider_output,
                blocks=block_payloads,
                file_hash=str(parsed_row["file_hash"]),
                parsed_document_id=parsed_document_id,
                profile_name=payload.profile,
                source_file_id=UUID(str(parsed_row["file_id"])),
            )
            yield _sse_event({"type": "status", "jobId": str(job_id), "stage": "persisting"})
            await _persist_analysis_result(
                analysis=analysis,
                job_id=job_id,
                raw_provider_output=raw_provider_output,
                workspace_id=workspace_id,
            )
            yield _sse_event(
                {
                    "type": "result",
                    "jobId": str(job_id),
                    "reviewReport": analysis.review_report.model_dump(by_alias=True, mode="json"),
                    "proposalCount": len(analysis.proposals),
                    "diagnostics": analysis.review_report.diagnostics,
                }
            )
        except (BusinessImportProviderError, BusinessImportValidationError) as error:
            raw_provider_output = "".join(raw_provider_parts)
            review_report = _failure_review_report(
                error,
                raw_provider_output=raw_provider_output,
            )
            await _mark_job_failed(
                job_id=job_id,
                message=str(error),
                raw_provider_output=raw_provider_output,
                review_report=review_report,
                status_value="failed",
                workspace_id=workspace_id,
            )
            yield _sse_event(
                {
                    "type": "error",
                    "message": str(error),
                    "diagnostics": review_report["diagnostics"],
                }
            )
        except asyncio.CancelledError:
            raw_provider_output = "".join(raw_provider_parts)
            await _mark_job_failed(
                job_id=job_id,
                message="The browser disconnected before the business import analysis completed.",
                raw_provider_output=raw_provider_output,
                review_report={
                    "diagnostics": {
                        "outcome": "rejected",
                        "stage": "client_disconnect",
                        "code": "business_import.client_disconnected",
                        "message": (
                            "The browser disconnected before the business import analysis "
                            "completed."
                        ),
                        "details": {
                            "rawProviderOutputCharacters": len(raw_provider_output)
                        },
                        "checks": [],
                    }
                },
                status_value="failed",
                workspace_id=workspace_id,
            )
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/parsed-documents/{parsed_document_id}/business-imports",
    response_model=BusinessImportJobListResponse,
)
async def list_business_import_jobs(
    knowledge_base_id: UUID,
    parsed_document_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> BusinessImportJobListResponse | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    try:
        async with get_db_connection() as connection:
            job_result = await connection.execute(
                JOB_LIST_QUERY,
                {
                    "knowledge_base_id": knowledge_base_id,
                    "parsed_document_id": parsed_document_id,
                    "workspace_id": workspace_id,
                },
            )
            job_rows = [dict(row) for row in job_result.mappings().all()]
            if not job_rows:
                return BusinessImportJobListResponse(jobs=[])
            job_ids = [row["job_id"] for row in job_rows]
            proposal_result = await connection.execute(
                PROPOSALS_FOR_JOBS_QUERY,
                {"job_ids": job_ids, "workspace_id": workspace_id},
            )
            grouped: dict[object, list[BusinessImportProposalResponse]] = {
                job_id: [] for job_id in job_ids
            }
            for proposal_row in proposal_result.mappings().all():
                row = dict(proposal_row)
                grouped[row["job_id"]].append(_proposal_response(row))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "database:unavailable",
                "cause": "FastAPI could not load business import jobs.",
            },
        )
    return BusinessImportJobListResponse(
        jobs=[_job_response(row, grouped[row["job_id"]]) for row in job_rows]
    )


@router.post(
    "/business-import-jobs/{job_id}/proposals/{proposal_id}/{decision}",
    response_model=None,
)
async def decide_business_import_proposal(
    job_id: UUID,
    proposal_id: UUID,
    decision: Literal["approve", "reject"],
    payload: BusinessImportDecisionRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    await _require_import_job_manage_permission(
        current_user=current_user,
        job_id=job_id,
        workspace_id=workspace_id,
    )
    try:
        actor_user_id = get_persistence_user_id(current_user)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                if current_user.is_development:
                    await ensure_development_identity(connection, current_user, workspace_id)
                result = await connection.execute(
                    DECIDE_PROPOSAL_QUERY,
                    {
                        "job_id": job_id,
                        "proposal_id": proposal_id,
                        "proposal_status": "approved" if decision == "approve" else "rejected",
                        "review_comment": payload.review_comment,
                        "reviewed_by": actor_user_id,
                        "workspace_id": workspace_id,
                    },
                )
                if result.scalar_one_or_none() is None:
                    return JSONResponse(
                        status_code=status.HTTP_409_CONFLICT,
                        content={
                            "code": "business_import:proposal_not_pending",
                            "message": "The proposal is not pending review in this workspace.",
                        },
                    )
                await connection.execute(
                    AUDIT_IMPORT_EVENT_QUERY,
                    {
                        "action": (
                            "import.proposal_approved"
                            if decision == "approve"
                            else "import.proposal_rejected"
                        ),
                        "actor_user_id": actor_user_id,
                        "metadata": json.dumps(
                            {"jobId": str(job_id), "proposalId": str(proposal_id)}
                        ),
                        "workspace_id": workspace_id,
                    },
                )
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "database:unavailable",
                "cause": "FastAPI could not update the business import proposal.",
            },
        )
    return JSONResponse({"jobId": str(job_id), "proposalId": str(proposal_id), "status": decision})


@router.post("/business-import-jobs/{job_id}/apply", response_model=None)
async def apply_business_import_job(
    job_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    await _require_import_job_manage_permission(
        current_user=current_user,
        job_id=job_id,
        workspace_id=workspace_id,
    )
    try:
        actor_user_id = get_persistence_user_id(current_user)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error
    try:
        async with get_db_connection() as connection:
            if current_user.is_development:
                async with connection.begin():
                    await ensure_development_identity(connection, current_user, workspace_id)
            applied = await apply_approved_import_job(
                connection,
                actor_user_id=actor_user_id,
                job_id=job_id,
                workspace_id=workspace_id,
            )
    except BusinessImportConflictError as error:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "business_import:conflict", "message": str(error)},
        )
    except BusinessImportApplicationError as error:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "business_import:not_applicable", "message": str(error)},
        )
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "database:unavailable",
                "cause": "FastAPI could not apply approved business import proposals.",
            },
        )
    return JSONResponse(
        {
            "jobId": str(job_id),
            "appliedProposalIds": [str(item.proposal_id) for item in applied],
            "researchIds": [str(item.research_id) for item in applied],
        }
    )
