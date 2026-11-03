from typing import Any

import pytest
from prometheus_client import generate_latest

from src.observability import metrics


def test_search_results_returned_registered() -> None:
    # given
    from prometheus_client import Histogram

    metrics.SEARCH_RESULTS_RETURNED.labels(engine="searxng", outcome="ok").observe(3)

    # when
    payload = generate_latest().decode()

    # then
    assert isinstance(metrics.SEARCH_RESULTS_RETURNED, Histogram)
    assert "search_results_returned" in payload
    assert "ascendwebhunter_search_results_total" not in payload


def test_strategy_counters_registered() -> None:
    # given
    metrics.STRATEGY_ATTEMPTS_TOTAL.labels(
        strategy="1-beautifulsoup", outcome="success", domain="example.com"
    ).inc()
    metrics.HUMAN_INTERVENTION_TOTAL.labels(intervention_type="captcha", joined="false").inc()

    # when
    payload = generate_latest().decode()

    # then
    assert "strategy_attempts_total" in payload
    assert "human_intervention_total" in payload


def test_novnc_metrics_registered_with_labels() -> None:
    # given
    from prometheus_client import Counter, Gauge

    # when
    metrics.NOVNC_ACTIVE_FLOWS.set(2)
    metrics.NOVNC_FLOWS_RECLAIMED_TOTAL.labels(reason="lease_expired").inc()
    metrics.HUMAN_INTERVENTION_TOTAL.labels(intervention_type="captcha", joined="false").inc()

    # then
    assert isinstance(metrics.NOVNC_ACTIVE_FLOWS, Gauge)
    assert isinstance(metrics.NOVNC_FLOWS_RECLAIMED_TOTAL, Counter)
    assert isinstance(metrics.HUMAN_INTERVENTION_TOTAL, Counter)
    payload = generate_latest().decode()
    assert "novnc_active_flows 2.0" in payload
    assert 'novnc_flows_reclaimed_total{reason="lease_expired"}' in payload
    assert 'human_intervention_total{intervention_type="captcha",joined="false"}' in payload
    metrics.NOVNC_ACTIVE_FLOWS.set(0)
    # given
    metrics.STRATEGY_ATTEMPTS_TOTAL.labels(
        strategy="1-beautifulsoup", outcome="success", domain="example.com"
    ).inc()
    metrics.HUMAN_INTERVENTION_TOTAL.labels(intervention_type="captcha", joined="false").inc()

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


def test_challenge_metrics_registered_with_labels() -> None:
    # given
    from prometheus_client import Counter, Histogram

    from src.reader.cloudflare.challenge_signals import assess, record_verdict

    wall_html = "<html><body><div id='cf-challenge-running'></div></body></html>"
    verdict = assess(200, wall_html)
    record_verdict(verdict, "test-tier")

    # when
    payload = generate_latest().decode()

    # then
    assert isinstance(metrics.CHALLENGE_SIGNALS_FIRED_TOTAL, Counter)
    assert isinstance(metrics.CHALLENGE_VERDICTS_TOTAL, Counter)
    assert isinstance(metrics.CHALLENGE_SCORE, Histogram)
    assert 'challenge_signals_fired_total{signal="interstitial_structure",vendor="cloudflare"}' in payload
    assert 'challenge_verdicts_total{tier="test-tier",verdict="wall"}' in payload
    assert 'challenge_score_bucket{le="100.0"' in payload


def test_challenge_score_buckets_hold_threshold() -> None:
    # given / when
    at_default = metrics.challenge_score_buckets(100)
    at_override = metrics.challenge_score_buckets(120)

    # then
    assert at_default == (0, 20, 40, 60, 80, 100, 120, 160, 200, 300)
    assert 120 in at_override
    assert at_override == tuple(sorted(set(at_default) | {120}))


