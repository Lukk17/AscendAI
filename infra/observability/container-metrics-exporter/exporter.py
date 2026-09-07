"""Prometheus exporter for per-container memory usage vs. configured limit.

Reads only the Docker Engine API over the Docker socket (/containers/json,
/containers/{id}/stats, /containers/{id}/json). Never reads image or
graph-driver metadata, so it works the same regardless of which storage
driver or snapshotter backs the Docker daemon.
"""

import datetime
import http.client
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily

DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
LISTEN_PORT = int(os.environ.get("EXPORTER_PORT", "8080"))
REQUEST_TIMEOUT_SECONDS = 10
# Docker's non-streaming stats endpoint samples two cgroup reads roughly a
# second apart before it replies, so one call costs ~1-2s no matter how
# small the container is. Fetched in parallel, one thread per container, so
# the whole scrape costs one slow call, not container_count slow calls.
MAX_PARALLEL_FETCHES = 32


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection over a Unix domain socket instead of TCP."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


def _docker_get(path: str) -> Any:
    conn = UnixSocketHTTPConnection(DOCKER_SOCKET, REQUEST_TIMEOUT_SECONDS)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"Docker API {path} returned {response.status}: {body!r}")
        return json.loads(body)
    finally:
        conn.close()


def _working_set_bytes(memory_stats: dict[str, Any]) -> int:
    """Approximate cAdvisor's working_set_bytes: usage minus reclaimable page cache."""
    usage = memory_stats.get("usage", 0)
    stats = memory_stats.get("stats", {})
    inactive_file = stats.get("inactive_file")
    if inactive_file is None:
        inactive_file = stats.get("total_inactive_file")
    if inactive_file is None:
        inactive_file = stats.get("cache", 0)
    return max(usage - inactive_file, 0)


def _start_time_seconds(started_at: str) -> float:
    parsed = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return parsed.timestamp()


def _fetch_container_metrics(container: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Fetch stats + inspect for one container. Runs in a worker thread."""
    container_id = container.get("Id", "")
    names = container.get("Names") or []
    name = names[0].lstrip("/") if names else container_id[:12]
    short_id = container_id[:12]

    try:
        stats = _docker_get(f"/containers/{container_id}/stats?stream=false")
        inspect = _docker_get(f"/containers/{container_id}/json")
        return name, short_id, stats, inspect, None
    except (OSError, RuntimeError, ValueError) as exc:
        return name, short_id, None, None, str(exc)


class ContainerMemoryCollector:
    """Collects memory usage, memory limit and start time for every running container."""

    def collect(self):
        memory_used = GaugeMetricFamily(
            "container_memory_used_bytes",
            "Container memory usage with reclaimable page cache subtracted "
            "(working-set style), read from the Docker Engine API stats endpoint.",
            labels=["name", "id"],
        )
        memory_limit = GaugeMetricFamily(
            "container_memory_limit_bytes",
            "Container memory limit (deploy.resources.limits.memory), read from the "
            "Docker Engine API stats endpoint. Containers without a configured limit "
            "report the host's total memory here.",
            labels=["name", "id"],
        )
        start_time = GaugeMetricFamily(
            "container_start_time_seconds",
            "Unix timestamp of the container's last start, from the Docker Engine API.",
            labels=["name", "id"],
        )

        try:
            containers = _docker_get("/containers/json")
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"ERROR: failed to list containers: {exc}", flush=True)
            return

        worker_count = min(MAX_PARALLEL_FETCHES, max(len(containers), 1))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(_fetch_container_metrics, containers))

        for name, short_id, stats, inspect, error in results:
            if error is not None:
                print(f"ERROR: failed to read stats for {name}: {error}", flush=True)
                continue

            memory_stats = stats.get("memory_stats", {})
            if memory_stats.get("usage") is not None:
                memory_used.add_metric([name, short_id], _working_set_bytes(memory_stats))
                memory_limit.add_metric([name, short_id], memory_stats.get("limit", 0))

            started_at = inspect.get("State", {}).get("StartedAt", "")
            if started_at and not started_at.startswith("0001-01-01"):
                start_time.add_metric([name, short_id], _start_time_seconds(started_at))

        yield memory_used
        yield memory_limit
        yield start_time


def main() -> None:
    REGISTRY.register(ContainerMemoryCollector())
    start_http_server(LISTEN_PORT)
    print(
        f"INFO: container-metrics-exporter listening on :{LISTEN_PORT}, "
        f"reading {DOCKER_SOCKET}",
        flush=True,
    )
    threading.Event().wait()


if __name__ == "__main__":
    main()
