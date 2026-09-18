import json
import logging

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.main import create_app
from app.services.agent_trace import (
    agent_database_trace_enabled,
    agent_tool_trace_context,
    configure_agent_trace_file_logging,
    install_agent_database_trace,
    summarize_tool_output,
    trace_event,
)


def test_agent_trace_is_enabled_only_for_development_and_can_be_disabled() -> None:
    assert (
        agent_database_trace_enabled(
            Settings(environment="development", agent_trace_logging_enabled=True)
        )
        is True
    )
    assert (
        agent_database_trace_enabled(
            Settings(environment="production", agent_trace_logging_enabled=True)
        )
        is False
    )
    assert (
        agent_database_trace_enabled(
            Settings(environment="development", agent_trace_logging_enabled=False)
        )
        is False
    )


def test_trace_event_logs_redacted_question_as_structured_json(caplog) -> None:
    settings = Settings(environment="development", agent_trace_logging_enabled=True)
    question = "Find the file; api_key=top-secret Bearer abc.def.ghi"

    with caplog.at_level(logging.INFO, logger="app.agent_trace"):
        trace_event(
            settings,
            "chat_request_started",
            request_id="request-1",
            user_question_preview=question,
        )

    record = next(record for record in caplog.records if "AGENT_TRACE " in record.message)
    payload = json.loads(record.message.split("AGENT_TRACE ", maxsplit=1)[1])
    assert payload["event"] == "chat_request_started"
    assert payload["request_id"] == "request-1"
    assert "top-secret" not in record.message
    assert "abc.def.ghi" not in record.message
    assert "[REDACTED]" in payload["user_question_preview"]


def test_trace_event_emits_nothing_when_not_in_development(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.agent_trace"):
        trace_event(
            Settings(environment="production"),
            "chat_request_received",
            request_id="request-ignored",
            user_question_preview="must not be logged",
        )

    assert "AGENT_TRACE" not in caplog.text


def test_trace_event_is_written_to_a_rotating_dev_log_file(tmp_path) -> None:
    from app.services.agent_trace import logger

    log_path = tmp_path / "agent-trace.log"
    settings = Settings(
        environment="development",
        agent_trace_logging_enabled=True,
        agent_trace_log_file=str(log_path),
    )

    try:
        assert configure_agent_trace_file_logging(settings) == log_path
        assert configure_agent_trace_file_logging(settings) == log_path
        trace_event(
            settings,
            "chat_request_received",
            request_id="request-file",
            user_question_preview="Find the policy",
        )

        contents = log_path.read_text(encoding="utf-8")
        assert '"event":"chat_request_received"' in contents
        assert '"request_id":"request-file"' in contents
        handlers = [
            handler
            for handler in logger.handlers
            if getattr(handler, "_agent_trace_file_handler", False)
        ]
        assert len(handlers) == 1
        assert handlers[0].maxBytes > 0
        assert handlers[0].backupCount > 0
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_agent_trace_file_handler", False):
                logger.removeHandler(handler)
                handler.close()


def test_trace_file_is_not_created_outside_development(tmp_path) -> None:
    log_path = tmp_path / "agent-trace.log"
    settings = Settings(
        environment="production",
        agent_trace_logging_enabled=True,
        agent_trace_log_file=str(log_path),
    )

    assert configure_agent_trace_file_logging(settings) is None
    assert not log_path.exists()


def test_fastapi_startup_configures_the_trace_file_only_in_development(
    monkeypatch,
    tmp_path,
) -> None:
    from app.services.agent_trace import logger

    log_path = tmp_path / "startup-trace.log"
    settings = Settings(
        environment="development",
        agent_trace_logging_enabled=True,
        agent_trace_log_file=str(log_path),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    try:
        with TestClient(create_app()):
            pass
        assert log_path.exists()
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_agent_trace_file_handler", False):
                logger.removeHandler(handler)
                handler.close()


def test_database_trace_reports_database_and_tables_without_bind_values(caplog) -> None:
    settings = Settings(environment="development", agent_trace_logging_enabled=True)
    engine = create_engine("sqlite:///:memory:")
    install_agent_database_trace(engine, settings)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "KnowledgeChunk" ("content" TEXT)'))

    with caplog.at_level(logging.INFO, logger="app.agent_trace"):
        with agent_tool_trace_context(
            settings,
            request_id="request-2",
            chat_id="chat-3",
            tool_name="searchKnowledgeBaseTool",
        ):
            with engine.connect() as connection:
                connection.execute(
                    text('SELECT * FROM "KnowledgeChunk" WHERE "content" = :content'),
                    {"content": "private document passage"},
                ).all()

    payloads = [
        json.loads(record.message.split("AGENT_TRACE ", maxsplit=1)[1])
        for record in caplog.records
        if "AGENT_TRACE " in record.message
    ]
    query = next(payload for payload in payloads if payload["event"] == "database_query_started")
    assert query["database_name"] == ":memory:"
    assert query["tables"] == ["KnowledgeChunk"]
    assert query["tool_name"] == "searchKnowledgeBaseTool"
    assert "private document passage" not in caplog.text

    engine.dispose()


def test_tool_output_summary_keeps_source_metadata_and_omits_document_content() -> None:
    summary = summarize_tool_output(
        "searchKnowledgeBaseTool",
        {
            "results": [
                {
                    "chunkId": "chunk-1",
                    "content": "confidential knowledge text",
                    "fileId": "file-1",
                    "fileName": "pricing.xlsx",
                }
            ]
        },
    )

    assert summary["result_count"] == 1
    assert summary["source_files"] == [
        {"file_id": "file-1", "file_name": "pricing.xlsx"}
    ]
    assert "confidential knowledge text" not in json.dumps(summary)


def test_extract_summary_identifies_read_file_without_logging_parsed_blocks() -> None:
    summary = summarize_tool_output(
        "extractKnowledgeFileTool",
        {
            "parsedDocument": {
                "blocks": [{"text": "confidential parsed content"}],
                "contentType": "text",
                "fileId": "file-2",
                "originalName": "handbook.pdf",
            }
        },
    )

    assert summary["source_files"] == [
        {"file_id": "file-2", "file_name": "handbook.pdf"}
    ]
    assert summary["parsed_document"]["blocks_count"] == 1
    assert "confidential parsed content" not in json.dumps(summary)
