import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
import uvicorn
from pact import Verifier

from src.api.middleware.rate_limit import limiter
from src.config.config import settings
from src.main import create_app
from src.model.ocr_models import JobRecord, JobResultLocation
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore
from tests.conftest import FakeResultStore, make_record

pytestmark = [
    pytest.mark.contract,
    pytest.mark.filterwarnings(
        r"ignore:Exception ignored in. <socket\.socket .*laddr=\('127\.0\.0\.1':pytest.PytestUnraisableExceptionWarning"
    ),
]

PROVIDER: Final = "ascend-ocr"
CONSUMER: Final = "ascend-agent"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[4]
PACT_FILE: Final = REPOSITORY_ROOT / "contracts" / "pacts" / f"{CONSUMER}-{PROVIDER}.json"

LOOPBACK: Final = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS: Final = 10.0
STARTUP_POLL_SECONDS: Final = 0.05
SHUTDOWN_TIMEOUT_SECONDS: Final = 10.0

SETUP: Final = "setup"
RESULT_BUCKET: Final = "ocr-results"
PROCESSING_TIME_SECONDS: Final = 1.0
FAILURE_DETAIL: Final = "The engine could not read the document"
PACT_DO_NOT_TRACK: Final = "PACT_DO_NOT_TRACK"

StateParameters = dict[str, object] | None
StateHandler = Callable[[str, StateParameters], None]


@dataclass(frozen=True)
class JobPath:
    store: JobStore
    runner: JobRunner


Seed = Callable[[JobPath, StateParameters], None]


class ProviderStates:
    """Puts the job path into the state an interaction names, over a fresh store every time."""

    def __init__(self, jobs_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._jobs_root = jobs_root
        self._monkeypatch = monkeypatch
        self._generation = 0
        self.reset()

    def reset(self) -> JobPath:
        self._generation += 1
        self._monkeypatch.setattr(settings, "OCR_JOBS_DIR", str(self._jobs_root / f"state-{self._generation}"))

        results = FakeResultStore()
        store = JobStore(results)
        runner = JobRunner(store, results)
        self._monkeypatch.setattr("src.api.rest.rest_endpoints.job_service", JobService(store, results, runner))
        limiter.reset()

        return JobPath(store, runner)

    def handlers(self) -> dict[str, StateHandler]:
        return {
            "": self._without_state,
            "the queue has room": self._state(_seed_nothing),
            "the queue is full": self._state(_seed_full_queue),
            "job {jobId} is waiting": self._state(_seed_waiting),
            "job {jobId} is running": self._state(_seed_running),
            "job {jobId} has succeeded": self._state(_seed_succeeded),
            "job {jobId} has failed": self._state(_seed_failed),
            "job {jobId} was cancelled": self._state(_seed_cancelled),
            "no job {jobId} exists": self._state(_seed_nothing),
        }

    def _without_state(self, action: str, parameters: StateParameters) -> None:
        _ = parameters
        if action != SETUP:
            self.reset()

    def _state(self, seed: Seed) -> StateHandler:
        def handle(action: str, parameters: StateParameters) -> None:
            path = self.reset()
            if action == SETUP:
                seed(path, parameters)

        return handle


def _parameter(parameters: StateParameters, name: str) -> str:
    value = (parameters or {}).get(name)
    if not isinstance(value, str):
        raise ValueError(f"Provider state parameter {name!r} is missing or not a string: {value!r}")

    return value


def _admit_waiting(path: JobPath, record: JobRecord) -> None:
    path.store.write(record)
    path.runner.admit(record)


def _write_running(path: JobPath, parameters: StateParameters) -> JobRecord:
    record = make_record(job_id=_parameter(parameters, "jobId"), state="running", started_at=time.time())
    path.store.write(record)

    return record


def _seed_nothing(path: JobPath, parameters: StateParameters) -> None:
    _ = path, parameters


def _seed_full_queue(path: JobPath, parameters: StateParameters) -> None:
    _ = parameters
    for _index in range(settings.OCR_JOB_QUEUE_MAX_DOCUMENTS):
        _admit_waiting(path, make_record())


def _seed_waiting(path: JobPath, parameters: StateParameters) -> None:
    _admit_waiting(path, make_record(job_id=_parameter(parameters, "jobId")))


def _seed_running(path: JobPath, parameters: StateParameters) -> None:
    _write_running(path, parameters)


def _seed_succeeded(path: JobPath, parameters: StateParameters) -> None:
    record = _write_running(path, parameters)
    location = JobResultLocation(bucket=RESULT_BUCKET, key=f"{record.job_id}.md")
    path.store.succeed(record, location, PROCESSING_TIME_SECONDS)


def _seed_failed(path: JobPath, parameters: StateParameters) -> None:
    record = _write_running(path, parameters)
    path.store.fail(record, _parameter(parameters, "errorCode"), FAILURE_DETAIL)


def _seed_cancelled(path: JobPath, parameters: StateParameters) -> None:
    record = make_record(job_id=_parameter(parameters, "jobId"))
    path.store.write(record)
    path.store.cancel(record)


def _wait_until_started(server: uvicorn.Server, thread: threading.Thread) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while not server.started:
        if not thread.is_alive():
            pytest.fail("The provider server stopped before it started accepting connections")

        if time.monotonic() > deadline:
            pytest.fail(f"The provider server did not start within {STARTUP_TIMEOUT_SECONDS} seconds")

        time.sleep(STARTUP_POLL_SECONDS)


def _verification_failure(verifier: Verifier) -> str | None:
    try:
        verifier.verify()
    except RuntimeError:
        return verifier.output(strip_ansi=True)

    return None


@pytest.fixture
def provider_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProviderStates:
    return ProviderStates(tmp_path / "jobs", monkeypatch)


@pytest.fixture
def provider_url(provider_states: ProviderStates) -> Iterator[str]:
    _ = provider_states
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((LOOPBACK, 0))
    port = listener.getsockname()[1]

    config = uvicorn.Config(create_app(), host=LOOPBACK, port=port, lifespan="off", ws="none", log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, name="pact-provider", daemon=True)
    thread.start()

    try:
        _wait_until_started(server, thread)

        yield f"http://{LOOPBACK}:{port}"
    finally:
        server.should_exit = True
        thread.join(SHUTDOWN_TIMEOUT_SECONDS)
        listener.close()


def test_provider_honours_every_interaction_the_agent_recorded(
    provider_url: str, provider_states: ProviderStates, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    if not PACT_FILE.is_file():
        pytest.fail(f"No pact file at {PACT_FILE}. The ascend-agent consumer contract tests write it.")

    monkeypatch.setenv(PACT_DO_NOT_TRACK, "true")

    verifier = (
        Verifier(PROVIDER, host=LOOPBACK)
        .add_transport(url=provider_url)
        .filter_consumers(CONSUMER)
        .add_source(PACT_FILE)
        .state_handler(provider_states.handlers(), teardown=True)
        .set_error_on_empty_pact(enabled=True)
    )

    # When
    failure = _verification_failure(verifier)

    # Then
    assert failure is None, f"Provider verification failed:\n{failure}"
