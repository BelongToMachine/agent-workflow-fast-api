"""Local development tracing for chat-agent decisions, tools, and database reads.

Provider APIs do not expose a safe, supported hidden chain-of-thought stream. This
module records observable execution events instead: model turns, selected tools,
sanitized tool arguments, source-file metadata, and SQL operation/table metadata.
"""

import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic
from typing import Any
from weakref import WeakSet

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import SERVICE_ROOT, Settings

logger = logging.getLogger("app.agent_trace")

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "refreshtoken",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|"
    r"passwd|secret|authorization|cookie)[\"']?\s*[:=]\s*)"
    r"[\"']?[^\"'\s,;}\]]+[\"']?"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_URL_CREDENTIALS_RE = re.compile(r"(https?://)[^/@\s]+:[^/@\s]+@", re.IGNORECASE)
_TOKEN_PREFIX_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_TABLE_REFERENCE_RE = re.compile(
    r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+(?:"([^"]+)"|([A-Za-z_][\w.$]*))',
    re.IGNORECASE,
)
_SQL_OPERATION_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH|CALL|SHOW)\b", re.I)
_active_trace: ContextVar["AgentTraceContext | None"] = ContextVar(
    "active_agent_trace",
    default=None,
)
_installed_engines: WeakSet[Engine] = WeakSet()
_TRACE_LOG_MAX_BYTES = 10 * 1024 * 1024
_TRACE_LOG_BACKUP_COUNT = 5
_TRACE_FILE_HANDLER_MARKER = "_agent_trace_file_handler"


@dataclass(frozen=True)
class AgentTraceContext:
    request_id: str
    chat_id: str
    tool_name: str | None = None


def agent_database_trace_enabled(settings: Settings) -> bool:
    """Trace only explicitly enabled local development configurations."""
    return (
        settings.agent_trace_logging_enabled
        and settings.environment.strip().lower() == "development"
    )


