from src.api.middleware.correlation_id import get_correlation_id
from src.config.logging_config import get_logger

logger = get_logger("paddleocr.audit")


def emit_mcp_audit(
    action: str,
    scheme: str,
    host: str | None,
    bytes_count: int,
    outcome: str,
) -> None:
    logger.info(
        "audit",
        extra={
            "audit_action": action,
            "audit_scheme": scheme,
            "audit_host": host or "(none)",
            "audit_bytes": bytes_count,
            "audit_outcome": outcome,
            "correlation_id": get_correlation_id(),
        },
    )
