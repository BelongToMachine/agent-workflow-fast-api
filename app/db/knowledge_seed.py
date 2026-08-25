import argparse
import asyncio
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text

from app.core.config import get_settings
from app.db.knowledge_provenance import (
    KnowledgeSourceImport,
    attach_source_coordinates,
    attach_source_provenance,
    ensure_knowledge_source,
)
from app.db.migration_status import MIGRATION_STATUS_QUERY, build_migration_statuses
from app.db.migration_utils import migration_apply_error
from app.db.session import get_db_connection


@dataclass(frozen=True)
class SeedTableSpec:
    table_name: str
    allowed_columns: frozenset[str]
    required_columns: frozenset[str]
    conflict_columns: tuple[str, ...]
    has_source_id: bool


@dataclass(frozen=True)
class SeedCounts:
    content_records: int = 0
    real_product_research: int = 0
    product_documents: int = 0
    product_operations: int = 0
    product_prices: int = 0

    def add(self, section: str, count: int) -> "SeedCounts":
        values = {
            "contentRecords": self.content_records,
            "realProductResearch": self.real_product_research,
            "productDocuments": self.product_documents,
            "productOperations": self.product_operations,
            "productPrices": self.product_prices,
        }
        values[section] += count
        return SeedCounts(**{
            "content_records": values["contentRecords"],
            "real_product_research": values["realProductResearch"],
            "product_documents": values["productDocuments"],
            "product_operations": values["productOperations"],
            "product_prices": values["productPrices"],
        })


def _columns(*values: str) -> frozenset[str]:
    return frozenset(values)


TABLE_SPECS: dict[str, SeedTableSpec] = {
    "contentRecords": SeedTableSpec(
        table_name="ContentRecord",
        allowed_columns=_columns(
            "accountDirection", "accountName", "accountType", "aiMaterials",
            "attachment", "copyText", "copyWriter", "createdAt", "id", "language",
            "notes", "photographer", "plannedAt", "platform", "product", "rawData",
            "recordType", "referenceVideo", "reviewStatus", "revisedCopy", "scriptDocument",
            "searchText", "shootConfirmed", "shootingScene", "sourceId", "sourceRow",
            "sourceSheet", "submitter", "tags", "targetTopic", "title", "usageStatus",
            "videoType",
        ),
        required_columns=_columns(
            "rawData", "recordType", "searchText", "sourceRow", "sourceSheet"
        ),
        conflict_columns=("sourceId", "sourceSheet", "sourceRow"),
        has_source_id=True,
    ),
    "realProductResearch": SeedTableSpec(
        table_name="RealProductResearch",
        allowed_columns=_columns(
            "brand", "category", "contactPerson", "costPrice", "customsFee", "id",
            "listedPrice", "logistics", "notes", "orderTotalPrice", "procurementConditions",
            "productFeatures", "productHighlights", "productImage", "productIntro",
            "productName", "promotionStatus", "proposer", "qualifications", "rawData",
            "relatedDocuments", "sellingPrice", "shippingTime", "singleProductCost",
            "sourceId", "sourceRow", "sourceSheet", "supplierContact", "targetSalesChannels",
        ),
        required_columns=_columns("id", "productName", "rawData", "sourceRow", "sourceSheet"),
        conflict_columns=("sourceId", "sourceSheet", "sourceRow"),
        has_source_id=True,
    ),
    "productDocuments": SeedTableSpec(
        table_name="ProductDocument",
        allowed_columns=_columns(
            "createdAt", "displayName", "documentType", "fileReference", "id", "rawText",
            "researchId", "sourceId", "sourceRow", "sourceSheet",
        ),
        required_columns=_columns(
            "documentType", "fileReference", "rawText", "researchId", "sourceRow", "sourceSheet"
        ),
        conflict_columns=("researchId", "documentType", "fileReference"),
        has_source_id=True,
    ),
    "productOperations": SeedTableSpec(
        table_name="ProductOperation",
        allowed_columns=_columns(
            "id", "researchId", "sourceRow", "sourceSheet", "promotionStatus",
            "operationStatus", "targetChannels", "proposer", "logisticsTerm", "qualifications",
            "nextAction", "notes", "rawData", "updatedAt",
        ),
        required_columns=_columns("researchId", "rawData", "sourceRow", "sourceSheet"),
        conflict_columns=("researchId",),
        has_source_id=False,
    ),
    "productPrices": SeedTableSpec(
        table_name="ProductPrice",
        allowed_columns=_columns(
            "id", "researchId", "sourceRow", "sourceSheet", "variant", "priceMin", "priceMax",
            "currency", "priceType", "rawText",
        ),
        required_columns=_columns(
            "currency", "priceMin", "priceType", "rawText", "researchId", "sourceRow",
            "sourceSheet", "variant",
        ),
        conflict_columns=("researchId", "variant", "priceMin", "currency", "priceType"),
        has_source_id=False,
    ),
}


