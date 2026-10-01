from prometheus_client import generate_latest

from src.observability import metrics


def test_counters_registered_with_provider_and_outcome_labels() -> None:
    # given
    for counter in (
        metrics.MEMORY_INSERT_TOTAL,
        metrics.MEMORY_SEARCH_TOTAL,
        metrics.MEMORY_DELETE_TOTAL,
        metrics.MEMORY_WIPE_TOTAL,
    ):
        counter.labels(provider="lmstudio", outcome="success").inc()

    # when
    payload = generate_latest().decode()

    # then
    for name in (
        "memory_insert_total",
        "memory_search_total",
        "memory_delete_total",
        "memory_wipe_total",
    ):
        assert name in payload


def test_histograms_registered_with_provider_label() -> None:
    # given
    for histogram in (
        metrics.MEMORY_INSERT_DURATION_SECONDS,
        metrics.MEMORY_SEARCH_DURATION_SECONDS,
        metrics.MEMORY_DELETE_DURATION_SECONDS,
        metrics.MEMORY_WIPE_DURATION_SECONDS,
    ):
        histogram.labels(provider="lmstudio").observe(0.1)

    # when
    payload = generate_latest().decode()

    # then
    for name in (
        "memory_insert_duration_seconds",
        "memory_search_duration_seconds",
        "memory_delete_duration_seconds",
        "memory_wipe_duration_seconds",
    ):
        assert name in payload
