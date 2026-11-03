"""Per-container slot registry with the flow records in Redis.

Each ascend-web-hunter container owns its display, so the slot pool, the
browsers and the monitor tasks live in the process. What every container
must agree on is which key has a live flow, so each live flow also has a
record in Redis under ``novnc_flow:{registrable_domain}:{profile}``,
written with ``SET NX PX`` for the flow's lease and deleted on release by
a compare-and-delete script, so a flow never deletes a record a later
flow wrote.

A Redis error never fails the caller: the flow is kept in the process
only, which is the behaviour of a single container, so a join then works
only inside the same container until Redis answers again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ascend_python_common.request_context import get_correlation_id

from src.api.exceptions import NoVNCFlowBusyException
from src.config.config import settings
from src.observability.metrics import NOVNC_ACTIVE_FLOWS, NOVNC_FLOWS_RECLAIMED_TOTAL
from src.reader.cloudflare.cookie_manager import CookieManager, cookie_manager
from src.reader.novnc.window_layout import WindowRect, rect_for_slot

logger = logging.getLogger(__name__)

NOVNC_FLOW_KEY_PREFIX = "novnc_flow:"

_FLOW_ID_HEX_LENGTH = 12

_RESERVE_ATTEMPTS = 3

# Deletes the record only while it still holds this flow_id, so a flow
# never deletes a record a later flow wrote for the same key.
_RELEASE_SCRIPT = (
    "local raw = redis.call('GET', KEYS[1]) "
    "if raw and cjson.decode(raw)['flow_id'] == ARGV[1] "
    "then return redis.call('DEL', KEYS[1]) "
    "else return 0 end"
)


def flow_key_for(url: str, profile: str | None) -> str:
    """Return the flow key for *url* + *profile*: registrable domain plus profile."""
    domain = CookieManager.registrable_domain(url)
    effective_profile = profile or settings.SESSION_DEFAULT_PROFILE

    return f"{domain}:{effective_profile}"


def _redis_key(flow_key: str) -> str:
    return f"{NOVNC_FLOW_KEY_PREFIX}{flow_key}"


def _lease_seconds() -> float:
    return settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS


def _lease_ms() -> int:
    return int(_lease_seconds() * 1000)


def flow_shape(flow: NoVNCFlow, now: float | None = None) -> dict[str, Any]:
    """The single flow shape shared by the 409 body and the listing."""
    at = time.time() if now is None else now

    return {
        "flow_id": flow.flow_id,
        "url": flow.url,
        "domain": CookieManager.registrable_domain(flow.url),
        "profile": flow.profile,
        "intervention_type": flow.intervention_type,
        "window": {
            "slot": flow.window.slot,
            "x": flow.window.x,
            "y": flow.window.y,
            "width": flow.window.width,
            "height": flow.window.height,
        },
        "age_seconds": round(at - flow.started_at, 1),
        "expires_in_seconds": round(max(0.0, flow.started_at + _lease_seconds() - at), 1),
        "vnc_url": flow.vnc_url,
    }


@dataclass
class NoVNCFlow:
    """The record of one live intervention flow.

    `task` and `lease_started` exist in the owning process only and are
    never written to Redis.
    """

    flow_id: str
    key: str
    url: str
    profile: str
    intervention_type: str
    window: WindowRect
    vnc_url: str
    started_at: float
    request_id: str
    task: asyncio.Task[None] | None = None
    lease_started: float = 0.0

    def to_record(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "key": self.key,
            "url": self.url,
            "profile": self.profile,
            "intervention_type": self.intervention_type,
            "window": {
                "slot": self.window.slot,
                "x": self.window.x,
                "y": self.window.y,
                "width": self.window.width,
                "height": self.window.height,
            },
            "vnc_url": self.vnc_url,
            "started_at": self.started_at,
            "request_id": self.request_id,
        }

    @classmethod
    def from_record(cls, data: dict[str, Any]) -> NoVNCFlow:
        window = data["window"]

        return cls(
            flow_id=data["flow_id"],
            key=data["key"],
            url=data["url"],
            profile=data["profile"],
            intervention_type=data["intervention_type"],
            window=WindowRect(
                slot=window["slot"],
                x=window["x"],
                y=window["y"],
                width=window["width"],
                height=window["height"],
            ),
            vnc_url=data["vnc_url"],
            started_at=data["started_at"],
            request_id=data["request_id"],
        )


class NoVNCFlowRegistry:
    """Owns this process's window slots and the shared Redis flow records."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._local: dict[str, NoVNCFlow] = {}

    def _client(self) -> Any | None:
        if self._redis is not None:
            return self._redis

        return cookie_manager.redis_client

    def _cap(self) -> int:
        return settings.NOVNC_MAX_CONCURRENT_FLOWS

    def local(self) -> list[NoVNCFlow]:
        """Return the flows this process runs, ordered by start time."""
        return sorted(self._local.values(), key=lambda flow: flow.started_at)

    def is_local(self, flow_id: str) -> bool:
        """Return whether *flow_id* is a flow this process runs."""
        return flow_id in self._local

    async def find(self, key: str) -> NoVNCFlow | None:
        """Return the live flow for *key*, from Redis or, when Redis is
        unreachable, from this process's flows."""
        client = self._client()
        if client is not None:
            try:
                raw = await client.get(_redis_key(key))
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: Redis read failed for key=%s: %s; using process-only flows",
                    key,
                    exc,
                )
                raw = None
            if raw:
                try:
                    return NoVNCFlow.from_record(json.loads(raw))
                except Exception as exc:
                    logger.warning(
                        "NoVNCFlowRegistry: ignoring unreadable record for key=%s: %s",
                        key,
                        exc,
                    )

        for flow in self._local.values():
            if flow.key == key:
                return flow

        return None

    async def reserve(
        self,
        *,
        key: str,
        url: str,
        profile: str,
        intervention_type: str,
    ) -> NoVNCFlow:
        """Take the lowest free local slot and write the flow record.

        Returns the new flow on a won ``SET NX`` write, or the winning flow
        as a join when the write loses to another request. Raises
        ``NoVNCFlowBusyException`` when every local slot is taken.
        """
        cap = self._cap()
        occupied = {flow.window.slot for flow in self._local.values()}
        free = [slot for slot in range(cap) if slot not in occupied]
        if not free:
            oldest = min(self._local.values(), key=lambda flow: flow.started_at)
            locals_by_age = sorted(self._local.values(), key=lambda flow: flow.started_at)
            raise NoVNCFlowBusyException(
                oldest.url,
                oldest.profile,
                active_flows=len(self._local),
                max_concurrent_flows=cap,
                flows=[flow_shape(flow) for flow in locals_by_age],
            )

        slot = free[0]
        window = rect_for_slot(
            slot,
            settings.NOVNC_DISPLAY_SIZE,
            (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
            settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
        )
        flow = NoVNCFlow(
            flow_id=uuid.uuid4().hex[:_FLOW_ID_HEX_LENGTH],
            key=key,
            url=url,
            profile=profile,
            intervention_type=intervention_type,
            window=window,
            vnc_url="",
            started_at=time.time(),
            request_id=get_correlation_id(),
            lease_started=time.monotonic(),
        )

        for _ in range(_RESERVE_ATTEMPTS):
            client = self._client()
            if client is None:
                return self._keep_process_only(flow, slot, key)
            try:
                won = await client.set(
                    _redis_key(flow.key), json.dumps(flow.to_record()), nx=True, px=_lease_ms()
                )
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: Redis write failed for flow_id=%s slot=%s: %s; keeping process-only",
                    flow.flow_id,
                    slot,
                    exc,
                )
                return self._keep_process_only(flow, slot, key)
            if won:
                return self._keep_process_only(flow, slot, key)
            try:
                raw = await client.get(_redis_key(flow.key))
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: Redis read failed for flow_id=%s slot=%s: %s; keeping process-only",
                    flow.flow_id,
                    slot,
                    exc,
                )
                return self._keep_process_only(flow, slot, key)
            if not raw:
                continue
            try:
                return NoVNCFlow.from_record(json.loads(raw))
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: ignoring unreadable record for key=%s: %s",
                    flow.key,
                    exc,
                )
                continue

        raise NoVNCFlowBusyException(url, profile)

    def _keep_process_only(self, flow: NoVNCFlow, slot: int, key: str) -> NoVNCFlow:
        self._local[flow.flow_id] = flow
        NOVNC_ACTIVE_FLOWS.set(len(self._local))
        logger.info(
            "NoVNCFlowRegistry: reserved flow_id=%s slot=%s key=%s request_id=%s",
            flow.flow_id,
            slot,
            key,
            flow.request_id,
        )

        return flow

    def attach_task(self, flow_id: str, task: asyncio.Task[None]) -> None:
        """Bind the monitor task to the local flow record."""
        self._local[flow_id].task = task

    async def set_vnc_url(self, flow_id: str, vnc_url: str) -> bool:
        """Fill in the resolved address on the local flow and its record."""
        flow = self._local.get(flow_id)
        if flow is None:
            return False
        flow.vnc_url = vnc_url
        client = self._client()
        if client is None:
            return True
        remaining_ms = max(1, int((flow.lease_started + _lease_seconds() - time.monotonic()) * 1000))
        try:
            await client.set(_redis_key(flow.key), json.dumps(flow.to_record()), xx=True, px=remaining_ms)
        except Exception as exc:
            logger.warning(
                "NoVNCFlowRegistry: Redis update failed for flow_id=%s slot=%s: %s",
                flow.flow_id,
                flow.window.slot,
                exc,
            )
        return True

    async def release(self, flow_id: str) -> None:
        """Free the local slot and delete the flow's own Redis record.

        Idempotent: releasing an unknown identifier is a no-op, and the
        record is deleted only while it still holds this flow_id.
        """
        flow = self._local.pop(flow_id, None)
        if flow is None:
            return
        NOVNC_ACTIVE_FLOWS.set(len(self._local))
        client = self._client()
        if client is not None:
            try:
                await client.eval(_RELEASE_SCRIPT, 1, _redis_key(flow.key), flow.flow_id)
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: Redis release failed for flow_id=%s slot=%s: %s",
                    flow.flow_id,
                    flow.window.slot,
                    exc,
                )
        logger.info(
            "NoVNCFlowRegistry: released flow_id=%s slot=%s key=%s",
            flow.flow_id,
            flow.window.slot,
            flow.key,
        )

    async def active(self) -> list[NoVNCFlow]:
        """Return the live flows of every container, ordered by start time."""
        client = self._client()
        flows: list[NoVNCFlow] = []
        if client is None:
            return self.local()
        try:
            keys = [key async for key in client.scan_iter(match=f"{NOVNC_FLOW_KEY_PREFIX}*")]
        except Exception as exc:
            logger.warning("NoVNCFlowRegistry: Redis listing failed: %s; using process-only flows", exc)
            return self.local()
        for redis_key in keys:
            try:
                raw = await client.get(redis_key)
            except Exception as exc:
                logger.warning("NoVNCFlowRegistry: Redis read failed: %s; using process-only flows", exc)
                return self.local()
            if not raw:
                continue
            try:
                flows.append(NoVNCFlow.from_record(json.loads(raw)))
            except Exception as exc:
                logger.warning("NoVNCFlowRegistry: ignoring unreadable record: %s", exc)
        flows.sort(key=lambda flow: flow.started_at)

        return flows

    async def sweep(self) -> list[NoVNCFlow]:
        """Cancel every local flow whose lease has expired, freeing its slot."""
        now = time.monotonic()
        lease = _lease_seconds()
        expired = [flow for flow in self._local.values() if now - flow.lease_started >= lease]
        for flow in expired:
            if flow.task is not None and not flow.task.done():
                flow.task.cancel()
            await self.release(flow.flow_id)
            NOVNC_FLOWS_RECLAIMED_TOTAL.labels(reason="lease_expired").inc()
            logger.warning(
                "NoVNCFlowRegistry: reclaimed expired flow_id=%s slot=%s key=%s",
                flow.flow_id,
                flow.window.slot,
                flow.key,
            )

        return expired

    async def shutdown(self) -> None:
        """Cancel every local flow and wait for the teardowns, bounded by
        the cancel grace in total. Flows of other containers are untouched."""
        flows = list(self._local.values())
        tasks = [flow.task for flow in flows if flow.task is not None and not flow.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=settings.NOVNC_FLOW_CANCEL_GRACE_SECONDS)
        for flow in flows:
            if flow.task is not None and not flow.task.done():
                NOVNC_FLOWS_RECLAIMED_TOTAL.labels(reason="cancel_timeout").inc()
                logger.warning(
                    "NoVNCFlowRegistry: orphaned flow_id=%s slot=%s key=%s did not finish its teardown",
                    flow.flow_id,
                    flow.window.slot,
                    flow.key,
                )
            else:
                NOVNC_FLOWS_RECLAIMED_TOTAL.labels(reason="shutdown").inc()
            await self.release(flow.flow_id)


novnc_flow_registry = NoVNCFlowRegistry()
