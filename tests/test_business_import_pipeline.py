import asyncio
import importlib.util
from pathlib import Path
from uuid import UUID

import pytest


def test_business_import_pipeline_is_available() -> None:
    """A parsed document must have a dedicated, review-only import pipeline."""
    assert importlib.util.find_spec("app.services.business_imports") is not None


def test_business_import_review_is_not_gated_by_a_runtime_flag() -> None:
    from app.api.routes import business_imports
    from app.core.config import Settings

    assert not hasattr(Settings(), "business_imports_enabled")
    assert "business_import:disabled" not in Path(business_imports.__file__).read_text(
        encoding="utf-8"
    )
    assert "BUSINESS_IMPORTS_ENABLED" not in (
        Path(__file__).resolve().parents[1] / ".env.example"
    ).read_text(encoding="utf-8")


def _completed_agent_response() -> str:
    return """<review_report>
找到 1 个产品候选和 1 条报价。产品名称与报价均来自同一份报价表，建议提交人工审核。
</review_report>
<proposal_json>
{
  "summary": "找到 1 个产品候选和 1 条报价，建议提交人工审核。",
  "candidateExplanations": [{
    "candidateRef": "candidate-1",
    "status": "ready_for_review",
    "explanation": "产品名称和 500ml 批发报价均有明确原文依据。",
    "basis": [{
      "claim": "产品名称为 304 不锈钢保温杯",
      "fieldPath": "product.productName",
      "evidenceRefs": ["evidence-1"]
    }],
    "uncertainties": []
  }],
  "unclassifiedFindings": [],
  "candidates": [{
    "candidateRef": "candidate-1",
    "product": {"productName": "304 不锈钢保温杯", "brand": null},
    "operation": null,
    "prices": [{
      "variant": "500ml",
      "priceMin": 8.5,
      "priceMax": null,
      "currency": "CNY",
      "priceType": "批发价",
      "rawText": "500ml 批发价 ¥8.5"
    }],
    "documents": [],
    "evidence": [{
      "evidenceId": "evidence-1",
      "fieldPath": "product.productName",
      "blockId": "block-product",
      "dataPath": "$.data.产品名称",
      "quote": "304 不锈钢保温杯"
    }, {
      "evidenceId": "evidence-2",
      "fieldPath": "prices[0]",
      "blockId": "block-price",
      "dataPath": "$.data.报价",
      "quote": "500ml 批发价 ¥8.5"
    }],
    "unresolved": []
  }]
}
</proposal_json>"""


def _parsed_blocks() -> list[dict[str, object]]:
    return [
        {
            "blockId": "block-product",
            "text": "产品名称：304 不锈钢保温杯",
            "data": {"产品名称": "304 不锈钢保温杯"},
            "locator": {"sheet": "报价表", "row": 12},
        },
        {
            "blockId": "block-price",
            "text": "500ml 批发价 ¥8.5",
            "data": {"报价": "500ml 批发价 ¥8.5"},
            "locator": {"sheet": "报价表", "row": 12},
        },
    ]


def test_product_profile_compiles_a_safe_agent_contract() -> None:
    from app.business_schema.compiler import compile_agent_contract
    from app.business_schema.registry import load_profile

    contract = compile_agent_contract(load_profile("product_and_price"))

    assert contract.profile == "product_and_price"
    assert "产品名称" in contract.instructions
    assert "RealProductResearch" not in contract.instructions
    assert "ProductPrice" not in contract.instructions
    assert contract.schema_version == "1"


def test_completed_agent_output_is_evidence_checked_and_enriched() -> None:
    from app.services.business_imports import parse_and_validate_agent_output

    result = parse_and_validate_agent_output(
        _completed_agent_response(),
        blocks=_parsed_blocks(),
        profile_name="product_and_price",
        source_file_id=UUID("00000000-0000-0000-0000-000000000010"),
        parsed_document_id=UUID("00000000-0000-0000-0000-000000000011"),
        file_hash="a" * 64,
    )

    assert result.review_report.summary == "找到 1 个产品候选和 1 条报价，建议提交人工审核。"
    assert result.proposals[0].patch["product"]["productName"] == "304 不锈钢保温杯"
    assert result.proposals[0].source_references[0].locator == {
        "sheet": "报价表",
        "row": 12,
    }
    assert result.proposals[0].review_explanation["status"] == "ready_for_review"
    assert getattr(result.review_report, "diagnostics", None) == {
        "outcome": "accepted",
        "stage": "validation_complete",
        "code": "business_import.validation_passed",
        "details": {"candidateCount": 1, "sourceEvidenceCount": 2},
        "checks": [
            {"name": "tagged_response", "status": "passed"},
            {"name": "proposal_contract", "status": "passed"},
            {"name": "candidate_fields", "status": "passed"},
            {"name": "source_evidence", "status": "passed"},
        ],
    }


