import logging
from collections.abc import Iterator

import pytest

from src.api.middleware.audit_log import emit_mcp_audit
from src.api.middleware.correlation_id import set_correlation_id


@pytest.fixture
def audit_records() -> Iterator[list[logging.LogRecord]]:
    """Attach a dedicated capture handler to `paddleocr.audit` and yield the records list.

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

    logger = logging.getLogger("paddleocr.audit")
    handler = _ListHandler(level=logging.INFO)
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


class TestEmitMcpAudit:
    def test_emits_record_with_audit_fields(self, audit_records: list[logging.LogRecord]):
        # Given
        set_correlation_id("corr-1")

        # When
        emit_mcp_audit("ocr_process", "http", "host.docker.internal", 1024, "ok")

        # Then
        record = next(r for r in audit_records if r.name == "paddleocr.audit")
        fields = dict(record.__dict__)
        assert fields["audit_action"] == "ocr_process"
        assert fields["audit_scheme"] == "http"
        assert fields["audit_host"] == "host.docker.internal"
        assert fields["audit_bytes"] == 1024
        assert fields["audit_outcome"] == "ok"
        assert fields["correlation_id"] == "corr-1"

    def test_emits_record_with_none_host_placeholder(
            self, audit_records: list[logging.LogRecord]
    ):
        # When
        emit_mcp_audit("ocr_process", "file", None, 256, "ok")

        # Then
        record = next(r for r in audit_records if r.name == "paddleocr.audit")
        assert record.__dict__["audit_host"] == "(none)"