SEED_MIGRATION_NAMES = frozenset({
    "0006_knowledge_source_provenance",
    "0007_knowledge_source_relationships",
    "0008_knowledge_source_import_key",
})


def _json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def normalize_seed_row(
    section: str,
    record: Mapping[str, Any],
    *,
    source_id: UUID,
) -> dict[str, Any]:
    """Validate a source row and attach authoritative provenance fields."""

    try:
        spec = TABLE_SPECS[section]
    except KeyError as error:
        raise ValueError(f"Unsupported seed section: {section}") from error

    row = dict(record)
    source_sheet = row.get("sourceSheet")
    source_row = row.get("sourceRow")
    if not isinstance(source_sheet, str) or not isinstance(source_row, int):
        raise ValueError(
            f"{section} rows must contain sourceSheet (string) and sourceRow (integer)."
        )

    row.pop("sourceId", None)
    row = (
        attach_source_provenance(
            row,
            source_id=source_id,
            source_sheet=source_sheet,
            source_row=source_row,
        )
        if spec.has_source_id
        else attach_source_coordinates(
            row,
            source_sheet=source_sheet,
            source_row=source_row,
        )
    )

    unknown_columns = set(row) - spec.allowed_columns
    if unknown_columns:
        unknown = ", ".join(sorted(unknown_columns))
        raise ValueError(f"Unsupported columns for {section}: {unknown}")

    missing_columns = [
        column for column in sorted(spec.required_columns)
        if column not in row or row[column] is None
    ]
    if missing_columns:
        raise ValueError(
            f"Missing required columns for {section}: {', '.join(missing_columns)}"
        )

    return {
        column: _json_value(value)
        for column, value in row.items()
    }


def build_upsert_query(section: str, columns: Iterable[str]) -> object:
    """Build SQL only from a checked-in table/column allowlist."""

    spec = TABLE_SPECS[section]
    ordered_columns = tuple(sorted(columns))
    if not ordered_columns or not set(ordered_columns) <= spec.allowed_columns:
        raise ValueError(f"Invalid columns for {section}.")

    def quote(column: str) -> str:
        return f'"{column}"'

    bind_names = {column: f"value_{index}" for index, column in enumerate(ordered_columns)}
    insert_columns = ", ".join(quote(column) for column in ordered_columns)
    insert_values = ", ".join(f":{bind_names[column]}" for column in ordered_columns)
    conflict_columns = ", ".join(quote(column) for column in spec.conflict_columns)
    update_columns = [
        column for column in ordered_columns
        if column not in spec.conflict_columns and column != "id"
    ]
    if update_columns:
        update = ", ".join(
            f'{quote(column)} = EXCLUDED.{quote(column)}'
            for column in update_columns
        )
        conflict_action = f"DO UPDATE SET {update}"
    else:
        conflict_action = "DO NOTHING"

    return text(
        f'INSERT INTO "{spec.table_name}" ({insert_columns}) '
        f"VALUES ({insert_values}) "
        f"ON CONFLICT ({conflict_columns}) {conflict_action}"
    )


async def _upsert_rows(
    connection,
    section: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    source_id: UUID,
) -> int:
    count = 0
    for record in rows:
        normalized = normalize_seed_row(section, record, source_id=source_id)
        query = build_upsert_query(section, normalized.keys())
        params = {
            f"value_{index}": normalized[column]
            for index, column in enumerate(sorted(normalized))
        }
        await connection.execute(query, params)
        count += 1
    return count


