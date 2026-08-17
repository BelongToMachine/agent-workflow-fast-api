from dataclasses import dataclass

from sqlalchemy.engine import make_url

from app.core.config import Settings

LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class MigrationTarget:
    host: str | None
    port: int | None
    database: str | None
    is_local: bool

    @property
    def display_name(self) -> str:
        host = self.host or "unix-socket"
        port = f":{self.port}" if self.port else ""
        database = self.database or "unknown-database"
        return f"{host}{port}/{database}"


def get_migration_target(settings: Settings) -> MigrationTarget:
    if not settings.postgres_url:
        return MigrationTarget(
            host=None,
            port=None,
            database=None,
            is_local=False,
        )

    url = make_url(settings.postgres_url)
    host = url.host
    return MigrationTarget(
        host=host,
        port=url.port,
        database=url.database,
        is_local=host is None or host in LOCAL_DATABASE_HOSTS,
    )


def migration_apply_error(
    settings: Settings,
    *,
    allow_remote: bool = False,
) -> str | None:
    environment = settings.environment.lower()
    if environment in {"production", "staging"}:
        return (
            "Refusing to apply a local migration in staging/production. "
            "Run the reviewed SQL through the deployment migration process."
        )

    target = get_migration_target(settings)
    if not settings.postgres_url:
        return "POSTGRES_URL is not configured; refusing to apply a database migration."
    if not target.is_local and not allow_remote:
        return (
            f"Refusing to apply a local migration to remote target {target.display_name}. "
            "Use a local PostgreSQL database, or pass --allow-remote only after a reviewed "
            "development-database backup and approval."
        )
    return None
