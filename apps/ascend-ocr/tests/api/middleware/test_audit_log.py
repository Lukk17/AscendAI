import logging
from collections.abc import Iterator

import pytest

from src.api.middleware.audit_log import emit_mcp_audit
from src.api.middleware.correlation_id import mcp_request_log_context

AUDITED_CORRELATION_ID = "corr-1"


@pytest.fixture
def audit_records() -> Iterator[list[logging.LogRecord]]:
    """Attach a dedicated capture handler to `ascend-ocr.audit` and yield the records list.

    Going through `caplog` is fragile here: other tests in the suite call
    `setup_logging()`, which invokes `logging.basicConfig(force=True)`. That removes any
    handlers `caplog` attached at fixture setup, so audit records that ARE emitted by the
    application logger never reach `caplog.records`. A handler attached directly to the
    named logger is immune to the global reset.
    """
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("ascend-ocr.audit")
    handler = _ListHandler(level=logging.INFO)
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.fixture
def audited_correlation_id() -> Iterator[str]:
    with mcp_request_log_context(AUDITED_CORRELATION_ID, None):
        yield AUDITED_CORRELATION_ID


class TestEmitMcpAudit:
    def test_emits_record_with_audit_fields(
        self, audit_records: list[logging.LogRecord], audited_correlation_id: str
    ) -> None:
        # When
        emit_mcp_audit("ocr_submit", "http", "host.docker.internal", 1024, "ok")

        # Then
        record = next(r for r in audit_records if r.name == "ascend-ocr.audit")
        fields = dict(record.__dict__)
        assert fields["audit_action"] == "ocr_submit"
        assert fields["audit_scheme"] == "http"
        assert fields["audit_host"] == "host.docker.internal"
        assert fields["audit_bytes"] == 1024
        assert fields["audit_outcome"] == "ok"
        assert fields["correlation_id"] == audited_correlation_id

    def test_emits_record_with_none_host_placeholder(self, audit_records: list[logging.LogRecord]) -> None:
        # When
        emit_mcp_audit("ocr_submit", "file", None, 256, "ok")

        # Then
        record = next(r for r in audit_records if r.name == "ascend-ocr.audit")
        assert record.__dict__["audit_host"] == "(none)"
