from ascend_python_common.readiness import ProbeResult

from src.config.config import settings
from src.observability.metrics import is_engine_warm
from src.service.job_service import job_runner
from src.service.ocr_service import is_accepting_work


def probe_engine() -> ProbeResult:
    warm = is_engine_warm(settings.DEFAULT_LANGUAGE)
    return ProbeResult(status="ok" if warm else "error", details={"warm": str(warm).lower()})


def probe_worker_pool() -> ProbeResult:
    accepting = is_accepting_work()
    return ProbeResult(
        status="ok" if accepting else "error",
        details={"accepting_work": str(accepting).lower()},
    )


def probe_jobs() -> ProbeResult:
    return ProbeResult(
        status="ok",
        details={
            "queued": str(job_runner.documents_waiting()),
            "running": str(job_runner.documents_running()),
        },
    )
