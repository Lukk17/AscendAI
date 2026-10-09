import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

logger = logging.getLogger(__name__)

ProbeStatus = Literal["ok", "skipped", "degraded", "error"]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    details: dict[str, str] | None = None


ProbeCallable = Callable[[], ProbeResult] | Callable[[], Coroutine[Any, Any, ProbeResult]]


async def _call_probe(
    name: str, probe: ProbeCallable, probe_timeout_seconds: float
) -> tuple[str, ProbeResult]:
    try:
        if inspect.iscoroutinefunction(probe):
            async_probe = cast("Callable[[], Awaitable[ProbeResult]]", probe)
            result = await asyncio.wait_for(async_probe(), timeout=probe_timeout_seconds)
        else:
            sync_probe = cast("Callable[[], ProbeResult]", probe)
            result = await asyncio.wait_for(asyncio.to_thread(sync_probe), timeout=probe_timeout_seconds)
    except TimeoutError:
        logger.warning("Readiness probe %s timed out", name)
        return name, ProbeResult(status="error")
    except Exception:
        logger.warning("Readiness probe %s failed", name)
        return name, ProbeResult(status="error")
    return name, result


async def check_readiness(
    probes: Mapping[str, ProbeCallable],
    probe_timeout_seconds: float,
) -> dict[str, ProbeResult]:
    checked = await asyncio.gather(
        *(_call_probe(name, probe, probe_timeout_seconds) for name, probe in probes.items())
    )
    return dict(checked)


def checks_body(results: Mapping[str, ProbeResult]) -> dict[str, dict[str, str]]:
    body: dict[str, dict[str, str]] = {}
    for name, result in results.items():
        entry: dict[str, str] = {"status": result.status}
        if result.details is not None:
            entry.update(result.details)
        body[name] = entry
    return body


def is_ready(results: Mapping[str, ProbeResult]) -> bool:
    return all(result.status in ("ok", "skipped") for result in results.values())


__all__ = [
    "ProbeCallable",
    "ProbeResult",
    "ProbeStatus",
    "check_readiness",
    "checks_body",
    "is_ready",
]
