# Knowledge Source Provenance Implementation Plan

## Scope

This plan covers the database schema and local application code needed to trace
knowledge-base records back to their source files.

The current phase does **not** include VPS storage, file upload, MinIO, OSS,
download URLs, or file preview.

## Current status

- [x] Step 1: Confirm the data model and source relationship
- [x] Step 2: Add or reconcile the `KnowledgeSource` schema and migration
- [x] Step 3: Add `sourceId` relationships and indexes
- [x] Step 4: Update import/seed scripts
- [x] Step 5: Add source-scoped database queries
- [x] Step 6: Update AI tools and source-aware prompts
- [x] Step 7: Return and render source citations
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
| `workspaceId` | Current workspace/tenant boundary for the source |
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

#### Step 1 decision record — 2026-08-25

Step 1 is complete. The following decisions are based on the current FastAPI
schema, query code, and database contents:

1. **Table and ownership**

   Keep `KnowledgeSource` as the source-file provenance table. The current
   database already contains this table and two ready legacy source rows. The
   FastAPI project is the migration and database authority; the old frontend
   Drizzle schema is compatibility/reference code and must not be used to run
   production migrations.

2. **Storage placeholders**

   Keep `storageProvider` and `storageKey` nullable. The current database has no
   populated `storageKey` values and no file-storage implementation is part of
   this phase. Keep `fileHash` nullable as well because the existing legacy
   rows do not have hashes.

3. **Workspace boundary**

   Keep `workspaceId` required on `KnowledgeSource`. The current deployment
   has one workspace, but the source-to-workspace relationship is already the
   correct isolation boundary for a future multi-workspace rollout. This step
   does not add workspace switching or split the current workspace.

4. **`ProductDocument` semantics**

   `ProductDocument` is a product-attached document record, not automatically
   a new source file. `researchId` expresses the business/product relationship;
   `sourceId`, `sourceSheet`, and `sourceRow` express provenance. A document
   imported from a separate file may point to a different `KnowledgeSource`;
   a derived document reuses the source relationship of its product research
   record. The first iteration will not create a separate source row for every
   derived document.

5. **Row-level provenance**

   Keep `sourceSheet` and `sourceRow`. The accepted uniqueness scope is
   `(sourceId, sourceSheet, sourceRow)`, so identical sheet/row coordinates in
   two files remain distinct. `ProductOperation` and `ProductPrice` continue to
   inherit provenance through `researchId`.

6. **Current database baseline**

   The existing database contains one workspace, two `KnowledgeSource` rows,
   47 `RealProductResearch` rows, and 46 `ContentRecord` rows. All existing
   research and content rows currently have valid source references. The
   knowledge-base migrations `0001`–`0004` are still pending, so this step did
   not run them or change any database data.

The next step must reconcile this confirmed model with the FastAPI migration
chain. It should add or adjust backend SQL migrations under `migrations/` and
the related migration tooling, rather than generating a frontend migration.

### Step 2 — Add or reconcile the source schema and migration

Files:

- `migrations/*.sql`
- `app/db/migrate_knowledge*.py`
- `app/db/migration_status.py`

Tasks:

- Reconcile the existing `KnowledgeSource` and knowledge-base migration chain.
- Add nullable `sourceId` columns first for safe migration.
- Add foreign keys and indexes.
- Keep `storageKey` nullable.

Validation:

```bash
make migration-status
make knowledge-integrity
```

#### Step 2 implementation record — 2026-08-25

Step 2 is complete at the repository level:

- Added `migrations/0006_knowledge_source_provenance.sql` to reconcile the
  existing legacy `KnowledgeSource` table without renaming or recreating it.
- The migration is idempotent and preserves nullable `storageProvider`,
  `storageKey`, and `fileHash` values.
- Required provenance fields and the `workspaceId` foreign-key relationship
  are validated before the migration succeeds. Missing workspace assignments
  fail explicitly instead of receiving an unsafe default workspace.
- Added the workspace/status index needed for source-scoped lookups.
- Registered the migration in `app/db/migrate_knowledge.py` and added schema
  capability checks to `app/db/migration_status.py`.
