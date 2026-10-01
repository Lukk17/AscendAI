from prometheus_client import generate_latest

from src.observability import metrics


def test_search_results_total_registered() -> None:
    # given
    metrics.SEARCH_RESULTS_TOTAL.labels(outcome="success").inc(3)

    # when
    payload = generate_latest().decode()

    # then
    assert "ascendwebhunter_search_results_total" in payload


def test_strategy_counters_registered() -> None:
    # given
    metrics.STRATEGY_ATTEMPTS_TOTAL.labels(
        strategy="1-beautifulsoup", outcome="success", domain="example.com"
    ).inc()
    metrics.HUMAN_INTERVENTION_TOTAL.labels(intervention_type="captcha").inc()

    # when
    payload = generate_latest().decode()

    # then
    assert "strategy_attempts_total" in payload
    assert "human_intervention_total" in payload


def test_searxng_metrics_registered() -> None:
    # given
    metrics.SEARXNG_REQUESTS_TOTAL.labels(outcome="success").inc()
    metrics.SEARXNG_DURATION_SECONDS.observe(0.25)

    # when
    payload = generate_latest().decode()

    # then
    assert "searxng_requests_total" in payload
    assert "searxng_duration_seconds" in payload
