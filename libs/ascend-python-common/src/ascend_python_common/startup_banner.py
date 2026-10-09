import re
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

DIVIDER_WIDTH: Final[int] = 80
DIVIDER: Final[str] = "-" * DIVIDER_WIDTH
MASKED_VALUE: Final[str] = "****"

CONNECTED: Final[str] = "Connected"
FAILED: Final[str] = "FAILED"
CONFIGURED: Final[str] = "Configured"
NOT_CONFIGURED: Final[str] = "Not configured"

_USER_INFO_RE: Final[re.Pattern[str]] = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s@]+@")


@dataclass(frozen=True, slots=True)
class BannerLine:
    label: str
    value: str
    secret: bool = False


@dataclass(frozen=True, slots=True)
class BannerCheck:
    label: str
    target: str
    status: str


@dataclass(frozen=True, slots=True)
class BannerSection:
    title: str
    entries: Sequence[BannerLine | BannerCheck] = ()


def warning(reason: str) -> str:
    return f"Warning ({reason})"


def strip_user_info(value: str) -> str:
    return _USER_INFO_RE.sub(r"\1", value)


def format_check(target: str, status: str) -> str:
    return f"{strip_user_info(target)} [{status}]"


def render_value(value: str, *, secret: bool) -> str:
    if secret:
        return MASKED_VALUE
    return strip_user_info(value)


def render_section(section: BannerSection) -> list[str]:
    width = max((len(entry.label) + 1 for entry in section.entries), default=0)
    lines = [f"    {section.title}:"]
    for entry in section.entries:
        if isinstance(entry, BannerCheck):
            rendered = format_check(entry.target, entry.status)
        else:
            rendered = render_value(entry.value, secret=entry.secret)
        lines.append(f"      {entry.label + ':':<{width}}  {rendered}")
    return lines


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


def build_banner(
    *,
    service_name: str,
    api_port: int,
    log_level: str,
    art: str,
    sections: Sequence[BannerSection] = (),
    host: str | None = None,
) -> list[str]:
    resolved_host = host if host is not None else _resolve_host()
    local_url = f"http://localhost:{api_port}"
    frame = (
        BannerSection(
            "Access URLs",
            (
                BannerLine("Local", local_url),
                BannerLine("Hostname", f"http://{resolved_host}:{api_port}"),
            ),
        ),
        BannerSection(
            "Actuator",
            (
                BannerLine("Health", f"{local_url}/health"),
                BannerLine("Ready", f"{local_url}/ready"),
                BannerLine("Metrics", f"{local_url}/metrics"),
            ),
        ),
        BannerSection(
            "MCP endpoint",
            (BannerLine("HTTP", f"POST {local_url}/mcp"),),
        ),
    )
    lines = [
        "",
        *art.splitlines(),
        DIVIDER,
        f"    Application '{service_name}' is running!",
        "",
        f"    Profile(s): default (log level: {log_level})",
        "",
    ]
    for index, section in enumerate((*frame, *sections)):
        if index > 0:
            lines.append("")
        lines.extend(render_section(section))
    lines.append(DIVIDER)
    return lines


__all__ = [
    "CONFIGURED",
    "CONNECTED",
    "DIVIDER",
    "DIVIDER_WIDTH",
    "FAILED",
    "MASKED_VALUE",
    "NOT_CONFIGURED",
    "BannerCheck",
    "BannerLine",
    "BannerSection",
    "build_banner",
    "format_check",
    "render_section",
    "render_value",
    "strip_user_info",
    "warning",
]
