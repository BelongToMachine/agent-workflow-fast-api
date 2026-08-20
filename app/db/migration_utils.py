import re
from dataclasses import dataclass

from sqlalchemy.engine import make_url

from app.core.config import Settings

LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_DOLLAR_QUOTE_PATTERN = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def split_sql_statements(sql: str) -> list[str]:
    """Split migration SQL without breaking quoted or dollar-quoted blocks."""
    statements: list[str] = []
    statement_start = 0
    quote: str | None = None
    dollar_quote: str | None = None
    index = 0

    while index < len(sql):
        if dollar_quote is not None:
            if sql.startswith(dollar_quote, index):
                index += len(dollar_quote)
                dollar_quote = None
            else:
                index += 1
            continue

        if quote is not None:
            if sql[index] == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif sql[index] == "\\" and quote == "'":
                index += 2
                continue
            index += 1
            continue

        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline == -1 else newline + 1
            continue

        if sql.startswith("/*", index):
            comment_end = sql.find("*/", index + 2)
            index = len(sql) if comment_end == -1 else comment_end + 2
            continue

        character = sql[index]
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue

        if character == "$":
            match = _DOLLAR_QUOTE_PATTERN.match(sql, index)
            if match:
                dollar_quote = match.group(0)
                index = match.end()
                continue

        if character == ";":
            statement = sql[statement_start:index].strip()
            if statement:
                statements.append(statement)
            statement_start = index + 1
        index += 1

    trailing_statement = sql[statement_start:].strip()
    if trailing_statement:
        statements.append(trailing_statement)
    return statements


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
