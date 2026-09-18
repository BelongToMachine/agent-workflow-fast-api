"""Controlled transactional application of approved business import proposals."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text

from app.services.business_imports import (
    BusinessImportValidationError,
    SourceReference,
    ValidatedProposal,
    build_product_write_plan,
)


class BusinessImportApplicationError(RuntimeError):
    """Raised when an approved import cannot safely be applied."""


class BusinessImportConflictError(BusinessImportApplicationError):
    """Raised instead of silently creating or overwriting a duplicate product."""


@dataclass(frozen=True)
class AppliedImportProposal:
    proposal_id: UUID
    research_id: UUID


JOB_FOR_APPLICATION_QUERY = text(
    """
    SELECT "id", "status", "sourceFileId" AS source_file_id,
           "parsedDocumentId" AS parsed_document_id
    FROM "ImportJob"
    WHERE "id" = :job_id AND "workspaceId" = :workspace_id
    FOR UPDATE
    """
)

APPROVED_PROPOSALS_QUERY = text(
    """
    SELECT "id" AS proposal_id, "candidateRef" AS candidate_ref,
           "patch", "reviewExplanation" AS review_explanation,
           "sourceReferences" AS source_references
    FROM "ImportProposal"
    WHERE "jobId" = :job_id
      AND "workspaceId" = :workspace_id
      AND "status" = 'approved'
    ORDER BY "createdAt" ASC, "id" ASC
    FOR UPDATE
    """
)

SET_JOB_APPLYING_QUERY = text(
    """
    UPDATE "ImportJob"
    SET "status" = 'applying', "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :job_id AND "workspaceId" = :workspace_id
    """
)

SET_PROPOSAL_APPLIED_QUERY = text(
    """
    UPDATE "ImportProposal"
    SET "status" = 'applied', "appliedAt" = CURRENT_TIMESTAMP,
        "updatedAt" = CURRENT_TIMESTAMP, "errorMessage" = NULL
    WHERE "id" = :proposal_id AND "workspaceId" = :workspace_id
    """
)

PENDING_PROPOSAL_COUNT_QUERY = text(
    """
    SELECT COUNT(*) AS proposal_count
    FROM "ImportProposal"
    WHERE "jobId" = :job_id
      AND "workspaceId" = :workspace_id
      AND "status" IN ('pending', 'approved')
    """
)

FINISH_JOB_QUERY = text(
    """
    UPDATE "ImportJob"
    SET "status" = :status,
        "finishedAt" = CASE WHEN :status = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :job_id AND "workspaceId" = :workspace_id
    """
)

FIND_EXISTING_RESEARCH_QUERY = text(
    """
    SELECT research."id"
    FROM "RealProductResearch" AS research
    INNER JOIN "KnowledgeFile" AS source ON source."id" = research."sourceFileId"
    WHERE source."workspaceId" = :workspace_id
      AND lower(research."productName") = lower(:product_name)
    LIMIT 1
    """
)

INSERT_RESEARCH_QUERY = text(
    """
    INSERT INTO "RealProductResearch" (
        "productName", "category", "brand", "productIntro", "productHighlights",
        "productFeatures", "procurementConditions", "shippingTime", "contactPerson",
        "supplierContact", "rawData", "sourceFileId", "sourceSheet", "sourceRow",
        "sourceLocator"
    ) VALUES (
        :product_name, :category, :brand, :product_intro, :product_highlights,
        :product_features, :procurement_conditions, :shipping_time, :contact_person,
        :supplier_contact, CAST(:raw_data AS jsonb), :source_file_id, :source_sheet,
        :source_row, CAST(:source_locator AS jsonb)
    )
    RETURNING "id"
    """
)

INSERT_OPERATION_QUERY = text(
    """
    INSERT INTO "ProductOperation" (
        "researchId", "logisticsTerm", "operationStatus", "promotionStatus", "proposer",
        "qualifications", "targetChannels", "nextAction", "notes", "rawData",
        "sourceFileId", "sourceSheet", "sourceRow", "sourceLocator"
    ) VALUES (
        :research_id, :logistics_term, :operation_status, :promotion_status, :proposer,
        :qualifications, :target_channels, :next_action, :notes, CAST(:raw_data AS jsonb),
        :source_file_id, :source_sheet, :source_row, CAST(:source_locator AS jsonb)
    )
    RETURNING "id"
    """
)

INSERT_PRICE_QUERY = text(
    """
    INSERT INTO "ProductPrice" (
        "researchId", "variant", "priceMin", "priceMax", "currency", "priceType",
        "rawText", "sourceFileId", "sourceSheet", "sourceRow", "sourceLocator"
    ) VALUES (
        :research_id, :variant, :price_min, :price_max, :currency, :price_type,
        :raw_text, :source_file_id, :source_sheet, :source_row, CAST(:source_locator AS jsonb)
    )
    RETURNING "id"
    """
)

INSERT_DOCUMENT_QUERY = text(
    """
    INSERT INTO "ProductDocument" (
        "researchId", "documentType", "displayName", "fileReference", "rawText",
        "sourceFileId", "sourceSheet", "sourceRow", "sourceLocator"
    ) VALUES (
        :research_id, :document_type, :display_name, :file_reference, :raw_text,
        :source_file_id, :source_sheet, :source_row, CAST(:source_locator AS jsonb)
    )
    RETURNING "id"
    """
)

INSERT_IMPORTED_FACT_QUERY = text(
    """
    INSERT INTO "ImportedFact" (
        "workspaceId", "proposalId", "sourceFileId", "parsedDocumentId", "entityType",
        "entityId", "fieldPath", "valueJson", "blockId", "dataPath", "sourceLocator",
        "quote"
    ) VALUES (
        :workspace_id, :proposal_id, :source_file_id, :parsed_document_id, :entity_type,
        :entity_id, :field_path, CAST(:value_json AS jsonb), :block_id, :data_path,
        CAST(:source_locator AS jsonb), :quote
    )
    """
)

INSERT_AUDIT_LOG_QUERY = text(
    """
    INSERT INTO "AuditLog" ("action", "actorUserId", "metadata", "workspaceId")
    VALUES (:action, :actor_user_id, CAST(:metadata AS jsonb), :workspace_id)
    """
)


async def apply_approved_import_job(
    connection: Any,
    *,
    actor_user_id: UUID,
    job_id: UUID,
    workspace_id: UUID,
) -> list[AppliedImportProposal]:
    """Apply every explicitly approved proposal in one database transaction."""
    async with connection.begin():
        job_result = await connection.execute(
            JOB_FOR_APPLICATION_QUERY,
            {"job_id": job_id, "workspace_id": workspace_id},
        )
        job = job_result.mappings().first()
        if job is None:
            raise BusinessImportApplicationError("Import job not found in this workspace.")
        if job["status"] not in {"awaiting_review", "completed"}:
            raise BusinessImportApplicationError(
                "Import job is not ready to apply approved proposals."
            )

        proposal_result = await connection.execute(
            APPROVED_PROPOSALS_QUERY,
            {"job_id": job_id, "workspace_id": workspace_id},
        )
        proposals = proposal_result.mappings().all()
        if not proposals:
            raise BusinessImportApplicationError("No approved proposals are ready to apply.")

        await connection.execute(
            SET_JOB_APPLYING_QUERY,
            {"job_id": job_id, "workspace_id": workspace_id},
        )
        applied: list[AppliedImportProposal] = []
        for row in proposals:
            proposal = _proposal_from_row(row)
            _assert_proposal_scope(
                proposal,
                source_file_id=UUID(str(job["source_file_id"])),
                parsed_document_id=UUID(str(job["parsed_document_id"])),
            )
            applied.append(
                await _apply_product_proposal(
                    connection,
                    proposal=proposal,
                    proposal_id=UUID(str(row["proposal_id"])),
                    workspace_id=workspace_id,
                )
            )
            await connection.execute(
                SET_PROPOSAL_APPLIED_QUERY,
                {"proposal_id": row["proposal_id"], "workspace_id": workspace_id},
            )

        count_result = await connection.execute(
            PENDING_PROPOSAL_COUNT_QUERY,
            {"job_id": job_id, "workspace_id": workspace_id},
        )
        remaining = int(count_result.mappings().one()["proposal_count"])
        final_status = "awaiting_review" if remaining else "completed"
        await connection.execute(
            FINISH_JOB_QUERY,
            {"job_id": job_id, "workspace_id": workspace_id, "status": final_status},
        )
        await connection.execute(
            INSERT_AUDIT_LOG_QUERY,
            {
                "action": "import.proposals_applied",
                "actor_user_id": actor_user_id,
                "metadata": json.dumps(
                    {
                        "jobId": str(job_id),
                        "proposalIds": [str(item.proposal_id) for item in applied],
                    }
                ),
                "workspace_id": workspace_id,
            },
        )
        return applied


def _proposal_from_row(row: Any) -> ValidatedProposal:
    try:
        references = [
            SourceReference.model_validate(reference)
            for reference in _json_value(row["source_references"])
        ]
    except (KeyError, TypeError, ValidationError) as error:
        raise BusinessImportApplicationError(
            "Stored proposal has invalid source references and cannot be applied."
        ) from error
    patch = _json_value(row["patch"])
    review_explanation = _json_value(row["review_explanation"])
    if not isinstance(patch, dict) or not isinstance(review_explanation, dict):
        raise BusinessImportApplicationError("Stored proposal has an invalid patch.")
    return ValidatedProposal(
        candidate_ref=str(row["candidate_ref"]),
        patch=patch,
        review_explanation=review_explanation,
        source_references=references,
    )


def _json_value(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise BusinessImportApplicationError(
                "Stored proposal contains invalid JSON."
            ) from error
    return value


def _assert_proposal_scope(
    proposal: ValidatedProposal,
    *,
    source_file_id: UUID,
    parsed_document_id: UUID,
) -> None:
    if any(
        reference.source_file_id != source_file_id
        or reference.parsed_document_id != parsed_document_id
        for reference in proposal.source_references
    ):
        raise BusinessImportApplicationError(
            "Stored proposal references a source outside its import job."
        )


async def _apply_product_proposal(
    connection: Any,
    *,
    proposal: ValidatedProposal,
    proposal_id: UUID,
    workspace_id: UUID,
) -> AppliedImportProposal:
    try:
        plan = build_product_write_plan(proposal)
    except BusinessImportValidationError as error:
        raise BusinessImportApplicationError("Stored proposal is no longer valid.") from error

    product_name = str(plan.product.values["productName"])
    duplicate_result = await connection.execute(
        FIND_EXISTING_RESEARCH_QUERY,
        {"workspace_id": workspace_id, "product_name": product_name},
    )
    if duplicate_result.mappings().first() is not None:
        raise BusinessImportConflictError(
            f"A product named {product_name!r} already exists in this workspace."
        )

    research_id = await _insert_research(connection, plan.product)
    await _insert_facts(
        connection,
        proposal_id=proposal_id,
        workspace_id=workspace_id,
        entity_id=research_id,
        entity_key="product",
        entity_type="product",
        plan=plan,
        values=plan.product.values,
    )
    if plan.operation is not None:
        operation_id = await _insert_operation(connection, research_id, plan.operation)
        await _insert_facts(
            connection,
            proposal_id=proposal_id,
            workspace_id=workspace_id,
            entity_id=operation_id,
            entity_key="operation",
            entity_type="product_operation",
            plan=plan,
            values=plan.operation.values,
        )
    for index, price in enumerate(plan.prices):
        price_id = await _insert_price(connection, research_id, price)
        await _insert_facts(
            connection,
            proposal_id=proposal_id,
            workspace_id=workspace_id,
            entity_id=price_id,
            entity_key=f"prices[{index}]",
            entity_type="product_price",
            plan=plan,
            values=price.values,
        )
    for index, document in enumerate(plan.documents):
        document_id = await _insert_document(connection, research_id, document)
        await _insert_facts(
            connection,
            proposal_id=proposal_id,
            workspace_id=workspace_id,
            entity_id=document_id,
            entity_key=f"documents[{index}]",
            entity_type="product_document",
            plan=plan,
            values=document.values,
        )
    return AppliedImportProposal(proposal_id=proposal_id, research_id=research_id)


def _source_position(reference: SourceReference) -> tuple[str, int]:
    locator = reference.locator
    sheet = locator.get("sheet")
    if isinstance(sheet, str) and sheet.strip():
        source_sheet = sheet.strip()[:64]
    else:
        source_sheet = "document"
    for key, offset in (("row", 0), ("page", 1_000_000), ("slide", 2_000_000)):
        value = locator.get(key)
        if type(value) is int and value >= 0:
            return source_sheet, offset + value
    return source_sheet, 0


def _source_params(reference: SourceReference) -> dict[str, object]:
    source_sheet, source_row = _source_position(reference)
    return {
        "source_file_id": reference.source_file_id,
        "source_locator": json.dumps(reference.locator, ensure_ascii=False),
        "source_row": source_row,
        "source_sheet": source_sheet,
    }


async def _insert_research(connection: Any, write: Any) -> UUID:
    values = write.values
    params = {
        "brand": values.get("brand"),
        "category": values.get("category"),
        "contact_person": values.get("contactPerson"),
        "procurement_conditions": values.get("procurementConditions"),
        "product_features": values.get("productFeatures"),
        "product_highlights": values.get("productHighlights"),
        "product_intro": values.get("productIntro"),
        "product_name": values["productName"],
        "raw_data": json.dumps(values, ensure_ascii=False),
        "shipping_time": values.get("shippingTime"),
        "supplier_contact": values.get("supplierContact"),
        **_source_params(write.primary_source),
    }
    result = await connection.execute(INSERT_RESEARCH_QUERY, params)
    return UUID(str(result.scalar_one()))


async def _insert_operation(connection: Any, research_id: UUID, write: Any) -> UUID:
    values = write.values
    params = {
        "logistics_term": values.get("logisticsTerm"),
        "next_action": values.get("nextAction"),
        "notes": values.get("notes"),
        "operation_status": values.get("operationStatus", "unknown"),
        "promotion_status": values.get("promotionStatus"),
        "proposer": values.get("proposer"),
        "qualifications": values.get("qualifications"),
        "raw_data": json.dumps(values, ensure_ascii=False),
        "research_id": research_id,
        "target_channels": values.get("targetChannels"),
        **_source_params(write.primary_source),
    }
    result = await connection.execute(INSERT_OPERATION_QUERY, params)
    return UUID(str(result.scalar_one()))


async def _insert_price(connection: Any, research_id: UUID, write: Any) -> UUID:
    values = write.values
    params = {
        "currency": values["currency"],
        "price_max": values.get("priceMax"),
        "price_min": values["priceMin"],
        "price_type": values["priceType"],
        "raw_text": values["rawText"],
        "research_id": research_id,
        "variant": values["variant"],
        **_source_params(write.primary_source),
    }
    result = await connection.execute(INSERT_PRICE_QUERY, params)
    return UUID(str(result.scalar_one()))


async def _insert_document(connection: Any, research_id: UUID, write: Any) -> UUID:
    values = write.values
    params = {
        "display_name": values.get("displayName"),
        "document_type": values["documentType"],
        "file_reference": values["fileReference"],
        "raw_text": values["rawText"],
        "research_id": research_id,
        **_source_params(write.primary_source),
    }
    result = await connection.execute(INSERT_DOCUMENT_QUERY, params)
    return UUID(str(result.scalar_one()))


async def _insert_facts(
    connection: Any,
    *,
    proposal_id: UUID,
    workspace_id: UUID,
    entity_id: UUID,
    entity_key: str,
    entity_type: str,
    plan: Any,
    values: dict[str, Any],
) -> None:
    for field_path in plan.facts_by_entity[entity_key]:
        reference = plan.source_by_field[field_path]
        field_name = field_path.rsplit(".", 1)[1]
        await connection.execute(
            INSERT_IMPORTED_FACT_QUERY,
            {
                "block_id": reference.block_id,
                "data_path": reference.data_path,
                "entity_id": entity_id,
                "entity_type": entity_type,
                "field_path": field_path,
                "parsed_document_id": reference.parsed_document_id,
                "proposal_id": proposal_id,
                "quote": reference.quote,
                "source_file_id": reference.source_file_id,
                "source_locator": json.dumps(reference.locator, ensure_ascii=False),
                "value_json": json.dumps(values[field_name], ensure_ascii=False),
                "workspace_id": workspace_id,
            },
        )
