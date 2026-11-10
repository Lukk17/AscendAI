"""Per-container slot registry with the flow records in Redis.

Each ascend-web-hunter container owns its display, so the slot pool, the
browsers and the monitor tasks live in the process. What every container
must agree on is which key has a live flow, so each live flow also has a
record in Redis under ``novnc_flow:{registrable_domain}:{profile}``,
written with ``SET NX PX`` for the flow's lease and deleted on release by
a compare-and-delete script, so a flow never deletes a record a later
flow wrote. A record nobody can read is taken over by a compare-and-set
script that replaces it only while it still holds the bytes the taker read.

A Redis error never fails the caller: the flow is kept in the process
only, which is the behaviour of a single container, so a join then works
only inside the same container until Redis answers again.

A flow is closed by its flow_id on any container. The owner cancels its
monitor at once. Another container deletes the record and writes
``novnc_flow_cancel:{flow_id}``, which the owner's monitor reads on its next
poll. Every finished window leaves its result under
``novnc_window_result:{registrable_domain}:{profile}`` for as long as a saved
login lives, so the session status can name how the last window ended.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ascend_python_common.request_context import get_correlation_id

from src.api.exceptions import NoVNCFlowBusyException, NoVNCFlowNotFoundError
from src.config.config import settings
from src.observability.metrics import NOVNC_ACTIVE_FLOWS, NOVNC_FLOWS_RECLAIMED_TOTAL
from src.observability.safe_address import address_without_query
from src.reader.cloudflare.cookie_manager import CookieManager, cookie_manager
from src.reader.novnc.window_layout import WindowRect, rect_for_slot

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

NOVNC_FLOW_KEY_PREFIX = "novnc_flow:"

NOVNC_FLOW_CANCEL_KEY_PREFIX = "novnc_flow_cancel:"

NOVNC_WINDOW_RESULT_KEY_PREFIX = "novnc_window_result:"

CANCELLED_OUTCOME = "cancelled"

_FLOW_ID_HEX_LENGTH = 12

_RESERVE_ATTEMPTS = 3

_RELEASE_SCRIPT = (
    "local raw = redis.call('GET', KEYS[1]) "
    "if raw and cjson.decode(raw)['flow_id'] == ARGV[1] "
    "then return redis.call('DEL', KEYS[1]) "
    "else return 0 end"
)

_TAKEOVER_SCRIPT = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] "
    "then redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3]) return 1 "
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


def _remaining_lease_ms(flow: NoVNCFlow) -> int:
    return max(1, int((flow.lease_started + _lease_seconds() - time.monotonic()) * 1000))


def _remaining_record_ms(flow: NoVNCFlow) -> int:
    return max(1, int((flow.started_at + _lease_seconds() - time.time()) * 1000))


def _result_lifetime_seconds() -> int:
    return settings.SESSION_AUTH_TTL_SECONDS


@dataclass(frozen=True, slots=True)
class WindowResult:
    """How one intervention window ended."""

    flow_id: str
    intervention_type: str
    outcome: str
    finished_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "flow_id": self.flow_id,
            "intervention_type": self.intervention_type,
            "outcome": self.outcome,
            "finished_at": self.finished_at,
        }

    def is_current(self, now: float) -> bool:
        return now - self.finished_at < _result_lifetime_seconds()


def flow_shape(flow: NoVNCFlow, now: float | None = None) -> dict[str, Any]:
    """The single flow shape shared by the 409 body and the listing."""
    at = time.time() if now is None else now

    return {
        "flow_id": flow.flow_id,
        "url": address_without_query(flow.url),
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

    `task`, `lease_started` and `settled` exist in the owning process only
    and are never written to Redis. `settled` is set once a reservation has
    either published its record or been abandoned.
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
    settled: asyncio.Event = field(default_factory=asyncio.Event, compare=False, repr=False)

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
        self._local_results: dict[str, WindowResult] = {}
        self._results_missing_from_redis: set[str] = set()

    def _client(self) -> Any | None:
        if self._redis is not None:
            return self._redis

        return cookie_manager.redis_client

    def _cap(self) -> int:
        return settings.NOVNC_MAX_CONCURRENT_FLOWS

    def local(self) -> list[NoVNCFlow]:
        """Return the flows this process runs, ordered by start time."""
        return sorted(self._local.values(), key=lambda flow: flow.started_at)

    def owns(self, flow: NoVNCFlow) -> bool:
        """Return whether *flow* is the very flow this process runs.

        A join always answers a copy, so a caller that joined never owns
        the flow it was given, even when the owner runs in this process.
        """
        return self._local.get(flow.flow_id) is flow

    def _local_flow_for(self, key: str) -> NoVNCFlow | None:
        return next((flow for flow in self._local.values() if flow.key == key), None)

    async def _join_local(self, flow: NoVNCFlow) -> NoVNCFlow | None:
        await flow.settled.wait()
        if not self.owns(flow):
            return None

        return NoVNCFlow.from_record(flow.to_record())

    async def find(self, key: str) -> NoVNCFlow | None:
        """Return the live flow for *key*, from Redis or, when Redis holds
        none, from this process's flows once their address is published."""
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

        local = self._local_flow_for(key)
        if local is None:
            return None

        return await self._join_local(local)

    async def reserve(
        self,
        *,
        key: str,
        url: str,
        profile: str,
        intervention_type: str,
        resolve_vnc_url: Callable[[NoVNCFlow], Awaitable[str]] | None = None,
    ) -> NoVNCFlow:
        """Take the lowest free local slot, resolve the address, then publish.

        The slot is taken before any await, and the record is written with
        ``SET NX`` only once it carries its address. Returns the new flow,
        or a copy of the winning flow as a join (see `owns`).

        Raises:
            NoVNCFlowBusyException: when every local slot is taken.
        """
        pending = self._local_flow_for(key)
        if pending is not None:
            joined = await self._join_local(pending)
            if joined is not None:
                return joined

            return await self.reserve(
                key=key,
                url=url,
                profile=profile,
                intervention_type=intervention_type,
                resolve_vnc_url=resolve_vnc_url,
            )

        flow = self._take_slot(key, url, profile, intervention_type)
        try:
            return await self._publish(flow, resolve_vnc_url)
        except BaseException:
            self._abandon(flow)
            raise
        finally:
            flow.settled.set()

    def _take_slot(self, key: str, url: str, profile: str, intervention_type: str) -> NoVNCFlow:
        cap = self._cap()
        occupied = {flow.window.slot for flow in self._local.values()}
        free = [slot for slot in range(cap) if slot not in occupied]
        if not free:
            locals_by_age = self.local()
            oldest = locals_by_age[0]
            raise NoVNCFlowBusyException(
                address_without_query(oldest.url),
                oldest.profile,
                active_flows=len(self._local),
                max_concurrent_flows=cap,
                flows=[flow_shape(flow) for flow in locals_by_age],
            )

        window = rect_for_slot(
            free[0],
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
        self._local[flow.flow_id] = flow

        return flow

    def _abandon(self, flow: NoVNCFlow) -> None:
        if self.owns(flow):
            del self._local[flow.flow_id]

    async def _publish(
        self,
        flow: NoVNCFlow,
        resolve_vnc_url: Callable[[NoVNCFlow], Awaitable[str]] | None,
    ) -> NoVNCFlow:
        if resolve_vnc_url is not None:
            try:
                flow.vnc_url = await resolve_vnc_url(flow)
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: VNC resolution failed for flow_id=%s slot=%s: %s",
                    flow.flow_id,
                    flow.window.slot,
                    exc,
                )
                raise
        record = json.dumps(flow.to_record())
        redis_key = _redis_key(flow.key)

        for _ in range(_RESERVE_ATTEMPTS):
            client = self._client()
            if client is None:
                return self._keep(flow)
            try:
                won = await client.set(redis_key, record, nx=True, px=_remaining_lease_ms(flow))
                if won:
                    return self._keep(flow)
                raw = await client.get(redis_key)
                if not raw:
                    continue
                winner = self._readable(raw, flow)
                if winner is not None:
                    self._abandon(flow)

                    return winner
                if await client.eval(_TAKEOVER_SCRIPT, 1, redis_key, raw, record, _remaining_lease_ms(flow)):
                    return self._keep(flow)
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: Redis reservation failed for flow_id=%s slot=%s: %s, "
                    "keeping process-only",
                    flow.flow_id,
                    flow.window.slot,
                    exc,
                )

                return self._keep(flow)

        logger.warning(
            "NoVNCFlowRegistry: flow record for flow_id=%s slot=%s kept changing; keeping process-only",
            flow.flow_id,
            flow.window.slot,
        )

        return self._keep(flow)

    @staticmethod
    def _readable(raw: str, flow: NoVNCFlow) -> NoVNCFlow | None:
        try:
            return NoVNCFlow.from_record(json.loads(raw))
        except Exception as exc:
            logger.warning(
                "NoVNCFlowRegistry: taking over unreadable record for key=%s flow_id=%s slot=%s: %s",
                flow.key,
                flow.flow_id,
                flow.window.slot,
                exc,
            )

            return None

    def _keep(self, flow: NoVNCFlow) -> NoVNCFlow:
        NOVNC_ACTIVE_FLOWS.set(len(self._local))
        logger.info(
            "NoVNCFlowRegistry: reserved flow_id=%s slot=%s key=%s request_id=%s",
            flow.flow_id,
            flow.window.slot,
            flow.key,
            flow.request_id,
        )

        return flow

    def attach_task(self, flow_id: str, task: asyncio.Task[None]) -> None:
        """Bind the monitor task to the local flow record."""
        self._local[flow_id].task = task

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

    async def finish(self, flow: NoVNCFlow, outcome: str) -> None:
        """Record how *flow*'s window ended, then free its slot and record."""
        try:
            await self._record_result(flow, outcome)
        finally:
            await self.release(flow.flow_id)

    async def _record_result(self, flow: NoVNCFlow, outcome: str) -> None:
        result = WindowResult(
            flow_id=flow.flow_id,
            intervention_type=flow.intervention_type,
            outcome=outcome,
            finished_at=time.time(),
        )
        self._local_results[flow.key] = result
        client = self._client()
        if client is None:
            return
        try:
            await client.set(
                f"{NOVNC_WINDOW_RESULT_KEY_PREFIX}{flow.key}",
                json.dumps(result.to_dict()),
                px=_result_lifetime_seconds() * 1000,
            )
        except Exception as exc:
            self._results_missing_from_redis.add(flow.key)
            logger.warning(
                "NoVNCFlowRegistry: Redis write of the window result failed for flow_id=%s: %s; "
                "keeping it process-only",
                flow.flow_id,
                exc,
            )

            return
        self._results_missing_from_redis.discard(flow.key)

    async def last_result(self, key: str) -> WindowResult | None:
        """Return how the last window for *key* ended, or None.

        Redis is the record whenever it answers, so a deleted key answers None.
        The process copy is read without Redis, when the Redis read fails, and
        while it is current for a key whose last Redis write failed.
        """
        if key in self._results_missing_from_redis:
            unwritten = self._current_local_result(key)
            if unwritten is not None:
                return unwritten
            self._results_missing_from_redis.discard(key)
        client = self._client()
        if client is not None:
            try:
                raw = await client.get(f"{NOVNC_WINDOW_RESULT_KEY_PREFIX}{key}")
                if raw is None:
                    self._local_results.pop(key, None)

                    return None

                return WindowResult(**json.loads(raw))
            except Exception as exc:
                logger.warning(
                    "NoVNCFlowRegistry: window result for key=%s unreadable: %s; using the process copy",
                    key,
                    exc,
                )

        return self._current_local_result(key)

    def _current_local_result(self, key: str) -> WindowResult | None:
        local = self._local_results.get(key)
        if local is None:
            return None
        if not local.is_current(time.time()):
            del self._local_results[key]

            return None

        return local

    async def cancel(self, flow_id: str) -> None:
        """Close the window of *flow_id* without saving anything from it.

        A flow of this process has its monitor cancelled and its slot freed
        before this returns. A flow of another container loses its record at
        once and is closed by its owner on the owner's next poll.

        Raises:
            NoVNCFlowNotFoundError: when no open window carries *flow_id*.
        """
        local = self._local.get(flow_id)
        if local is not None:
            await local.settled.wait()
            local = self._local.get(flow_id)
        if local is not None:
            await self._cancel_local(local)

            return
        remote = next((flow for flow in await self.active() if flow.flow_id == flow_id), None)
        if remote is None:
            raise NoVNCFlowNotFoundError(flow_id)
        await self._cancel_remote(remote)

    async def _cancel_local(self, flow: NoVNCFlow) -> None:
        await self._cancel_within_grace([flow])
        if flow.task is None or not flow.task.done():
            await self.finish(flow, CANCELLED_OUTCOME)
        logger.info(
            "NoVNCFlowRegistry: cancelled flow_id=%s slot=%s key=%s",
            flow.flow_id,
            flow.window.slot,
            flow.key,
        )

    async def _cancel_remote(self, flow: NoVNCFlow) -> None:
        client = self._client()
        assert client is not None
        await client.set(f"{NOVNC_FLOW_CANCEL_KEY_PREFIX}{flow.flow_id}", "1", px=_remaining_record_ms(flow))
        await client.eval(_RELEASE_SCRIPT, 1, _redis_key(flow.key), flow.flow_id)
        await self._record_result(flow, CANCELLED_OUTCOME)
        logger.info(
            "NoVNCFlowRegistry: asked the owner to close flow_id=%s slot=%s key=%s",
            flow.flow_id,
            flow.window.slot,
            flow.key,
        )

    async def cancel_requested(self, flow_id: str) -> bool:
        """Return whether another container asked to close *flow_id*."""
        client = self._client()
        if client is None:
            return False
        try:
            return bool(await client.get(f"{NOVNC_FLOW_CANCEL_KEY_PREFIX}{flow_id}"))
        except Exception as exc:
            logger.warning("NoVNCFlowRegistry: Redis cancel check failed for flow_id=%s: %s", flow_id, exc)

            return False

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
        """Cancel every local flow whose lease has expired, wait up to the
        cancel grace for their teardowns, then free their slots."""
        now = time.monotonic()
        lease = _lease_seconds()
        expired = [flow for flow in self._local.values() if now - flow.lease_started >= lease]
        await self._cancel_within_grace(expired)
        for flow in expired:
            reason = "cancel_timeout" if self._teardown_unfinished(flow) else "lease_expired"
            await self.release(flow.flow_id)
            NOVNC_FLOWS_RECLAIMED_TOTAL.labels(reason=reason).inc()
            logger.warning(
                "NoVNCFlowRegistry: reclaimed expired flow_id=%s slot=%s key=%s",
                flow.flow_id,
                flow.window.slot,
                flow.key,
            )

        return expired

    @staticmethod
    async def _cancel_within_grace(flows: list[NoVNCFlow]) -> None:
        tasks = [flow.task for flow in flows if flow.task is not None and not flow.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=settings.NOVNC_FLOW_CANCEL_GRACE_SECONDS)

    @staticmethod
    def _teardown_unfinished(flow: NoVNCFlow) -> bool:
        if flow.task is None or flow.task.done():
            return False
        logger.warning(
            "NoVNCFlowRegistry: orphaned flow_id=%s slot=%s key=%s did not finish its teardown",
            flow.flow_id,
            flow.window.slot,
            flow.key,
        )

        return True

    async def shutdown(self) -> None:
        """Cancel every local flow and wait for the teardowns, bounded by
        the cancel grace in total. Flows of other containers are untouched."""
        flows = list(self._local.values())
        await self._cancel_within_grace(flows)
        for flow in flows:
            reason = "cancel_timeout" if self._teardown_unfinished(flow) else "shutdown"
            NOVNC_FLOWS_RECLAIMED_TOTAL.labels(reason=reason).inc()
            await self.release(flow.flow_id)


novnc_flow_registry = NoVNCFlowRegistry()
