# Knowledge Source Import Contract

The FastAPI seed scripts accept one JSON payload per source file. The payload
is designed to be generated from Excel/CSV/JSON by a separate adapter; the
database writer does not guess business-column mappings.

## Commands

```bash
uv run python -m scripts.seed_knowledge_data --input ./source.json
uv run python -m scripts.seed_content_data --input ./source.json
uv run python -m scripts.seed_real_product_data --input ./source.json
uv run python -m scripts.seed_real_operations_data --input ./source.json
```

All commands are local-only by default. A reviewed development database needs
an explicit `--allow-remote` flag.

## Payload

```json
{
  "source": {
    "displayName": "supplier-catalog.xlsx",
    "sourceType": "xlsx",
    "workspaceId": "00000000-0000-0000-0000-000000000001",
    "fileHash": "sha256-hex-value",
    "status": "ready",
    "version": 1
  },
  "contentRecords": [
    {
      "recordType": "copy",
      "rawData": {"product": "chair"},
      "searchText": "chair product copy",
      "sourceSheet": "Content",
      "sourceRow": 18
    }
  ],
  "realProductResearch": [
    {
      "id": "10000000-0000-0000-0000-000000000001",
      "productName": "Chair",
      "rawData": {"supplier": "Example"},
      "sourceSheet": "Products",
      "sourceRow": 2
    }
  ],
  "productDocuments": [],
  "productOperations": [],
  "productPrices": []
}
```

## Rules

- `source.workspaceId`, `source.fileHash`, `source.displayName`, and
  `source.sourceType` are required.
- `fileHash` should be the SHA-256 hash of the original bytes. The same hash is
  idempotent within one workspace.
- Every row must contain `sourceSheet` and a positive `sourceRow`.
- Any input `sourceId` is ignored and replaced by the source registered by the
  importer.
- Unknown database columns are rejected.
- Product documents, operations, and prices must reference a
  `RealProductResearch` row from the same source.
- Re-running the same payload updates the existing source-scoped row instead
  of inserting a duplicate.