def test_wall_verdict_with_four_signals_increments() -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess, record_verdict

    html = (
        "<html><body>"
        "<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>"
        "<div class='cf-turnstile'></div>"
        "<p>" + "word " * 100 + "</p><a href='/a'>a</a><a href='/b'>b</a></body></html>"
    )
    verdict = assess(200, html)
    assert verdict.wall is True
    assert len(verdict.signals) == 4

    def _counter_value(counter: Any, **labels: str) -> Any:
        return counter.labels(**labels)._value.get()

    before_signals = sum(
        _counter_value(metrics.CHALLENGE_SIGNALS_FIRED_TOTAL, signal=signal.id, vendor="cloudflare")
        for signal in verdict.signals
    )
    before_verdicts = _counter_value(metrics.CHALLENGE_VERDICTS_TOTAL, verdict="wall", tier="tiers")

    def _score_count() -> float:
        import re

        from prometheus_client import generate_latest

        match = re.search(r"^challenge_score_count (\S+)$", generate_latest().decode(), re.MULTILINE)
        assert match is not None

        return float(match.group(1))

    before_sum = metrics.CHALLENGE_SCORE._sum.get()
    before_count = _score_count()

    # when
    for signal in verdict.signals:
        metrics.CHALLENGE_SIGNALS_FIRED_TOTAL.labels(signal=signal.id, vendor="cloudflare").inc()
    record_verdict(verdict, "tiers")
    metrics.CHALLENGE_SCORE.observe(verdict.score)

    # then
    after_signals = sum(
        _counter_value(metrics.CHALLENGE_SIGNALS_FIRED_TOTAL, signal=signal.id, vendor="cloudflare")
        for signal in verdict.signals
    )
    assert after_signals - before_signals == 4.0
    assert _counter_value(
        metrics.CHALLENGE_VERDICTS_TOTAL, verdict="wall", tier="tiers"
    ) - before_verdicts == (1.0)
    assert metrics.CHALLENGE_SCORE._sum.get() - before_sum == float(verdict.score)
    assert _score_count() - before_count == 1.0


def test_assess_increments_signals_and_score() -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess

    def _counter_value(counter: Any, **labels: str) -> Any:
        return counter.labels(**labels)._value.get()

    before = _counter_value(
        metrics.CHALLENGE_SIGNALS_FIRED_TOTAL, signal="interstitial_structure", vendor="cloudflare"
    )

    # when
    verdict = assess(200, "<html><body><div id='cf-challenge-running'></div></body></html>")

    # then
    assert verdict.wall is True
    assert (
        _counter_value(
            metrics.CHALLENGE_SIGNALS_FIRED_TOTAL,
            signal="interstitial_structure",
            vendor="cloudflare",
        )
        - before
        == 1.0
    )


def test_verdict_log_line_carries_score_vendor_type_and_signals(caplog: pytest.LogCaptureFixture) -> None:
    # given
    import logging

    from src.reader.cloudflare.challenge_signals import assess, log_verdict

    verdict = assess(200, "<html><body><div id='cf-challenge-running'></div></body></html>")

    # when
    with caplog.at_level(logging.INFO, logger="src.reader.cloudflare.challenge_signals"):
        log_verdict(verdict, "curl_cffi", "http://test.com/page")

    # then
    assert caplog.records, "a wall verdict must log at INFO"
    line = caplog.records[-1].getMessage()
    assert caplog.records[-1].levelname == "INFO"
    assert f"score={verdict.score}" in line
    assert "vendor=cloudflare" in line
    assert "type=captcha" in line
    for signal in verdict.signals:
        assert signal.id in line


def test_verdict_log_line_hides_header_values_cookie_values_and_excerpts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    import logging

    from src.reader.cloudflare.challenge_signals import assess, log_verdict

    html = "<html><body><article><p>" + "word " * 200 + "</p></article></body></html>"
    verdict = assess(
        403,
        html,
        headers={"cf-mitigated": "challenge", "authorization": "Bearer s3cr3t-value"},
        cookie_names=["sessionid"],
    )
    assert verdict.wall is True

    # when
    with caplog.at_level(logging.INFO, logger="src.reader.cloudflare.challenge_signals"):
        log_verdict(verdict, "curl_cffi", "http://test.com/page")

    # then
    line = caplog.records[-1].getMessage()
    assert "s3cr3t-value" not in line
    assert "Bearer" not in line
    assert "word word" not in line
    assert "sessionid" not in line or "signal" in line


def test_content_verdict_logs_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    # given
    import logging

    from src.reader.cloudflare.challenge_signals import assess, log_verdict

    html = "<html><body><article><p>" + "word " * 200 + "</p></article></body></html>"
    verdict = assess(200, html)
    assert verdict.wall is False

    # when
    with caplog.at_level(logging.DEBUG, logger="src.reader.cloudflare.challenge_signals"):
        log_verdict(verdict, "reader", "http://test.com/page")

    # then
    assert caplog.records, "a quiet content verdict must still log at DEBUG"
    assert caplog.records[-1].levelname == "DEBUG"
