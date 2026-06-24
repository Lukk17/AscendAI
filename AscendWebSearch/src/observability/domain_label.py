"""Cardinality-capped registrable-domain label for Prometheus metrics.

Once the number of distinct domains seen exceeds DOMAIN_METRIC_CARDINALITY_CAP,
any new domain is bucketed under the reserved label value "other".  Domains
already seen before the cap was reached keep their real label.
"""

import tldextract

from src.config.config import settings

# suffix_list_urls=() disables remote PSL fetches (same choice as cookie_manager).
_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

_seen_domains: set[str] = set()


def _extract_registrable(url: str) -> str:
    """Return the registrable domain (e.g. 'linkedin.com') from a URL."""
    result = _TLD_EXTRACT(url)
    if result.domain and result.suffix:
        return f"{result.domain}.{result.suffix}"
    return url.split("/")[2] if "://" in url else url


def domain_label(url: str) -> str:
    """Return the Prometheus label value for the registrable domain of ``url``.

    New domains are admitted until the cardinality cap is reached; beyond the
    cap every previously-unseen domain maps to "other".
    """
    domain = _extract_registrable(url)
    if domain in _seen_domains:
        return domain
    if len(_seen_domains) >= settings.DOMAIN_METRIC_CARDINALITY_CAP:
        return "other"
    _seen_domains.add(domain)
    return domain
