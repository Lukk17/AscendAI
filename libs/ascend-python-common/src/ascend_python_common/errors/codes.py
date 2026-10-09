from dataclasses import dataclass
from typing import Final

ERROR_TYPE_BASE: Final[str] = "https://ascend.ai/errors/"
INTERNAL_FIXED_DETAIL: Final[str] = "An unexpected error occurred. Check server logs for details."
UNAUTHORIZED_FIXED_DETAIL: Final[str] = "Authentication is required to access this resource."


@dataclass(frozen=True, slots=True)
class ProblemCode:
    code: str
    status: int

    def type_uri(self) -> str:
        return ERROR_TYPE_BASE + self.code.lower().replace("_", "-")


VALIDATION: Final[ProblemCode] = ProblemCode("validation", 400)
BAD_REQUEST: Final[ProblemCode] = ProblemCode("bad_request", 400)
UNAUTHORIZED: Final[ProblemCode] = ProblemCode("unauthorized", 401)
NOT_FOUND: Final[ProblemCode] = ProblemCode("not_found", 404)
METHOD_NOT_ALLOWED: Final[ProblemCode] = ProblemCode("method_not_allowed", 405)
NOT_ACCEPTABLE: Final[ProblemCode] = ProblemCode("not_acceptable", 406)
CONTENT_TOO_LARGE: Final[ProblemCode] = ProblemCode("content_too_large", 413)
UNSUPPORTED_MEDIA_TYPE: Final[ProblemCode] = ProblemCode("unsupported_media_type", 415)
RATE_LIMITED: Final[ProblemCode] = ProblemCode("rate_limited", 429)
HTTP_ERROR: Final[ProblemCode] = ProblemCode("http_error", 500)
INTERNAL: Final[ProblemCode] = ProblemCode("internal", 500)

_PLATFORM_BY_STATUS: Final[dict[int, ProblemCode]] = {
    400: BAD_REQUEST,
    401: UNAUTHORIZED,
    404: NOT_FOUND,
    405: METHOD_NOT_ALLOWED,
    406: NOT_ACCEPTABLE,
    413: CONTENT_TOO_LARGE,
    415: UNSUPPORTED_MEDIA_TYPE,
    429: RATE_LIMITED,
    500: INTERNAL,
}


def platform_code_for_status(status: int) -> ProblemCode:
    found = _PLATFORM_BY_STATUS.get(status)
    if found is not None:
        return found
    return ProblemCode("http_error", status)


__all__ = [
    "BAD_REQUEST",
    "CONTENT_TOO_LARGE",
    "ERROR_TYPE_BASE",
    "HTTP_ERROR",
    "INTERNAL",
    "INTERNAL_FIXED_DETAIL",
    "METHOD_NOT_ALLOWED",
    "NOT_ACCEPTABLE",
    "NOT_FOUND",
    "RATE_LIMITED",
    "UNAUTHORIZED",
    "UNAUTHORIZED_FIXED_DETAIL",
    "UNSUPPORTED_MEDIA_TYPE",
    "VALIDATION",
    "ProblemCode",
    "platform_code_for_status",
]
