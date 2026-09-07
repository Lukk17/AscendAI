import os
import tempfile
from pathlib import Path

# prometheus_client decides, once, whether to back every Counter/Histogram with its
# multiprocess-safe (mmap-file) value class or an in-memory one: it reads
# PROMETHEUS_MULTIPROC_DIR from os.environ the moment prometheus_client.values is first
# imported in a process (see get_value_class() there), before any metric object exists.
# OCR inference runs in a ProcessPoolExecutor worker started with the "spawn" context
# (see service/ocr_service.py), a fresh interpreter with its own copy of every metric
# object, so counters incremented there (for example the engine cache eviction counter)
# never reach the main process's registry and the /metrics endpoint never moves.
#
# Tracing solved the same fresh-interpreter problem by having each process push its own
# spans straight to the OTLP collector (configure_worker_tracing, called from the pool
# initializer). That approach can't be reused here: by the time the pool initializer
# runs, src.observability.metrics has already been imported and its Counter/Histogram
# objects already constructed, using whatever value class prometheus_client picked at
# that point. The package __init__ is the earliest point common to both the main
# process and every worker, since Python always executes it before any src.* submodule,
# so the env var is set here, before anything under src/ can import prometheus_client.
# The main process's /metrics endpoint (see main.py, via prometheus-fastapi-
# instrumentator) then merges every process's own file in this directory at scrape time.
_PROMETHEUS_MULTIPROC_DIR = Path(tempfile.gettempdir()) / "ascendocr_prometheus_multiproc"
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", str(_PROMETHEUS_MULTIPROC_DIR))
Path(os.environ["PROMETHEUS_MULTIPROC_DIR"]).mkdir(parents=True, exist_ok=True)
