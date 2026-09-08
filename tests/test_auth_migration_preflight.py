from app.db.auth_migration_preflight import build_auth_migration_preflight


def test_auth_migration_preflight_reports_counts_and_safe_mapping() -> None:
    preflight = build_auth_migration_preflight(
        {
            "user_count": 4,
            "external_identity_count": 3,
            "workspace_member_count": 4,
            "permission_count": 2,
            "duplicate_email_groups": 0,
            "invalid_email_count": 0,
        }
    )

    assert preflight.user_count == 4
    assert preflight.external_identity_count == 3
    assert preflight.safe_for_identity_mapping is True


def test_auth_migration_preflight_blocks_duplicate_or_invalid_email_data() -> None:
    preflight = build_auth_migration_preflight(
        {"duplicate_email_groups": 1, "invalid_email_count": 2}
    )

    assert preflight.safe_for_identity_mapping is False
