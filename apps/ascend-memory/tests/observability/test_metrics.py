from prometheus_client import generate_latest

from src.observability import metrics


def test_counter_registered_with_operation_and_outcome_labels() -> None:
    # given
    for operation in ("insert", "search", "delete", "wipe"):
        for outcome in ("ok", "error", "timeout", "rate_limited", "not_found"):
            metrics.MEMORY_OPERATIONS_TOTAL.labels(operation=operation, outcome=outcome).inc()

    # when
    payload = generate_latest().decode()

    # then
    assert "memory_operations_total" in payload
    for operation in ("insert", "search", "delete", "wipe"):
        for outcome in ("ok", "error", "timeout", "rate_limited", "not_found"):
            assert f'memory_operations_total{{operation="{operation}",outcome="{outcome}"}}' in payload


def test_search_histogram_registered_with_embedding_provider_label() -> None:
    # given
    metrics.MEMORY_SEARCH_DURATION_SECONDS.labels(embedding_provider="openai").observe(0.1)

    # when
    payload = generate_latest().decode()

    # then
    assert "memory_search_duration_seconds" in payload
    assert 'memory_search_duration_seconds_bucket{embedding_provider="openai"' in payload


def test_other_histograms_registered_with_provider_label() -> None:    # given
    for histogram in (
        metrics.MEMORY_INSERT_DURATION_SECONDS,
        metrics.MEMORY_DELETE_DURATION_SECONDS,
        metrics.MEMORY_WIPE_DURATION_SECONDS,
    ):
        histogram.labels(provider="lmstudio").observe(0.1)

    # when
    payload = generate_latest().decode()

    # then
    for name in (
        "memory_insert_duration_seconds",
        "memory_delete_duration_seconds",
        "memory_wipe_duration_seconds",
    ):
        assert name in payload


def test_outcome_for_exception_maps_timeout() -> None:
    # when / then
    assert metrics.outcome_for_exception(TimeoutError("qdrant timed out")) == "timeout"


def test_outcome_for_exception_maps_rate_limited() -> None:
    # given
    refusals = [
        Exception("rate_limited: Rate limit exceeded: 3/minute"),
        Exception("Rate limit exceeded for this caller"),
        Exception("upstream answered 429"),
    ]

    # when / then
    for exc in refusals:
        assert metrics.outcome_for_exception(exc) == "rate_limited"


def test_outcome_for_exception_maps_not_found() -> None:
    # given
    missing = [
        KeyError("m1"),
        FileNotFoundError("m1"),
        LookupError("m1"),
        Exception("memory not_found: m1"),
        Exception("Memory Not Found: m1"),
    ]

    # when / then
    for exc in missing:
        assert metrics.outcome_for_exception(exc) == "not_found"


def test_outcome_for_exception_maps_everything_else_to_error() -> None:
    # given
    unexpected = [
        RuntimeError("qdrant connection refused"),
        ValueError("text must not be empty"),
    ]

    # when / then
    for exc in unexpected:
        assert metrics.outcome_for_exception(exc) == "error"
