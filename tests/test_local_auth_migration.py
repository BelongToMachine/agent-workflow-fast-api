from pathlib import Path

from app.db.local_auth_status import build_local_auth_status
from app.db.migration_utils import split_sql_statements

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "0010_local_auth.sql"


def test_local_auth_migration_defines_all_foundation_tables_and_constraints() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    for table in ("PasswordCredential", "AuthSession", "AuthOneTimeToken", "AuthAuditLog"):
        assert f'CREATE TABLE IF NOT EXISTS "{table}"' in sql
    assert '"PasswordCredential_user_fk"' in sql
    assert '"AuthSession_user_fk"' in sql
    assert '"AuthOneTimeToken_purpose_check"' in sql
    assert '"AuthAuditLog_session_fk"' in sql
    assert "ON DELETE SET NULL" in sql


def test_local_auth_migration_can_be_split_into_complete_sql_statements() -> None:
    statements = split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8"))

    assert len(statements) == 9
    assert all(statement for statement in statements)


def test_local_auth_status_requires_every_table_column_and_index() -> None:
    flags = {
        "password_table": True,
        "password_required_columns": True,
        "session_table": True,
        "session_required_columns": True,
        "one_time_table": True,
        "one_time_required_columns": True,
        "audit_table": True,
        "audit_required_columns": True,
        "session_index": True,
        "one_time_index": True,
        "audit_index": True,
    }

    assert build_local_auth_status(flags).applied is True
    flags["audit_index"] = False
    assert build_local_auth_status(flags).applied is False
