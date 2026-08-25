from pathlib import Path
from uuid import UUID

import pytest

from app.db.knowledge_provenance import (
    KnowledgeSourceImport,
    attach_source_provenance,
    sha256_file_content,
)
from app.db.knowledge_seed import (
    build_upsert_query,
    load_seed_payload,
    normalize_seed_row,
)


def test_sha256_file_content_is_stable() -> None:
    assert sha256_file_content(b"asianode") == (
        "bc4c3ff891b8a2acfe76b47c92c9417f3d5ed4e746bf794a9f188f339bb07acf"
    )


def test_source_import_requires_meaningful_metadata() -> None:
    with pytest.raises(ValueError, match="display name"):
        KnowledgeSourceImport(
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            display_name=" ",
            source_type="xlsx",
        )

    with pytest.raises(ValueError, match="version"):
        KnowledgeSourceImport(
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            display_name="catalog.xlsx",
            source_type="xlsx",
            version=0,
        )


def test_attach_source_provenance_overwrites_untrusted_row_coordinates() -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000010")

    result = attach_source_provenance(
        {"productName": "chair", "sourceId": "untrusted"},
        source_id=source_id,
        source_sheet=" Products ",
        source_row=18,
    )

    assert result == {
        "productName": "chair",
        "sourceId": source_id,
        "sourceSheet": "Products",
        "sourceRow": 18,
    }


def test_normalize_seed_row_attaches_source_and_rejects_untrusted_columns() -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000010")

    result = normalize_seed_row(
        "contentRecords",
        {
            "recordType": "copy",
            "rawData": {"product": "chair"},
            "searchText": "chair",
            "sourceId": "untrusted",
            "sourceSheet": "Content",
            "sourceRow": 18,
        },
        source_id=source_id,
    )

    assert result["sourceId"] == source_id
    assert result["rawData"] == '{"product":"chair"}'

    with pytest.raises(ValueError, match="Unsupported columns"):
        normalize_seed_row(
            "contentRecords",
            {
                "recordType": "copy",
                "rawData": {},
                "searchText": "chair",
                "sourceSheet": "Content",
                "sourceRow": 18,
                "notAColumn": True,
            },
            source_id=source_id,
        )


def test_build_upsert_query_uses_source_scoped_conflict_key() -> None:
    sql = str(
        build_upsert_query(
            "contentRecords",
            {"recordType", "rawData", "searchText", "sourceId", "sourceSheet", "sourceRow"},
        )
    )

    assert 'INSERT INTO "ContentRecord"' in sql
    assert 'ON CONFLICT ("sourceId", "sourceSheet", "sourceRow")' in sql


def test_load_seed_payload_requires_source_metadata(tmp_path: Path) -> None:
    payload_path = tmp_path / "source.json"
    payload_path.write_text(
        """{
          "source": {
            "displayName": "catalog.xlsx",
            "sourceType": "xlsx",
            "workspaceId": "00000000-0000-0000-0000-000000000001",
            "fileHash": "abc123"
          },
          "contentRecords": [],
          "realProductResearch": [],
          "productDocuments": [],
          "productOperations": [],
          "productPrices": []
        }""",
        encoding="utf-8",
    )

    source, sections = load_seed_payload(payload_path)

    assert source.display_name == "catalog.xlsx"
    assert source.workspace_id == UUID("00000000-0000-0000-0000-000000000001")
    assert sections["contentRecords"] == []


def test_load_seed_payload_rejects_unknown_section_shape(tmp_path: Path) -> None:
    payload_path = tmp_path / "source.json"
    payload_path.write_text(
        '{"source": {"displayName": "catalog", "sourceType": "json", '
        '"workspaceId": "00000000-0000-0000-0000-000000000001", '
        '"fileHash": "abc123"}, "contentRecords": {}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be an array of objects"):
        load_seed_payload(payload_path)


@pytest.mark.parametrize(
    ("source_sheet", "source_row", "message"),
    [(" ", 1, "sheet"), ("Products", 0, "row")],
)
def test_attach_source_provenance_rejects_invalid_coordinates(
    source_sheet: str,
    source_row: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        attach_source_provenance(
            {},
            source_id=UUID("00000000-0000-0000-0000-000000000010"),
            source_sheet=source_sheet,
            source_row=source_row,
        )
