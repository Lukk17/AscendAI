from pathlib import Path

_CGROUP_V2_MEMORY_MAX_PATH = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_MEMORY_LIMIT_PATH = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_V2_UNLIMITED = "max"
# cgroup v1 reports "no limit" as an implementation-specific huge number (commonly
# 2^63 rounded down to the page size) rather than a sentinel string. No real container
# is ever configured with an exabyte-scale limit, so any value at or above this floor
# means "unlimited", not "the actual ceiling".
_CGROUP_V1_UNLIMITED_FLOOR_BYTES = 1 << 62
_BYTES_PER_MIB = 1024 * 1024


def detect_memory_limit_mib() -> float | None:
    """Return this container's own cgroup memory ceiling in MiB, or None if unreadable or unlimited.

    Mirrors `detect_cpu_limit()` in `cpu_limits.py`: read the cgroup filesystem
    directly, since that is the only place this process's own ceiling is recorded.
    Unlike the CPU limit, there is no meaningful fallback to substitute when this
    reads as unlimited or unreadable — `os.cpu_count()` has an obvious host-wide
    meaning to fall back to, but there is no host-memory figure that is safe to
    compare a single container's own budget against, so both cases return None
    ("unknown") rather than a guessed number.
    """
    limit_bytes = _read_cgroup_v2_memory_limit() or _read_cgroup_v1_memory_limit()
    if limit_bytes is None:
        return None

    return limit_bytes / _BYTES_PER_MIB


def _read_cgroup_v2_memory_limit() -> int | None:
    try:
        raw = _CGROUP_V2_MEMORY_MAX_PATH.read_text().strip()
    except OSError:
        return None

    if raw == _CGROUP_V2_UNLIMITED:
        return None

    try:
        return int(raw)
    except ValueError:
        return None


def _read_cgroup_v1_memory_limit() -> int | None:
    try:
        raw = _CGROUP_V1_MEMORY_LIMIT_PATH.read_text().strip()
    except OSError:
        return None

    try:
        limit_bytes = int(raw)
    except ValueError:
        return None

    if limit_bytes >= _CGROUP_V1_UNLIMITED_FLOOR_BYTES:
        return None

    return limit_bytes
