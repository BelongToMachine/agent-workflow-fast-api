# Knowledge Source Provenance Implementation Plan

## Scope

This plan covers the database schema and local application code needed to trace
knowledge-base records back to their source files.

The current phase does **not** include VPS storage, file upload, MinIO, OSS,
download URLs, or file preview.

## Current status

- [ ] Step 1: Confirm the data model and source relationship
- [ ] Step 2: Add the `KnowledgeSource` schema and migration
- [ ] Step 3: Add `sourceId` relationships and indexes
- [ ] Step 4: Update import/seed scripts
- [ ] Step 5: Add source-scoped database queries
- [ ] Step 6: Update AI tools and source-aware prompts
- [ ] Step 7: Return and render source citations
- [ ] Step 8: Backfill legacy data and verify the full flow

We will stop after each step for review. A step is only marked complete after
explicit approval.

## Proposed data model

### `KnowledgeSource`

Create one row for each imported knowledge source file:

| Field | Purpose |
| --- | --- |
| `id` | Internal source identifier |
| `displayName` | User-facing file name, such as `供应商报价.xlsx` |
| `sourceType` | `excel`, `pdf`, `word`, or another source type |
| `storageProvider` | Reserved for `local`, `vps`, `oss`, etc. |
| `storageKey` | Reserved storage location; nullable for now |
| `fileHash` | Detect duplicate files or new versions |
| `version` | Source version number |
| `status` | `pending`, `ready`, or `failed` |
| `createdAt` | Creation timestamp |
| `updatedAt` | Last update timestamp |

### Existing table relationships

Add `sourceId` as a foreign key to:

- `ContentRecord`
- `RealProductResearch`
- `ProductDocument`

Keep the existing fields:

- `sourceSheet`: worksheet or section inside the source file
- `sourceRow`: row number inside the source file

The final provenance chain will be:

```text
sourceId → source file
sourceSheet → worksheet
sourceRow → row
```

`ProductOperation` and `ProductPrice` already reference
`RealProductResearch` through `researchId`, so they can inherit the source
relationship without duplicating `sourceId` in the first iteration.

## Step-by-step work

### Step 1 — Confirm the data model

Review and approve:

- The `KnowledgeSource` table name and fields.
- Whether `storageProvider` and `storageKey` should be nullable placeholders.
- Whether `ProductDocument` represents a separate source file or only a
  reference attached to a product row.
- Whether the knowledge base is shared enterprise data or needs a future
  `workspaceId`/tenant relationship now.

Acceptance criteria:

- The source-file relationship is clear.
- Existing `sourceSheet` and `sourceRow` remain useful.
- No VPS-related implementation is required yet.

### Step 2 — Add the source schema and migration

Files:

- `lib/db/schema.ts`
- Generated file under `lib/db/migrations/`

Tasks:

- Add `KnowledgeSource`.
- Add nullable `sourceId` columns first for safe migration.
- Add foreign keys and indexes.
- Keep `storageKey` nullable.

Validation:

```bash
pnpm db:generate
pnpm db:check
```

### Step 3 — Add source relationships and indexes

Tasks:

- Add `sourceId` to `ContentRecord`.
- Add `sourceId` to `RealProductResearch`.
- Add `sourceId` to `ProductDocument` if confirmed in Step 1.
- Replace the current uniqueness scope of
  `(sourceSheet, sourceRow)` with `(sourceId, sourceSheet, sourceRow)`.
- Add indexes for `sourceId`.

This prevents two different files with the same worksheet and row number from
being treated as duplicates.

### Step 4 — Update import and seed scripts

Files:

- `scripts/seed-content-data.ts`
- `scripts/seed-real-product-data.ts`
- `scripts/seed-real-operations-data.ts`

Tasks:

- Create or find a `KnowledgeSource` before importing rows.
- Pass its `sourceId` into every imported root record.
- Keep writing `sourceSheet` and `sourceRow`.
- Propagate the relationship to product documents where applicable.
- Make repeated imports deterministic using `fileHash` or a stable import key.

Legacy data that cannot be matched to a known file will receive a clearly
marked legacy source rather than an invented file name.

### Step 5 — Add source-scoped database queries

Files:

- `lib/db/content-queries.ts`
- `lib/db/trade-queries.ts`
- Any product-document query added later

Tasks:

- Resolve user-facing file names to `sourceId` values.
- Add optional source filters to search inputs.
- Apply `sourceId` filtering in SQL.
- Support multiple source files.
- Do not fall back to the full knowledge base when an explicit source filter
  returns no result.

### Step 6 — Update AI tools and prompts

Files:

- `lib/ai/tools/search-content.ts`
- Product search tool definition
- `lib/ai/prompts.ts`
- `lib/types.ts`

Tasks:

- Add optional source-file filters to tool schemas.
- Explain source-scoped search in tool descriptions.
- Require the model to use only returned records as factual evidence.
- Keep the actual restriction in the database layer; prompts are not a
  security boundary.

### Step 7 — Return and render citations

Tasks:

- Include `sourceId`, file name, sheet, and row in query results.
- Add a consistent citation shape for future PDF page or document section
  support.
- Update the tool result types.
- Render source information in the chat UI.

Example citation:

```json
{
  "sourceId": "source_123",
  "fileName": "供应商报价.xlsx",
  "sheet": "手机配件",
  "row": 18
}
```

### Step 8 — Backfill and verify

Tasks:

- Create source rows for existing imported datasets.
- Backfill `sourceId` values.
- Make the columns non-null only after successful backfill.
- Run migrations and seed scripts against a test database.
- Test unrestricted search.
- Test one-source search.
- Test multi-source search.
- Test missing-source search.
- Confirm two files can contain the same sheet and row number.

Validation commands:

```bash
pnpm db:migrate
pnpm db:seed:content
pnpm db:seed:real
pnpm db:seed:real-operations
pnpm check
```

## Explicitly out of scope for this phase

- VPS directory creation.
- File upload APIs.
- MinIO or OSS integration.
- Signed download URLs.
- File preview.
- Vector embeddings and semantic search.

Those features will use the reserved `storageProvider` and `storageKey`
fields later.
