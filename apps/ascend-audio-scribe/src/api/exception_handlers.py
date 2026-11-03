from ascend_python_common.errors import INTERNAL, VALIDATION, ErrorRegistry, ProblemCode

FILE_TOO_LARGE = ProblemCode("file_too_large", 413)
UPSTREAM_PROVIDER = ProblemCode("upstream_provider", 502)


class FileSizeExceededError(Exception):
    """Raised when upload, download, or zip extraction exceeds the configured
    cap. Distinct from ValueError so it can map to 413 (Content Too Large)
    rather than 400 (Validation Failed)."""


class UpstreamProviderError(Exception):
    """Raised when an upstream transcription provider's HTTP call fails
    (timeout, 5xx, connection reset). Distinct from ValueError so it maps to
    502 (Bad Gateway) rather than 400 (Bad Request): the caller's input was
    fine, the provider was unavailable."""


def build_error_registry() -> ErrorRegistry:
    registry = ErrorRegistry(internal_code=INTERNAL)
    registry.register(ValueError, VALIDATION, str)
    registry.register(FileSizeExceededError, FILE_TOO_LARGE, str)
    registry.register(UpstreamProviderError, UPSTREAM_PROVIDER, str, expected=True)
    return registry


error_registry = build_error_registry()
