from typing import Any

import pytest

from src.config.config import settings
from src.crawl.robots import (
    RobotsStore,
    collect_sitemap_urls,
    ensure_opt_out,
    load_rules,
    robots_url,
    sitemap_locations,
)

ROBOTS = """User-agent: *
Disallow: /private/
Crawl-delay: 5
Sitemap: https://example.com/sitemap.xml
"""


def test_robots_url_points_at_host_root() -> None:
    assert robots_url("https://example.com/guide/page?x=1") == "https://example.com/robots.txt"


async def test_load_rules_parses_disallow_delay_and_sitemaps() -> None:
    # given
    async def fetch(url: str) -> str:
        assert url == "https://example.com/robots.txt"
        return ROBOTS

    # when
    rules = await load_rules("https://example.com/guide/", fetch)

    # then
    assert rules is not None
    assert rules.can_fetch("https://example.com/guide/", "*")
    assert not rules.can_fetch("https://example.com/private/x", "*")
    assert rules.crawl_delay("*") == 5.0
    assert list(rules.sitemaps) == ["https://example.com/sitemap.xml"]


async def test_load_rules_missing_file_allows_all() -> None:
    # given
    async def fetch(url: str) -> str:
        return ""

    # when
    rules = await load_rules("https://example.com/guide/", fetch)

    # then
    assert rules is None


async def test_load_rules_fetch_error_allows_all() -> None:
    # given
    async def fetch(url: str) -> str:
        raise RuntimeError("down")

    # when
    rules = await load_rules("https://example.com/guide/", fetch)

    # then
    assert rules is None


def test_ensure_opt_out_passes_when_respecting() -> None:
    ensure_opt_out(["https://example.com/"], True)


def test_ensure_opt_out_refuses_unknown_domain() -> None:
    with pytest.raises(ValueError, match="respect_robots=false is refused"):
        ensure_opt_out(["https://example.com/"], False)


def test_ensure_opt_out_accepts_listed_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_OPT_OUT_DOMAINS", ("example.com",))

    # when / then no raise
    ensure_opt_out(["https://example.com/"], False)


def test_sitemap_locations_splits_urlset() -> None:
    # given
    body = (
        '<?xml version="1.0"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/a</loc></url>"
        "<url><loc>  </loc></url>"
        "</urlset>"
    )

    # when
    pages, nested = sitemap_locations(body)

    # then
    assert pages == ["https://example.com/a"]
    assert nested == []


def test_sitemap_locations_splits_index_without_namespace() -> None:
    # given
    body = "<sitemapindex><sitemap><loc>https://example.com/s1.xml</loc></sitemap></sitemapindex>"

    # when
    pages, nested = sitemap_locations(body)

    # then
    assert pages == []
    assert nested == ["https://example.com/s1.xml"]


def test_sitemap_locations_skips_entries_without_loc() -> None:
    # given an index and a urlset whose entries name no location
    index = "<sitemapindex><sitemap><lastmod>2026-01-01</lastmod></sitemap></sitemapindex>"
    urlset = "<urlset><url><lastmod>2026-01-01</lastmod></url></urlset>"

    # when / then both sides are empty
    assert sitemap_locations(index) == ([], [])
    assert sitemap_locations(urlset) == ([], [])


def test_sitemap_locations_ignores_unknown_root() -> None:
    assert sitemap_locations("<feed/>") == ([], [])
    assert sitemap_locations("<urlset/>") == ([], [])


def test_sitemap_locations_rejects_invalid_xml() -> None:
    assert sitemap_locations("not xml") == ([], [])


async def test_collect_sitemap_urls_follows_index_once() -> None:
    # given an index that names itself and one page sitemap
    async def fetch(url: str) -> str:
        if url == "https://example.com/sitemap.xml":
            return (
                "<sitemapindex>"
                "<sitemap><loc>https://example.com/sitemap.xml</loc></sitemap>"
                "<sitemap><loc>https://example.com/pages.xml</loc></sitemap>"
                "</sitemapindex>"
            )
        return "<urlset><url><loc>https://example.com/a</loc></url></urlset>"

    # when
    urls = await collect_sitemap_urls(["https://example.com/sitemap.xml"], fetch)

    # then the self reference does not loop and the page is found
    assert urls == ["https://example.com/a"]


async def test_collect_sitemap_urls_skips_failures() -> None:
    # given
    async def fetch(url: str) -> str:
        if "bad" in url:
            raise RuntimeError("down")
        if "empty" in url:
            return ""
        return "<urlset><url><loc>https://example.com/a</loc></url></urlset>"

    # when
    urls = await collect_sitemap_urls(["https://example.com/bad.xml", "https://example.com/empty.xml"], fetch)

    # then
    assert urls == []


async def test_robots_store_caches_rules_per_job_and_domain() -> None:
    # given
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return ROBOTS

    store = RobotsStore(fetch)

    # when the same domain is read twice for one job
    first = await store.rules("j1", "https://example.com/a")
    second = await store.rules("j1", "https://example.com/b")
    other_job = await store.rules("j2", "https://example.com/a")

    # then the fetch ran once per job and both jobs share nothing
    assert first is second
    assert other_job is not first
    assert calls == ["https://example.com/robots.txt", "https://example.com/robots.txt"]

    # when the job ends
    store.drop_job("j1")
    await store.rules("j1", "https://example.com/a")

    # then the file is fetched again
    assert calls == [
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
    ]


async def test_robots_store_sitemap_seed_urls() -> None:
    # given
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return ROBOTS
        return "<urlset><url><loc>https://example.com/a</loc></url></urlset>"

    store = RobotsStore(fetch)

    # when / then
    assert await store.sitemap_seed_urls("j1", "https://example.com/") == ["https://example.com/a"]


async def test_robots_store_no_rules_no_sitemaps() -> None:
    # given
    async def fetch(url: str) -> str:
        return ""

    store = RobotsStore(fetch)

    # when / then
    assert await store.sitemap_seed_urls("j1", "https://example.com/") == []


async def test_default_fetch_uses_guarded_curl(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    from src.crawl import robots as robots_module

    seen: dict[str, Any] = {}

    async def fake_fetch(url: str, ua: Any, label: str, profile: Any = None) -> str:
        seen["url"] = url
        return ROBOTS

    monkeypatch.setattr(robots_module, "fetch_with_curl_cffi", fake_fetch)

    # when
    rules = await robots_module._default_fetch("https://example.com/guide/")

    # then the fetch goes through the shared guarded fetch
    assert seen["url"] == "https://example.com/guide/"
    assert rules == ROBOTS