async def _assert_research_links(
    connection,
    source_id: UUID,
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    dependent_ids = {
        str(record["researchId"])
        for section in ("productDocuments", "productOperations", "productPrices")
        for record in sections.get(section, [])
        if record.get("researchId") is not None
    }
    if not dependent_ids:
        return

    result = await connection.execute(
        text(
            """
            SELECT "id"
            FROM "RealProductResearch"
            WHERE "id" IN :research_ids
              AND "sourceId" = :source_id
            """
        ).bindparams(bindparam("research_ids", expanding=True)),
        {"research_ids": list(dependent_ids), "source_id": source_id},
    )
    found_ids = {str(row[0]) for row in result}
    missing_ids = sorted(dependent_ids - found_ids)
    if missing_ids:
        raise ValueError(
            "Dependent product rows must reference research rows from the same source: "
            + ", ".join(missing_ids)
        )


async def seed_sections(
    connection,
    source: KnowledgeSourceImport,
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[UUID, SeedCounts]:
    """Seed selected sections in the caller's transaction."""

    source_id = await ensure_knowledge_source(connection, source)
    counts = SeedCounts()
    ordered_sections = (
        "realProductResearch",
        "contentRecords",
        "productDocuments",
        "productOperations",
        "productPrices",
    )
    if sections.get("realProductResearch"):
        counts = counts.add(
            "realProductResearch",
            await _upsert_rows(
                connection,
                "realProductResearch",
                sections["realProductResearch"],
                source_id=source_id,
            ),
        )
    await _assert_research_links(connection, source_id, sections)
    for section in ordered_sections[1:]:
        rows = sections.get(section, [])
        if rows:
            counts = counts.add(
                section,
                await _upsert_rows(connection, section, rows, source_id=source_id),
            )
    return source_id, counts


def load_seed_payload(path: Path) -> tuple[KnowledgeSourceImport, dict[str, list[dict[str, Any]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("source"), dict):
        raise ValueError("Seed input must contain a top-level source object.")

    source_payload = payload["source"]
    required_source_fields = ("displayName", "sourceType", "workspaceId", "fileHash")
    missing_source_fields = [
        field for field in required_source_fields
        if not source_payload.get(field)
    ]
    if missing_source_fields:
        raise ValueError(
            "Missing source fields: " + ", ".join(missing_source_fields)
        )

    source = KnowledgeSourceImport(
        workspace_id=UUID(str(source_payload["workspaceId"])),
        display_name=str(source_payload["displayName"]),
        source_type=str(source_payload["sourceType"]),
        file_hash=str(source_payload["fileHash"]),
        storage_provider=source_payload.get("storageProvider"),
        storage_key=source_payload.get("storageKey"),
        status=str(source_payload.get("status", "ready")),
        version=int(source_payload.get("version", 1)),
    )

    sections: dict[str, list[dict[str, Any]]] = {}
    for section in TABLE_SPECS:
        value = payload.get(section, [])
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValueError(f"Seed section {section} must be an array of objects.")
        sections[section] = value
    return source, sections


async def _assert_migrations_ready(connection) -> None:
    result = await connection.execute(MIGRATION_STATUS_QUERY)
    statuses = build_migration_statuses(dict(result.mappings().one()))
    pending = sorted(
        status.name for status in statuses
        if status.name in SEED_MIGRATION_NAMES and not status.applied
    )
    if pending:
        raise RuntimeError(
            "Knowledge provenance migrations are pending: " + ", ".join(pending)
        )


def _parser(fixed_sections: Sequence[str] | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Idempotently seed source-provenance data.")
    parser.add_argument("--input", required=True, type=Path, help="JSON seed payload path")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow writes to a reviewed non-local development database.",
    )
    parser.set_defaults(fixed_sections=tuple(fixed_sections or ()))
    return parser


async def run_cli(fixed_sections: Sequence[str] | None = None) -> int:
    args = _parser(fixed_sections).parse_args()
    settings = get_settings()
    if error := migration_apply_error(settings, allow_remote=args.allow_remote):
        print(error)
        return 1

    try:
        source, sections = load_seed_payload(args.input)
        if args.fixed_sections:
            sections = {
                section: sections[section]
                for section in args.fixed_sections
            }
        async with get_db_connection() as connection:
            async with connection.begin():
                await _assert_migrations_ready(connection)
                source_id, counts = await seed_sections(connection, source, sections)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Seed failed: {error}")
        return 1

    print(f"Source: {source_id}")
    print(counts)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run_cli()))


if __name__ == "__main__":
    main()