- No `sourceId` columns were added yet; those belong to Step 3.

The configured database is a remote development Supabase target. The migration
has not been applied remotely in this batch because the repository requires an
explicit `--allow-remote` opt-in for that operation. Until it is applied,
`make migration-status` will correctly report `0006_knowledge_source_provenance`
as pending.

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

#### Step 3 implementation record — 2026-08-25

Step 3 is complete at the repository level:

- Added `migrations/0007_knowledge_source_relationships.sql`.
- Added nullable `sourceId` columns and `KnowledgeSource` foreign keys for
  `ContentRecord`, `RealProductResearch`, and `ProductDocument`.
- Added source lookup indexes for all three tables.
- Replaced the legacy global `(sourceSheet, sourceRow)` uniqueness indexes on
  `ContentRecord` and `RealProductResearch` with
  `(sourceId, sourceSheet, sourceRow)` indexes.
- Kept `ProductDocument`'s existing business uniqueness on
  `(researchId, documentType, fileReference)`; its source relationship is
  provenance only.
- Kept the new columns nullable so Step 8 can backfill legacy rows before
  enforcing non-nullability.
- Registered the migration and capability checks in the FastAPI migration
  tooling.

The configured remote development database already has all three source
relationships, valid foreign keys, and the source-scoped indexes. The read-only
baseline confirmed 46 `ContentRecord` rows, 47 `RealProductResearch` rows, and
21 `ProductDocument` rows with no null or orphan source references, and no
`ProductDocument`/`RealProductResearch` source mismatches.

### Step 4 — Update import and seed scripts

Files:

- `app/db/knowledge_provenance.py`
- `app/db/knowledge_seed.py`
- `scripts/seed_knowledge_data.py`
- `scripts/seed_content_data.py`
- `scripts/seed_real_product_data.py`
- `scripts/seed_real_operations_data.py`
- `docs/knowledge-source-import-contract.md`
- `migrations/0008_knowledge_source_import_key.sql`

Tasks:

- Create or find a `KnowledgeSource` before importing rows.
- Pass its `sourceId` into every imported root record.
- Keep writing `sourceSheet` and `sourceRow`.
- Propagate the relationship to product documents where applicable.
- Make repeated imports deterministic using `fileHash` or a stable import key.

Legacy data that cannot be matched to a known file will receive a clearly
marked legacy source rather than an invented file name.

#### Step 4 implementation record — 2026-08-25

Step 4 is complete at the repository level. The original Next.js seed paths
(`scripts/seed-content-data.ts`, `scripts/seed-real-product-data.ts`, and
`scripts/seed-real-operations-data.ts`) are not present in the current
repositories, so the import contract is implemented as FastAPI-native Python
adapters instead of inventing a missing source-file mapping.

- `app/db/knowledge_provenance.py` provides transactional source registration,
  SHA-256 helpers, and authoritative row-level provenance injection.
- `app/db/knowledge_seed.py` provides a shared JSON payload loader and writer
  for `ContentRecord`, `RealProductResearch`, `ProductDocument`,
  `ProductOperation`, and `ProductPrice`.
- The four CLI adapters expose full-source, content-only, product-only, and
  operations-only imports. They use allowlisted columns, source-scoped
  idempotent upserts, source coordinate validation, and same-source research
  dependency checks.
- `migrations/0008_knowledge_source_import_key.sql` makes repeated imports of
  the same `(workspaceId, fileHash)` deterministic while preserving nullable
  hashes for legacy/manual sources.
- `docs/knowledge-source-import-contract.md` documents the JSON contract and
  the `make seed-* INPUT=...` entry points.

No real seed input was run in this batch because the repository does not
contain a source dataset. Script help, validation/unit tests, SQL parsing, and
the local/remote-write safety gate were verified; no remote database write was
performed.

### Step 5 — Add source-scoped database queries

Files:

- `app/api/routes/content.py`
- `app/api/routes/products.py`
- `app/api/routes/knowledge_sources.py`
- `app/core/knowledge_access.py`
- `app/core/knowledge_base_entity.py`
- `app/services/agent_tools.py`
- `tests/test_content.py`
- `tests/test_products.py`
- `tests/test_knowledge_sources.py`
- `tests/test_knowledge_base_entity.py`

