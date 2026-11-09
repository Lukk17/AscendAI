import re
from typing import Final
from urllib.parse import urlsplit

from ascend_python_common.startup_banner import strip_user_info

UNREADABLE_ADDRESS: Final[str] = "<unreadable address>"

MAX_EXCEPTION_TEXT_LENGTH: Final[int] = 1000

_PATH_PARAMETERS_SEPARATOR: Final[str] = ";"

_HTTP_ADDRESS: Final[re.Pattern[str]] = re.compile(r"https?://[^\s\"'<>]*", re.IGNORECASE)


def address_without_query(url: str) -> str:
    """Scheme, host, port and path of *url*, never its user info, query, fragment or path parameters."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return UNREADABLE_ADDRESS
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    shown_port = "" if port is None else f":{port}"
    path = parts.path.partition(_PATH_PARAMETERS_SEPARATOR)[0]

    return f"{parts.scheme.lower()}://{host}{shown_port}{path}"


def _shown_address(match: re.Match[str]) -> str:
    return address_without_query(match.group())


def exception_text_without_queries(exc: BaseException) -> str:
    """The text of *exc*, capped, with each http or https address cut by address_without_query."""
    capped = str(exc)[:MAX_EXCEPTION_TEXT_LENGTH]

    return (
        strip_user_info(_HTTP_ADDRESS.sub(_shown_address, capped))[:MAX_EXCEPTION_TEXT_LENGTH]
        or type(exc).__name__
    )
