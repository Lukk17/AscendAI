from prometheus_client import generate_latest

from src.observability import metrics


def test_search_results_total_registered() -> None:
    metrics.SEARCH_RESULTS_TOTAL.labels(outcome="success").inc(3)

    payload = generate_latest().decode()
    assert "ascendwebsearch_search_results_total" in payload


def test_strategy_counters_registered() -> None:
    metrics.STRATEGY_ATTEMPTS_TOTAL.labels(
        strategy="1-beautifulsoup", outcome="success", domain="example.com"
    ).inc()
    metrics.HUMAN_INTERVENTION_TOTAL.labels(intervention_type="captcha").inc()

    payload = generate_latest().decode()
    assert "strategy_attempts_total" in payload
    assert "human_intervention_total" in payload


def test_searxng_metrics_registered() -> None:
    metrics.SEARXNG_REQUESTS_TOTAL.labels(outcome="success").inc()
    metrics.SEARXNG_DURATION_SECONDS.observe(0.25)

    payload = generate_latest().decode()
    assert "searxng_requests_total" in payload
    assert "searxng_duration_seconds" in payload
