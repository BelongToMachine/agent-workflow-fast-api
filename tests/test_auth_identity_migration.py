from app.db.auth_identity_status import (
    AUTH_IDENTITY_STATUS_QUERY,
    build_auth_identity_status,
)
from app.db.migrate_auth_identity import MIGRATION_PATH, PREREQUISITE_QUERY
from app.db.migration_utils import split_sql_statements


def test_auth_identity_migration_file_is_present_and_idempotent() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'CREATE TABLE IF NOT EXISTS "ExternalIdentity"' in sql
    assert 'ADD COLUMN IF NOT EXISTS "status"' in sql
    assert 'CREATE INDEX IF NOT EXISTS "ExternalIdentity_user_idx"' in sql
    assert 'UNIQUE ("provider", "subject")' in sql
    assert 'REFERENCES "public"."User"("id")' in sql


def test_auth_identity_status_requires_every_schema_capability() -> None:
    row = {
        "user_table": True,
        "user_required_columns": True,
        "user_email_compatible": True,
        "user_status_column": True,
        "user_status_check": True,
        "identity_table": True,
        "identity_required_columns": True,
        "identity_user_idx": True,
        "identity_user_fk": True,
        "identity_provider_subject_key": True,
    }

    status = build_auth_identity_status(row)

    assert status.applied is True
    assert status.name == "0005_auth_identity"

    row["identity_provider_subject_key"] = False
    assert build_auth_identity_status(row).applied is False


def test_auth_identity_status_query_covers_user_and_external_identity_schema() -> None:
    sql = str(AUTH_IDENTITY_STATUS_QUERY)

    assert "user_email_compatible" in sql
    assert "user_status_check" in sql
    assert "identity_required_columns" in sql
    assert "ExternalIdentity_provider_subject_key" in sql


def test_auth_identity_preflight_only_checks_existing_user_prerequisites() -> None:
    sql = str(PREREQUISITE_QUERY)

    assert 'to_regclass(\'public."User"\')' in sql
    assert "column_name IN ('id', 'email')" in sql


def test_sql_splitter_keeps_dollar_quoted_blocks_together() -> None:
    statements = split_sql_statements(
        "CREATE TABLE example (id uuid);"
        "DO $$ BEGIN PERFORM 1; PERFORM 2; END $$;"
        "CREATE INDEX example_id_idx ON example (id);"
    )

    assert len(statements) == 3
    assert statements[1].startswith("DO $$")
    assert "PERFORM 1; PERFORM 2;" in statements[1]
