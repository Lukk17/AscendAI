import os
from pathlib import Path

import cv2

from src.config.logging_config import get_logger

logger = get_logger(__name__)

_CGROUP_V2_MAX_PATH = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_QUOTA_PATH = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_PERIOD_PATH = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
_CGROUP_V2_UNLIMITED = "max"
_CGROUP_V1_UNLIMITED = -1


def detect_cpu_limit() -> int:
    """Return the number of CPUs this process may actually use.

    `os.cpu_count()` reports every core on the host, not the CFS quota Docker's `--cpus`
    (and the compose `deploy.resources.limits.cpus` equivalent) enforces, so it overstates
    capacity inside a throttled container: `nproc` keeps reporting the host's full core
    count regardless of the quota. Reading the quota straight from the cgroup filesystem
    keeps the result correct even if that limit changes later.
    """
    limit = _read_cgroup_v2_limit() or _read_cgroup_v1_limit()
    if limit is not None:
        return limit

    return os.cpu_count() or 1


def _read_cgroup_v2_limit() -> int | None:
    try:
        quota_str, period_str = _CGROUP_V2_MAX_PATH.read_text().split()
    except (OSError, ValueError):
        return None

    if quota_str == _CGROUP_V2_UNLIMITED:
        return None

    return _quota_to_cpus(int(quota_str), int(period_str))


def _read_cgroup_v1_limit() -> int | None:
    try:
        quota = int(_CGROUP_V1_QUOTA_PATH.read_text().strip())
        period = int(_CGROUP_V1_PERIOD_PATH.read_text().strip())
    except (OSError, ValueError):
        return None

    if quota == _CGROUP_V1_UNLIMITED:
        return None

    return _quota_to_cpus(quota, period)


def _quota_to_cpus(quota_us: int, period_us: int) -> int:
    return max(1, quota_us // period_us)


def apply_cpu_thread_limit() -> int:
    """Cap OpenCV's thread pool to the container's real CPU budget and return that budget.

    OpenCV's parallel_for_ backend defaults cv2.getNumThreads() to os.cpu_count() and does
    not honour its own OPENCV_NUM_THREADS env var (verified empirically, not documented).
    Paddle is capped separately, per engine, by build_engine passing cpu_threads: PaddleOCR
    always passes its own default of 10 to paddlex, so PADDLE_PDX_CPU_NUM_THREADS never
    reaches the inference graph and is deliberately not set here.
    """
    cpu_limit = detect_cpu_limit()
    cv2.setNumThreads(cpu_limit)

    logger.info("Capped OpenCV's thread pool to %d CPU(s)", cpu_limit)

    return cpu_limit