def test_missing_required_field_has_a_machine_readable_validation_diagnostic() -> None:
    from app.services.business_imports import (
        BusinessImportValidationError,
        parse_and_validate_agent_output,
    )

    invalid_response = _completed_agent_response().replace(
        '"productName": "304 不锈钢保温杯"',
        '"productName": null',
    )

    with pytest.raises(BusinessImportValidationError) as raised:
        parse_and_validate_agent_output(
            invalid_response,
            blocks=_parsed_blocks(),
            profile_name="product_and_price",
            source_file_id=UUID("00000000-0000-0000-0000-000000000010"),
            parsed_document_id=UUID("00000000-0000-0000-0000-000000000011"),
            file_hash="a" * 64,
        )

    assert getattr(raised.value, "diagnostics", None) == {
        "stage": "candidate_validation",
        "code": "candidate.required_field_missing",
        "details": {
            "candidateRef": "candidate-1",
            "fieldPath": "product.productName",
        },
    }


def test_job_response_exposes_raw_provider_output_to_authorized_reviewers() -> None:
    from app.api.routes.business_imports import _job_response

    job = _job_response(
        {
            "created_at": "2026-09-18T00:00:00Z",
            "error_message": "The candidate is missing required field product.productName.",
            "finished_at": "2026-09-18T00:00:02Z",
            "job_id": "00000000-0000-0000-0000-000000000020",
            "model": "test-model",
            "parsed_document_id": "00000000-0000-0000-0000-000000000011",
            "profile": "product_and_price",
            "prompt_version": "business-import/v1",
            "raw_provider_output": "<review_report>…</review_report>",
            "review_report": {
                "diagnostics": {"code": "candidate.required_field_missing"}
            },
            "schema_version": "1",
            "source_file_id": "00000000-0000-0000-0000-000000000010",
            "status": "failed",
            "updated_at": "2026-09-18T00:00:02Z",
        },
        [],
    )

    assert getattr(job, "raw_provider_output", None) == "<review_report>…</review_report>"


def test_agent_output_rejects_evidence_that_does_not_match_the_parsed_block() -> None:
    from app.services.business_imports import (
        BusinessImportValidationError,
        parse_and_validate_agent_output,
    )

    invalid_response = _completed_agent_response().replace(
        '"quote": "304 不锈钢保温杯"',
        '"quote": "凭空编造的产品"',
    )

    with pytest.raises(BusinessImportValidationError, match="quote"):
        parse_and_validate_agent_output(
            invalid_response,
            blocks=_parsed_blocks(),
            profile_name="product_and_price",
            source_file_id=UUID("00000000-0000-0000-0000-000000000010"),
            parsed_document_id=UUID("00000000-0000-0000-0000-000000000011"),
            file_hash="a" * 64,
        )


class _ProviderStreamResponse:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"<review_report>找到 1 个候选"}}]}'
        yield 'data: {"choices":[{"delta":{"content":"，建议审核。</review_report>"}}]}'
        yield "data: [DONE]"


class _ProviderStreamClient:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def stream(self, _method: str, _url: str, **kwargs):
        self.request = kwargs
        return _ProviderStreamResponse()


def test_provider_stream_exposes_only_review_text_before_structured_proposal() -> None:
    from app.services.business_imports import stream_provider_completion

    client = _ProviderStreamClient()

    async def collect() -> list[str]:
        return [
            delta
            async for delta in stream_provider_completion(
                api_key="test-key",
                base_url="https://provider.example/v1",
                client=client,
                messages=[{"role": "user", "content": "untrusted source"}],
                model="test-model",
                timeout_seconds=12,
            )
        ]

    assert asyncio.run(collect()) == ["找到 1 个候选", "，建议审核。"]
    assert client.request is not None
    assert client.request["json"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "untrusted source"}],
        "stream": True,
    }


def test_business_import_migration_is_in_the_knowledge_migration_runner() -> None:
    from app.db.migrate_knowledge import MIGRATION_NAMES, MIGRATION_PATHS

    assert "0016_business_import_review" in MIGRATION_NAMES
    assert any(path.name == "0016_business_import_review.sql" for path in MIGRATION_PATHS)


def test_product_write_plan_preserves_field_level_provenance() -> None:
    from app.services.business_imports import (
        build_product_write_plan,
        parse_and_validate_agent_output,
    )

    analysis = parse_and_validate_agent_output(
        _completed_agent_response(),
        blocks=_parsed_blocks(),
        profile_name="product_and_price",
        source_file_id=UUID("00000000-0000-0000-0000-000000000010"),
        parsed_document_id=UUID("00000000-0000-0000-0000-000000000011"),
        file_hash="a" * 64,
    )

    plan = build_product_write_plan(analysis.proposals[0])

    assert plan.product.values == {"productName": "304 不锈钢保温杯", "brand": None}
    assert plan.product.source_locator == {"sheet": "报价表", "row": 12}
    assert plan.prices[0].values["priceMin"] == 8.5
    assert plan.facts_by_entity["product"] == ["product.productName"]
    assert set(plan.facts_by_entity["prices[0]"]) == {
        "prices[0].currency",
        "prices[0].priceMin",
        "prices[0].priceType",
        "prices[0].rawText",
        "prices[0].variant",
    }
