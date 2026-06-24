"""Tests for per-domain metric label with cardinality cap (task 7.2)."""

import pytest

import src.observability.domain_label as dl_module
from src.observability.domain_label import domain_label


@pytest.fixture(autouse=True)
def reset_seen_domains() -> None:
    """Clear the module-level seen-domains set between tests."""
    dl_module._seen_domains.clear()
    yield
    dl_module._seen_domains.clear()


def test_known_domain_returns_registrable_domain() -> None:
    result = domain_label("https://linkedin.com/in/person")
    assert result == "linkedin.com"


def test_same_domain_returns_same_label_on_repeat() -> None:
    label1 = domain_label("https://example.com/a")
    label2 = domain_label("https://example.com/b")
    assert label1 == label2 == "example.com"


def test_domains_beyond_cap_return_other() -> None:
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("src.observability.domain_label.settings.DOMAIN_METRIC_CARDINALITY_CAP", 2)
        dl_module._seen_domains.clear()

        domain_label("https://site1.com/")
        domain_label("https://site2.com/")
        result = domain_label("https://site3.com/")

    assert result == "other"


def test_previously_seen_domain_keeps_label_after_cap_is_reached() -> None:
    """Domains admitted before the cap was hit keep their real label even after cap."""
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("src.observability.domain_label.settings.DOMAIN_METRIC_CARDINALITY_CAP", 2)
        dl_module._seen_domains.clear()

        label_first = domain_label("https://site1.com/")
        domain_label("https://site2.com/")  # fills the cap
        label_first_again = domain_label("https://site1.com/")

    assert label_first == "site1.com"
    assert label_first_again == "site1.com"


def test_domain_label_bare_hostname_without_scheme() -> None:
    """When the URL has no '://' the raw input is used as the label (line 23 else branch)."""
    result = domain_label("example.com")
    assert result == "example.com"


def test_domain_label_ip_address_fallback() -> None:
    """When tldextract cannot extract a registrable domain (e.g. bare IP), the
    fallback extracts the host from the URL string via split('/')."""
    result = domain_label("http://192.168.1.1/path")
    assert result == "192.168.1.1"


def test_strategy_counter_includes_domain_label() -> None:
    """The domain label must be accepted by STRATEGY_ATTEMPTS_TOTAL (3-label metric)."""
    from src.observability.metrics import STRATEGY_ATTEMPTS_TOTAL

    STRATEGY_ATTEMPTS_TOTAL.labels(strategy="1-beautifulsoup", outcome="success", domain="example.com").inc()
    from prometheus_client import generate_latest

    payload = generate_latest().decode()
    assert 'domain="example.com"' in payload