def configure_agent_trace_file_logging(settings: Settings) -> Path | None:
    """Attach a bounded JSON-line file handler for local development traces."""
    if not agent_database_trace_enabled(settings):
        return None

    configured_path = Path(settings.agent_trace_log_file).expanduser()
    log_path = (
        configured_path if configured_path.is_absolute() else SERVICE_ROOT / configured_path
    ).resolve()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        for handler in tuple(logger.handlers):
            if not getattr(handler, _TRACE_FILE_HANDLER_MARKER, False):
                continue
            if Path(handler.baseFilename) == log_path:
                return log_path
            logger.removeHandler(handler)
            handler.close()

        handler = RotatingFileHandler(
            log_path,
            mode="a",
            maxBytes=_TRACE_LOG_MAX_BYTES,
            backupCount=_TRACE_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        setattr(handler, _TRACE_FILE_HANDLER_MARKER, True)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = True
    except OSError:
        logging.getLogger("app").exception(
            "Failed to open the local chat-agent trace log file",
            extra={"agent_trace_log_file": str(log_path)},
        )
        return None
    return log_path


def redact_sensitive_text(value: str, *, max_length: int = 1200) -> str:
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", value)
    redacted = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", redacted)
    redacted = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", redacted)
    redacted = _TOKEN_PREFIX_RE.sub("[REDACTED_TOKEN]", redacted)
    if len(redacted) > max_length:
        return redacted[:max_length] + "…[truncated]"
    return redacted


def _is_sensitive_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(part.replace("_", "") in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_trace_value(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_trace_value(item_value, key=str(item_key))
            for item_key, item_value in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_trace_value(item) for item in list(value)[:20]]
    if isinstance(value, str):
        return redact_sensitive_text(value, max_length=1000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive_text(str(value), max_length=1000)


def trace_event(
    settings: Settings,
    event_name: str,
    *,
    request_id: str | None = None,
    chat_id: str | None = None,
    **fields: Any,
) -> None:
    """Write one JSON event to the local console logger when tracing is enabled."""
    if not agent_database_trace_enabled(settings):
        return

    context = _active_trace.get()
    explicit_tool_name = fields.pop("tool_name", None)
    _write_trace_event(
        event_name,
        request_id=request_id or (context.request_id if context else None),
        chat_id=chat_id or (context.chat_id if context else None),
        tool_name=explicit_tool_name or (context.tool_name if context else None),
        **fields,
    )


def _write_trace_event(
    event_name: str,
    *,
    request_id: str | None,
    chat_id: str | None,
    tool_name: str | None = None,
    **fields: Any,
) -> None:
    """Write an event when its caller has already passed the environment gate."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "event": event_name,
        "request_id": request_id,
        "chat_id": chat_id,
    }
    if tool_name:
        entry["tool_name"] = tool_name
    entry.update(sanitize_trace_value(fields))
    logger.info("AGENT_TRACE %s", json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


@contextmanager
def agent_tool_trace_context(
    settings: Settings,
    *,
    request_id: str,
    chat_id: str,
    tool_name: str,
) -> Iterator[None]:
    """Bind correlation metadata while a tool (and its SQL calls) is running."""
    if not agent_database_trace_enabled(settings):
        yield
        return

    token: Token[AgentTraceContext | None] = _active_trace.set(
        AgentTraceContext(
            request_id=request_id,
            chat_id=chat_id,
            tool_name=tool_name,
        )
    )
    try:
        yield
    finally:
        _active_trace.reset(token)


def _sql_metadata(statement: str) -> dict[str, Any]:
    operation_match = _SQL_OPERATION_RE.search(statement)
    table_names: list[str] = []
    seen: set[str] = set()
    for match in _TABLE_REFERENCE_RE.finditer(statement):
        table_name = match.group(1) or match.group(2)
        if table_name and table_name not in seen:
            seen.add(table_name)
            table_names.append(table_name)
    return {
        "operation": operation_match.group(1).upper() if operation_match else "UNKNOWN",
        "tables": table_names,
    }


def _before_cursor_execute(
    connection: Any,
    _cursor: Any,
    statement: str,
    _parameters: Any,
    execution_context: Any,
    _executemany: bool,
) -> None:
    trace = _active_trace.get()
    if trace is None:
        return

    metadata = _sql_metadata(statement)
    execution_context._agent_trace_metadata = metadata
    execution_context._agent_trace_started_at = monotonic()
    _write_trace_event(
        "database_query_started",
        request_id=trace.request_id,
        chat_id=trace.chat_id,
        tool_name=trace.tool_name,
        database_name=connection.engine.url.database,
        **metadata,
    )


def _after_cursor_execute(
    connection: Any,
    cursor: Any,
    _statement: str,
    _parameters: Any,
    execution_context: Any,
    _executemany: bool,
) -> None:
    trace = _active_trace.get()
    metadata = getattr(execution_context, "_agent_trace_metadata", None)
    started_at = getattr(execution_context, "_agent_trace_started_at", None)
    if trace is None or metadata is None or started_at is None:
        return

    row_count = getattr(cursor, "rowcount", None)
    _write_trace_event(
        "database_query_completed",
        request_id=trace.request_id,
        chat_id=trace.chat_id,
        tool_name=trace.tool_name,
        database_name=connection.engine.url.database,
        elapsed_ms=round((monotonic() - started_at) * 1000),
        row_count=row_count if isinstance(row_count, int) and row_count >= 0 else None,
        **metadata,
    )


def install_agent_database_trace(engine: Any, settings: Settings) -> None:
    """Install SQL metadata hooks on local dev engines; bind values are never logged."""
    if not agent_database_trace_enabled(settings):
        return
    sync_engine = getattr(engine, "sync_engine", engine)
    if sync_engine in _installed_engines:
        return
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", _after_cursor_execute)
    _installed_engines.add(sync_engine)


def _source_files(value: Any) -> list[dict[str, str | None]]:
    found: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            file_id = (
                item.get("fileId")
                or item.get("file_id")
                or item.get("sourceFileId")
                or item.get("source_file_id")
            )
            file_name = (
                item.get("fileName")
                or item.get("originalName")
                or item.get("sourceFileName")
                or item.get("source_file_name")
            )
            if file_id or file_name:
                pair = (str(file_id) if file_id else None, str(file_name) if file_name else None)
                if pair not in seen:
                    seen.add(pair)
                    found.append({"file_id": pair[0], "file_name": pair[1]})
            for key, child in item.items():
                if str(key).lower() not in {
                    "content",
                    "text",
                    "searchtext",
                    "copytext",
                    "notes",
                }:
                    visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return found[:20]


def summarize_tool_output(tool_name: str, output: Mapping[str, Any]) -> dict[str, Any]:
    """Keep counts and source metadata; never include returned document contents."""
    if "error" in output:
        return {
            "status": "error",
            "error": redact_sensitive_text(str(output.get("error", "")), max_length=300),
        }

    item_keys = (
        "results",
        "products",
        "records",
        "files",
        "knowledgeBases",
        "knowledgeBase",
        "file",
    )
    result_items: Any = None
    for key in item_keys:
        if key in output:
            result_items = output[key]
            break

    if isinstance(result_items, (list, tuple)):
        result_count = len(result_items)
    elif result_items is None:
        result_count = None
    else:
        result_count = 1

    summary: dict[str, Any] = {"status": "completed", "tool_name": tool_name}
    if result_count is not None:
        summary["result_count"] = result_count
    source_files = _source_files(output)
    if source_files:
        summary["source_files"] = source_files
    parsed_document = output.get("parsedDocument")
    if isinstance(parsed_document, Mapping):
        summary["parsed_document"] = {
            "file_id": parsed_document.get("fileId"),
            "file_name": parsed_document.get("fileName")
            or parsed_document.get("originalName"),
            "document_type": parsed_document.get("documentType")
            or parsed_document.get("contentType"),
            "parser": parsed_document.get("parser"),
        }
        for key in ("blocks", "rows", "pages", "sheets", "slides"):
            collection = parsed_document.get(key)
            if isinstance(collection, (list, tuple)):
                summary["parsed_document"][f"{key}_count"] = len(collection)
    return summary