Tasks:

- Resolve user-facing file names to `sourceId` values.
- Add optional source filters to search inputs.
- Apply `sourceId` filtering in SQL.
- Support multiple source files.
- Do not fall back to the full knowledge base when an explicit source filter
  returns no result.

#### Step 5 implementation record — 2026-08-25

Step 5 is complete at the FastAPI repository level. The source-scoped query
path was already present in the migrated backend routes; this step audited the
full request-to-query path and fixed the remaining product-query gap.

- `sourceFileNames` is resolved within the requested workspace and, when
  grants are enabled, intersected with the caller's authorized source IDs.
- Content search applies the resolved IDs to `ContentRecord.sourceId`.
- Product search now applies the resolved IDs to
  `RealProductResearch.sourceId`; it no longer uses only a display-name
  predicate after source resolution.
- Multiple source files are supported by an expanding SQL `IN` parameter.
- An explicit source filter with no authorized/matching source returns an empty
  result and an explanatory message; it never falls back to the full dataset.
- The knowledge-base entity feature flag consistently switches source lookup,
  authorization, content search, product search, and source listing between
  `KnowledgeSource` and `KnowledgeBase`.
- Agent tool input and execution already pass `sourceFileNames` through to the
  same FastAPI query boundary, so the database filter remains authoritative.

Focused content/product/source/entity tests and Ruff checks pass. No database
migration or remote data write is required for this step.

### Step 6 — Update AI tools and prompts

Files:

- `app/services/agent_tools.py`
- `app/services/agent_workflow.py`
- `app/api/routes/chat.py`
- `tests/test_knowledge_search.py`

Tasks:

- Add optional source-file filters to tool schemas.
- Explain source-scoped search in tool descriptions.
- Require the model to use only returned records as factual evidence.
- Keep the actual restriction in the database layer; prompts are not a
  security boundary.

#### Step 6 implementation record — 2026-08-25

Step 6 is complete at the FastAPI repository level:

- `ProductToolInput` and `ContentToolInput` expose the optional
  `sourceFileNames` filter with an explicit exact-display-name description.
- `searchProductsTool` and `searchContentTool` descriptions instruct the model
  to pass every source file named by the user, avoid treating file names as
  ordinary keywords, and use only returned rows as factual evidence.
- The final-summary prompts used by both the bounded agent workflow and the
  streaming chat workflow now state that enterprise tool results are the only
  authoritative evidence. Empty or missing-source results must be reported,
  and named-source requests must not be answered from other sources.
- The database query layer remains the enforcement boundary; prompt guidance
  does not replace workspace or source authorization checks.

The tool schema and workflow tests pass. No database migration or remote data
write is required for this step.

### Step 7 — Return and render citations

Files:

- `app/core/knowledge_citation.py`
- `app/api/routes/content.py`
- `app/api/routes/products.py`
- `tests/test_content.py`
- `tests/test_products.py`
- `../asianodeagent-front/src/lib/knowledgeCitation.ts`
- `../asianodeagent-front/src/lib/db/contentQueries.ts`
- `../asianodeagent-front/src/lib/db/tradeQueries.ts`
- `../asianodeagent-front/src/components/chat/message.tsx`

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

#### Step 7 implementation record — 2026-08-25

Step 7 is complete at the repository level:

- Added the shared backend `SourceCitation` contract with `sourceId`,
  `fileName`, `sheet`, and `row`, plus optional `page` and `section` fields
  reserved for PDF and document citations.
- Content and product API summaries now return a nested `citation` object.
  The existing flat source fields remain in the response for compatibility with
  current clients.
- Updated the frontend result types and chat tool-result cards to render a
  consistent source line using the file name, sheet, and row. The internal
  `sourceId` is available to the application but is not shown to end users.
- Added schema contract tests for both content and product responses.
- No database migration or remote database write was required.

Validation completed:

- Backend Ruff checks passed.
- 27 focused backend tests passed; 3 unrelated environment/auth-gated tests
  were deselected.
- Frontend `npm run lint` passed.
- Frontend `npm run build` passed.

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
