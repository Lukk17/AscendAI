from prometheus_client import generate_latest

from src.observability import metrics


def test_counters_registered_with_provider_and_outcome_labels():
    for counter in (
        metrics.MEMORY_INSERT_TOTAL,
        metrics.MEMORY_SEARCH_TOTAL,
        metrics.MEMORY_DELETE_TOTAL,
        metrics.MEMORY_WIPE_TOTAL,
    ):
        counter.labels(provider="lmstudio", outcome="success").inc()

    payload = generate_latest().decode()
    for name in (
        "memory_insert_total",
        "memory_search_total",
        "memory_delete_total",
        "memory_wipe_total",
    ):
        assert name in payload


def test_histograms_registered_with_provider_label():
    for histogram in (
        metrics.MEMORY_INSERT_DURATION_SECONDS,
        metrics.MEMORY_SEARCH_DURATION_SECONDS,
        metrics.MEMORY_DELETE_DURATION_SECONDS,
        metrics.MEMORY_WIPE_DURATION_SECONDS,
    ):
        histogram.labels(provider="lmstudio").observe(0.1)

    payload = generate_latest().decode()
    for name in (
        "memory_insert_duration_seconds",
        "memory_search_duration_seconds",
        "memory_delete_duration_seconds",
        "memory_wipe_duration_seconds",
    ):
        assert name in payload
