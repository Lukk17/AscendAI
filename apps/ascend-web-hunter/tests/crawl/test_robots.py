import asyncio
import functools
import gzip
import socket
import threading
import tracemalloc
import zlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import AsyncMock

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from protego import Protego

from src.config.config import settings
from src.crawl import robots as robots_module
from src.crawl.fetcher import CRAWL_USER_AGENT, RobotsFetch, fetch_robots_txt
from src.crawl.robots import (
    RobotsStore,
    collect_sitemap_urls,
    load_rules,
    origin_of,
    robots_url,
    sitemap_locations,
)
from src.session.profile import MAX_URL_LENGTH
from src.session.profile_pattern import is_valid_profile

ROBOTS = """User-agent: *
Disallow: /private/
Crawl-delay: 5
Sitemap: https://example.com/sitemap.xml
"""
ROBOTS_FILE = RobotsFetch(200, ROBOTS)
NO_SITEMAP_LIMIT = 1_000_000


def _allowance(*, documents: int = NO_SITEMAP_LIMIT, urls: int = NO_SITEMAP_LIMIT) -> Any:
    return robots_module.SitemapAllowance(documents=documents, urls=urls)


async def _locations(body: str) -> tuple[list[str], list[str]]:
    return await sitemap_locations(
        body,
        allowance=_allowance(),
        max_nested=NO_SITEMAP_LIMIT,
        accept=lambda _url: True,
        accept_nested=lambda _url: True,
    )


def test_robots_url_points_at_host_root() -> None:
    assert robots_url("https://example.com/guide/page?x=1") == "https://example.com/robots.txt"


async def test_load_rules_parses_disallow_delay_and_sitemaps() -> None:
    # given
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        assert url == "https://example.com/robots.txt"
        return ROBOTS_FILE

    # when
    rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then
    assert rules is not None
    assert rules.can_fetch("https://example.com/guide/", "*")
    assert not rules.can_fetch("https://example.com/private/x", "*")
    assert rules.crawl_delay("*") == 5.0
    assert list(rules.sitemaps) == ["https://example.com/sitemap.xml"]


async def test_load_rules_empty_file_allows_all() -> None:
    # given
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, "")

    # when
    rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then
    assert rules is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 451, 308])
async def test_load_rules_unavailable_file_allows_all(status: int) -> None:
    # given a robots.txt that answers a client error, or a redirect left after the hop limit
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(status, "User-agent: *\nDisallow: /\n")

    # when
    rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then every page of the origin may be crawled
    assert rules is None


@pytest.mark.parametrize("status", [None, 429, 500, 502, 503, 504])
async def test_load_rules_unreachable_file_disallows_the_whole_origin(
    status: int | None, caplog: pytest.LogCaptureFixture
) -> None:
    # given a robots.txt that answers a server error or 429, or no answer at all
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(status, "User-agent: *\nAllow: /\n")

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then no page of the origin may be crawled, whatever the body says
    assert rules is not None
    assert not rules.can_fetch("https://example.com/", "*")
    assert not rules.can_fetch("https://example.com/guide/page?x=1", "*")
    assert rules.crawl_delay("*") is None
    assert list(rules.sitemaps) == []
    assert "https://example.com/robots.txt" in caplog.text


async def test_load_rules_reads_a_guard_refusal_as_an_absent_file() -> None:
    # given a robots.txt whose address or redirect hop the guard refuses
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        raise UnsafeUriError("redirect to a private address")

    # when
    rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then the crawl reads the file as absent, as before the guard refusal reached the caller
    assert rules is None


async def test_load_rules_lets_a_raised_fetch_reach_the_caller() -> None:
    # given
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        raise RuntimeError("cookie store down")

    # when / then
    with pytest.raises(RuntimeError, match="cookie store down"):
        await load_rules("https://example.com/guide/", fetch, profile=None)


async def test_sitemap_locations_splits_urlset() -> None:
    # given
    body = (
        '<?xml version="1.0"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/a</loc></url>"
        "<url><loc>  </loc></url>"
        "</urlset>"
    )

    # when
    pages, nested = await _locations(body)

    # then
    assert pages == ["https://example.com/a"]
    assert nested == []


async def test_sitemap_locations_splits_index_without_namespace() -> None:
    # given
    body = "<sitemapindex><sitemap><loc>https://example.com/s1.xml</loc></sitemap></sitemapindex>"

    # when
    pages, nested = await _locations(body)

    # then
    assert pages == []
    assert nested == ["https://example.com/s1.xml"]


async def test_sitemap_locations_skips_entries_without_loc() -> None:
    # given an index and a urlset whose entries name no location
    index = "<sitemapindex><sitemap><lastmod>2026-01-01</lastmod></sitemap></sitemapindex>"
    urlset = "<urlset><url><lastmod>2026-01-01</lastmod></url></urlset>"

    # when / then both sides are empty
    assert await _locations(index) == ([], [])
    assert await _locations(urlset) == ([], [])


async def test_sitemap_locations_ignores_unknown_root() -> None:
    assert await _locations("<feed/>") == ([], [])
    assert await _locations("<urlset/>") == ([], [])


async def test_sitemap_locations_rejects_invalid_xml() -> None:
    assert await _locations("not xml") == ([], [])


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
    urls = await collect_sitemap_urls(
        ["https://example.com/sitemap.xml"], fetch, allowance=_allowance(documents=50, urls=10)
    )

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
    urls = await collect_sitemap_urls(
        ["https://example.com/bad.xml", "https://example.com/empty.xml"],
        fetch,
        allowance=_allowance(documents=50, urls=10),
    )

    # then
    assert urls == []


async def test_robots_store_caches_rules_per_job_and_domain() -> None:
    # given
    calls: list[str] = []

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        return ROBOTS_FILE

    store = RobotsStore(fetch)

    # when the same domain is read twice for one job
    first = await store.rules("j1", "https://example.com/a", profile=None)
    second = await store.rules("j1", "https://example.com/b", profile=None)
    other_job = await store.rules("j2", "https://example.com/a", profile=None)

    # then the fetch ran once per job and both jobs share nothing
    assert first is second
    assert other_job is not first
    assert calls == ["https://example.com/robots.txt", "https://example.com/robots.txt"]

    # when the job ends
    store.drop_job("j1")
    await store.rules("j1", "https://example.com/a", profile=None)

    # then the file is fetched again
    assert calls == [
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
    ]


async def test_robots_store_shares_one_fetch_between_concurrent_asks_for_one_origin() -> None:
    # given
    calls: list[str] = []
    release = asyncio.Event()

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        await release.wait()
        return ROBOTS_FILE

    store = RobotsStore(fetch)

    # when four workers ask for the rules of one origin at the same moment
    asks = [
        asyncio.create_task(store.rules("j1", f"https://example.com/{page}", profile=None)) for page in "abcd"
    ]
    await asyncio.sleep(0)
    release.set()
    answers = await asyncio.gather(*asks)

    # then one fetch ran, all four share its rules, and no gate is left behind
    assert calls == ["https://example.com/robots.txt"]
    assert answers[0] is not None
    assert all(answer is answers[0] for answer in answers)
    assert store._gates == {}


@pytest.mark.parametrize("status", [None, 429, 503])
async def test_robots_store_keeps_an_unreachable_verdict_as_disallow_all_for_the_job_with_one_fetch(
    status: int | None,
) -> None:
    # given
    calls: list[str] = []
    release = asyncio.Event()

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        await release.wait()
        return RobotsFetch(status)

    store = RobotsStore(fetch)

    # when four workers ask at the same moment and the one fetch finds the file unreachable
    asks = [
        asyncio.create_task(store.rules("j1", f"https://example.com/{page}", profile=None)) for page in "abcd"
    ]
    await asyncio.sleep(0)
    release.set()
    answers = await asyncio.gather(*asks)
    later = await store.rules("j1", "https://example.com/e", profile=None)

    # then all of them read disallow-all from that one fetch until the job ends
    assert answers[0] is not None
    assert not answers[0].can_fetch("https://example.com/a", "*")
    assert all(answer is answers[0] for answer in [*answers, later])
    assert calls == ["https://example.com/robots.txt"]
    assert store._gates == {}


async def test_robots_store_does_not_keep_a_raised_fetch_and_the_next_ask_fetches_again() -> None:
    # given a fetch that raises once and then answers the file
    calls: list[str] = []

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("cookie store down")
        return ROBOTS_FILE

    store = RobotsStore(fetch)

    # when
    with pytest.raises(RuntimeError, match="cookie store down"):
        await store.rules("j1", "https://example.com/a", profile=None)
    rules = await store.rules("j1", "https://example.com/b", profile=None)

    # then the raised fetch was not kept and the second ask read the file
    assert rules is not None
    assert not rules.can_fetch("https://example.com/private/x", "*")
    assert calls == ["https://example.com/robots.txt", "https://example.com/robots.txt"]
    assert store._gates == {}


async def test_robots_store_does_not_keep_a_cancelled_fetch_and_the_next_ask_fetches_again() -> None:
    # given
    calls: list[str] = []
    release = asyncio.Event()

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        await release.wait()
        return ROBOTS_FILE

    store = RobotsStore(fetch)

    # when the worker that fetches is cancelled while three more wait for the same origin
    asks = [
        asyncio.create_task(store.rules("j1", f"https://example.com/{page}", profile=None)) for page in "abcd"
    ]
    await asyncio.sleep(0)
    asks[0].cancel()
    await asyncio.sleep(0)
    release.set()
    answers = await asyncio.gather(*asks, return_exceptions=True)

    # then the cancelled fetch is not kept, the next waiter fetches once more and the other two share it
    assert isinstance(answers[0], asyncio.CancelledError)
    assert answers[1] is not None
    assert answers[2] is answers[1]
    assert answers[3] is answers[1]
    assert calls == ["https://example.com/robots.txt", "https://example.com/robots.txt"]
    assert store._gates == {}


async def test_robots_store_sitemap_seed_urls() -> None:
    # given
    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return ROBOTS_FILE

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        return "<urlset><url><loc>https://example.com/a</loc></url></urlset>"

    store = RobotsStore(robots_fetch, sitemap_fetch)

    # when / then
    assert await store.sitemap_seed_urls("j1", "https://example.com/", profile=None, max_urls=10) == [
        "https://example.com/a"
    ]


async def test_robots_store_no_rules_no_sitemaps() -> None:
    # given
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(404)

    store = RobotsStore(fetch)

    # when / then
    assert await store.sitemap_seed_urls("j1", "https://example.com/", profile=None, max_urls=10) == []


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://Example.COM/a?x=1", "https://example.com:443"),
        ("http://example.com/a", "http://example.com:80"),
        ("https://docs.example.com:8443/a", "https://docs.example.com:8443"),
    ],
)
def test_origin_of_names_scheme_host_and_port(url: str, origin: str) -> None:
    assert origin_of(url) == origin


async def test_robots_store_caches_rules_per_origin() -> None:
    # given
    calls: list[str] = []

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        return ROBOTS_FILE

    store = RobotsStore(fetch)

    # when three origins of one registrable domain are read, one of them twice
    await store.rules("j1", "https://example.com/a", profile=None)
    await store.rules("j1", "https://example.com:443/b", profile=None)
    await store.rules("j1", "https://docs.example.com/a", profile=None)
    await store.rules("j1", "http://example.com/a", profile=None)
    await store.rules("j1", "https://example.com:8443/a", profile=None)

    # then each origin's own file is fetched once
    assert calls == [
        "https://example.com/robots.txt",
        "https://docs.example.com/robots.txt",
        "http://example.com/robots.txt",
        "https://example.com:8443/robots.txt",
    ]


async def test_collect_sitemap_urls_stops_at_the_url_bound() -> None:
    # given an index of three page sitemaps with two URLs each
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        if url.endswith("index.xml"):
            return (
                "<sitemapindex>"
                + "".join(f"<sitemap><loc>https://example.com/s{n}.xml</loc></sitemap>" for n in range(3))
                + "</sitemapindex>"
            )
        name = url.rsplit("/", 1)[1]
        return f"<urlset><url><loc>https://example.com/{name}-1</loc></url><url><loc>https://example.com/{name}-2</loc></url></urlset>"

    # when collection is bounded to three URLs
    urls = await collect_sitemap_urls(
        ["https://example.com/index.xml"], fetch, allowance=_allowance(documents=50, urls=3)
    )

    # then it returns three URLs and fetches no sitemap past the bound
    assert len(urls) == 3
    assert len(fetched) == 3


async def test_collect_sitemap_urls_counts_only_accepted_urls() -> None:
    # given
    async def fetch(url: str) -> str:
        return (
            "<urlset><url><loc>https://example.com/skip</loc></url>"
            "<url><loc>https://example.com/keep</loc></url></urlset>"
        )

    # when
    urls = await collect_sitemap_urls(
        ["https://example.com/sitemap.xml"],
        fetch,
        allowance=_allowance(documents=50, urls=1),
        accept=lambda url: url.endswith("/keep"),
    )

    # then
    assert urls == ["https://example.com/keep"]


def _index_of(count: int) -> str:
    return (
        "<sitemapindex>"
        + "".join(f"<sitemap><loc>https://example.com/s{n}.xml</loc></sitemap>" for n in range(count))
        + "</sitemapindex>"
    )


async def _index_and_pages(fetched: list[str], url: str) -> str:
    fetched.append(url)
    if url.endswith("index.xml"):
        return _index_of(5)
    name = url.rsplit("/", 1)[1]
    return f"<urlset><url><loc>https://example.com/{name}-page</loc></url></urlset>"


async def test_collect_sitemap_urls_stops_at_the_document_bound(caplog: pytest.LogCaptureFixture) -> None:
    # given an index naming five page sitemaps
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        return await _index_and_pages(fetched, url)

    # when collection is bounded to three documents, the index included
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        urls = await collect_sitemap_urls(
            ["https://example.com/index.xml"], fetch, allowance=_allowance(documents=3, urls=100)
        )

    # then the index and two page sitemaps are fetched, nothing more, and the stop is logged
    assert len(fetched) == 3
    assert len(urls) == 2
    assert "1 sitemaps not fetched" in caplog.text


async def test_collect_sitemap_urls_counts_failed_fetches_against_the_document_bound() -> None:
    # given sitemaps that all fail
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        raise RuntimeError("down")

    # when
    urls = await collect_sitemap_urls(
        [f"https://example.com/s{n}.xml" for n in range(5)],
        fetch,
        allowance=_allowance(documents=2, urls=100),
    )

    # then
    assert urls == []
    assert len(fetched) == 2


async def test_collect_sitemap_urls_logs_nothing_when_the_document_bound_is_not_reached(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given an index that names itself only
    async def fetch(url: str) -> str:
        return "<sitemapindex><sitemap><loc>https://example.com/index.xml</loc></sitemap></sitemapindex>"

    # when the bound is exactly one document
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        urls = await collect_sitemap_urls(
            ["https://example.com/index.xml"], fetch, allowance=_allowance(documents=1, urls=10)
        )

    # then the visited self reference is not reported as a skipped sitemap
    assert urls == []
    assert caplog.text == ""


async def test_robots_store_sitemap_seed_urls_reads_the_document_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given robots.txt pointing at an index of five sitemaps and a bound of two documents
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_MAX_DOCUMENTS", 2)
    fetched: list[str] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, "Sitemap: https://example.com/index.xml\n")

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        return await _index_and_pages(fetched, url)

    store = RobotsStore(robots_fetch, sitemap_fetch)

    # when
    urls = await store.sitemap_seed_urls("j1", "https://example.com/", profile=None, max_urls=100)

    # then
    assert len(fetched) == 2
    assert len(urls) == 1


async def test_default_sitemap_fetch_caps_the_bytes_of_one_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    from src.crawl import robots as robots_module

    seen: dict[str, Any] = {}

    async def fake_fetch(
        url: str,
        ua: Any,
        label: str,
        profile: Any = None,
        *,
        max_bytes: int | None = None,
        unpack: Any = None,
    ) -> str:
        seen["url"] = url
        seen["max_bytes"] = max_bytes
        return "<urlset/>"

    monkeypatch.setattr(robots_module, "fetch_with_curl_cffi", fake_fetch)
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_MAX_BYTES", 1234)

    # when
    body = await robots_module._default_sitemap_fetch("https://example.com/sitemap.xml", None)

    # then the sitemap goes through the shared guarded fetch with the byte cap
    assert seen == {"url": "https://example.com/sitemap.xml", "max_bytes": 1234}
    assert body == "<urlset/>"


async def test_default_sitemap_fetch_treats_a_refused_redirect_as_an_absent_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from src.crawl import robots as robots_module

    async def refused_fetch(*_args: Any, **_kwargs: Any) -> str:
        raise UnsafeUriError("redirect to a private address")

    monkeypatch.setattr(robots_module, "fetch_with_curl_cffi", refused_fetch)

    # when
    body = await robots_module._default_sitemap_fetch("https://example.com/sitemap.xml", None)

    # then the crawl reads the file as absent, as before the guard refusal reached the caller
    assert body == ""


async def test_robots_store_defaults_to_the_robots_fetch_and_the_capped_sitemap_fetch() -> None:
    # given
    from src.crawl import robots as robots_module

    # when
    store = RobotsStore()

    # then
    assert store._fetch is fetch_robots_txt
    assert store._sitemap_fetch is robots_module._default_sitemap_fetch


_GZ_SITEMAP_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<url><loc>https://example.com/guide/one</loc></url>"
    b"<url><loc>https://example.com/guide/two</loc></url>"
    b"</urlset>"
)
_GZ_SITEMAP_PAGES = ["https://example.com/guide/one", "https://example.com/guide/two"]
_BOMB_INFLATED_BYTES = 256 * 1024 * 1024
_BOMB_CAP_BYTES = 1024 * 1024
_BOMB_PEAK_LIMIT_BYTES = 16 * 1024 * 1024
_BOMB_PATHS: dict[str, str] = {"/bomb.xml.gz": "application/gzip", "/mistyped-bomb.xml": "text/xml"}


@functools.cache
def _gzip_bomb() -> bytes:
    deflater = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
    zeros = bytes(1024 * 1024)
    parts = [deflater.compress(b"<urlset>")]
    parts.extend(deflater.compress(zeros) for _ in range(_BOMB_INFLATED_BYTES // len(zeros)))
    parts.append(deflater.compress(b"</urlset>"))
    parts.append(deflater.flush())
    return b"".join(parts)


_SITEMAP_ROUTES: dict[str, tuple[str, bytes]] = {
    "/sitemap.xml.gz": ("application/octet-stream", gzip.compress(_GZ_SITEMAP_XML)),
    "/typed-gzip": ("application/gzip", gzip.compress(_GZ_SITEMAP_XML)),
    "/typed-x-gzip": ("Application/X-Gzip; charset=binary", gzip.compress(_GZ_SITEMAP_XML)),
    "/plain.xml": ("application/xml", _GZ_SITEMAP_XML),
    "/mistyped-gzip.xml": ("application/xml", gzip.compress(_GZ_SITEMAP_XML)),
    "/already-inflated.xml.gz": ("application/gzip", _GZ_SITEMAP_XML),
    "/truncated.xml.gz": ("application/gzip", gzip.compress(_GZ_SITEMAP_XML)[:-12]),
    "/corrupt.xml.gz": ("application/gzip", b"\x1f\x8b\x00not a deflate stream"),
}


class _SitemapHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        content_type, body = (
            (_BOMB_PATHS[self.path], _gzip_bomb()) if self.path in _BOMB_PATHS else _SITEMAP_ROUTES[self.path]
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def sitemap_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    from src.reader.cloudflare.cookie_manager import cookie_manager

    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("127.0.0.1",))
    monkeypatch.setattr(cookie_manager, "get_flat_cookies", AsyncMock(return_value={}))
    monkeypatch.setattr(cookie_manager, "get_user_agent", AsyncMock(return_value=None))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SitemapHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize(
    "path",
    [
        "/sitemap.xml.gz",
        "/typed-gzip",
        "/typed-x-gzip",
        "/plain.xml",
        "/already-inflated.xml.gz",
        "/mistyped-gzip.xml",
    ],
)
async def test_default_sitemap_fetch_reads_gzipped_and_plain_sitemaps(sitemap_server: str, path: str) -> None:
    # given
    from src.crawl import robots as robots_module

    # when
    body = await robots_module._default_sitemap_fetch(f"{sitemap_server}{path}", None)

    # then
    assert await _locations(body) == (_GZ_SITEMAP_PAGES, [])


@pytest.mark.parametrize("path", ["/truncated.xml.gz", "/corrupt.xml.gz"])
async def test_default_sitemap_fetch_skips_a_broken_gzip_sitemap(sitemap_server: str, path: str) -> None:
    # given
    from src.crawl import robots as robots_module

    # when
    body = await robots_module._default_sitemap_fetch(f"{sitemap_server}{path}", None)

    # then
    assert body == ""


@pytest.mark.parametrize("path", list(_BOMB_PATHS))
async def test_default_sitemap_fetch_stops_inflating_a_gzip_bomb_at_the_cap(
    sitemap_server: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    # given a 256 MiB gzip bomb whose compressed form fits a cap of 1 MiB
    from src.crawl import robots as robots_module

    monkeypatch.setattr(settings, "CRAWL_SITEMAP_MAX_BYTES", _BOMB_CAP_BYTES)

    # when
    tracemalloc.start()
    try:
        with caplog.at_level("WARNING", logger="src.reader.strategies.curl_cffi_fetcher"):
            body = await robots_module._default_sitemap_fetch(f"{sitemap_server}{path}", None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # then the file is skipped and inflation never held more than a few times the cap
    assert body == ""
    assert f"above the cap of {_BOMB_CAP_BYTES} bytes" in caplog.text
    assert peak < _BOMB_PEAK_LIMIT_BYTES


class _RobotsServer(ThreadingHTTPServer):
    robots_status: int = 200
    robots_body: bytes = b"User-agent: *\nDisallow: /private/\n"


class _RobotsHandler(BaseHTTPRequestHandler):
    server: _RobotsServer

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        body = self.server.robots_body
        self.send_response(self.server.robots_status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def robots_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[_RobotsServer]:
    from src.reader.cloudflare.cookie_manager import cookie_manager

    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("127.0.0.1",))
    monkeypatch.setattr(cookie_manager, "get_flat_cookies", AsyncMock(return_value={}))
    monkeypatch.setattr(cookie_manager, "get_user_agent", AsyncMock(return_value=None))
    server = _RobotsServer(("127.0.0.1", 0), _RobotsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize(
    ("status", "public_allowed", "private_allowed"),
    [
        (200, True, False),
        (404, True, True),
        (500, False, False),
        (503, False, False),
        (429, False, False),
    ],
)
async def test_robots_store_applies_rfc_9309_to_the_answer_of_a_real_server(
    robots_server: _RobotsServer, status: int, public_allowed: bool, private_allowed: bool
) -> None:
    # given a server whose robots.txt answers the status
    robots_server.robots_status = status
    origin = f"http://127.0.0.1:{robots_server.server_port}"
    store = RobotsStore()

    # when
    rules = await store.rules("j1", f"{origin}/page", profile=None)

    # then a 4xx file allows all, while 5xx and 429 disallow the whole origin
    def allowed(path: str) -> bool:
        return rules is None or rules.can_fetch(f"{origin}{path}", "*")

    assert allowed("/page") is public_allowed
    assert allowed("/private/x") is private_allowed


async def test_robots_store_disallows_an_origin_whose_robots_txt_refuses_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a port where nothing listens
    import socket

    from src.reader.cloudflare.cookie_manager import cookie_manager

    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("127.0.0.1",))
    monkeypatch.setattr(cookie_manager, "get_flat_cookies", AsyncMock(return_value={}))
    monkeypatch.setattr(cookie_manager, "get_user_agent", AsyncMock(return_value=None))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    store = RobotsStore()

    # when
    rules = await store.rules("j1", f"http://127.0.0.1:{port}/page", profile=None)

    # then
    assert rules is not None
    assert not rules.can_fetch(f"http://127.0.0.1:{port}/page", "*")


async def test_robots_store_parses_the_first_part_of_a_robots_txt_larger_than_the_cap(
    robots_server: _RobotsServer,
) -> None:
    # given a robots.txt of about 2 MiB whose rules before the 500 KiB cap disallow one path
    padding = b"# padding line of a robots.txt that is far too large\n" * 40000
    robots_server.robots_body = b"User-agent: *\nDisallow: /private/\n" + padding + b"Disallow: /late/\n"
    assert len(robots_server.robots_body) > 2 * settings.CRAWL_ROBOTS_MAX_BYTES
    origin = f"http://127.0.0.1:{robots_server.server_port}"

    # when
    rules = await RobotsStore().rules("j1", f"{origin}/page", profile=None)

    # then the rules in the first part apply and the rule past the cap is ignored
    assert rules is not None
    assert not rules.can_fetch(f"{origin}/private/x", "*")
    assert rules.can_fetch(f"{origin}/late/x", "*")
    assert rules.can_fetch(f"{origin}/page", "*")


async def test_robots_store_keeps_one_verdict_per_profile_and_fetches_with_it() -> None:
    # given
    calls: list[tuple[str, str | None]] = []

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append((url, profile))
        return ROBOTS_FILE if profile == "alice" else RobotsFetch(404)

    store = RobotsStore(fetch)

    # when one job and origin is asked for two profiles, the first one twice
    alice = await store.rules("j1", "https://example.com/a", profile="alice")
    again = await store.rules("j1", "https://example.com/b", profile="alice")
    bob = await store.rules("j1", "https://example.com/a", profile="bob")

    # then each profile fetched once with its own session and kept its own verdict
    assert calls == [("https://example.com/robots.txt", "alice"), ("https://example.com/robots.txt", "bob")]
    assert alice is again
    assert alice is not None
    assert not alice.can_fetch("https://example.com/private/x", "*")
    assert bob is None


async def test_robots_store_reads_sitemaps_with_the_profile() -> None:
    # given
    seen: list[str | None] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return ROBOTS_FILE

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        seen.append(profile)
        return "<urlset/>"

    store = RobotsStore(robots_fetch, sitemap_fetch)

    # when
    await store.sitemap_seed_urls("j1", "https://example.com/", profile="alice", max_urls=10)

    # then
    assert seen == ["alice"]


async def test_default_sitemap_fetch_sends_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    from src.crawl import robots as robots_module

    seen: list[Any] = []

    async def fake_fetch(url: str, ua: Any, label: str, profile: Any = None, **kwargs: Any) -> str:
        seen.append(profile)
        return "<urlset/>"

    monkeypatch.setattr(robots_module, "fetch_with_curl_cffi", fake_fetch)

    # when
    await robots_module._default_sitemap_fetch("https://example.com/sitemap.xml", "alice")

    # then
    assert seen == ["alice"]


async def test_robots_store_keeps_nothing_from_a_fetch_that_ran_while_its_job_was_dropped() -> None:
    # given a fetch that is still running
    calls: list[str] = []
    release = asyncio.Event()

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        await release.wait()
        return ROBOTS_FILE

    store = RobotsStore(fetch)
    ask = asyncio.create_task(store.rules("j1", "https://example.com/a", profile=None))
    await asyncio.sleep(0)

    # when the job ends while the fetch runs
    store.drop_job("j1")
    release.set()
    answer = await ask

    # then the asker gets its answer, nothing is kept, and the drop mark is gone with the last fetch
    assert answer is not None
    assert store._cache == {}
    assert store._dropped == set()
    assert store._gates == {}


async def test_robots_store_drop_of_one_job_does_not_affect_a_running_fetch_of_another() -> None:
    # given a running fetch of job j2
    release = asyncio.Event()

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        await release.wait()
        return ROBOTS_FILE

    store = RobotsStore(fetch)
    ask = asyncio.create_task(store.rules("j2", "https://example.com/a", profile=None))
    await asyncio.sleep(0)

    # when job j1, which has no fetch running, is dropped
    store.drop_job("j1")
    release.set()
    await ask

    # then j2 keeps its verdict and no drop mark is left
    assert ("j2", None, "https://example.com:443") in store._cache
    assert store._dropped == set()


@pytest.mark.parametrize("answer", ["refused", "unreachable"])
async def test_load_rules_logs_the_robots_address_without_userinfo(
    answer: str, caplog: pytest.LogCaptureFixture
) -> None:
    # given a page address that carries userinfo
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        if answer == "refused":
            raise UnsafeUriError("refused")
        return RobotsFetch(503)

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        await load_rules("https://user:secret@example.com/x", fetch, profile=None)

    # then
    assert "example.com/robots.txt" in caplog.text
    assert "secret" not in caplog.text


class _ParseNotAllowed:
    @staticmethod
    def parse(_body: str) -> None:
        raise AssertionError("the file must not reach the parser")


def _groups_body(agent_line: str, agents: int, rules: int) -> str:
    return (agent_line + "\n") * agents + "Disallow: /x\n" * rules


async def _rules_of(body: str) -> Any:
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, body)

    return await load_rules("https://example.com/guide/", fetch, profile=None)


@pytest.mark.parametrize(
    "agent_line",
    [
        "User-agent: a",
        "USER-AGENT:a",
        "useragent: a",
        "User agent: a",
        "User-agent a",
        "  User-agent : a # c",
    ],
)
async def test_load_rules_refuses_a_file_whose_rules_expand_past_the_limit_before_parsing_it(
    agent_line: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given a file of 20 agents and 20 rules, which is 400 rule objects, and a limit of 399
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_RULES", 399)
    monkeypatch.setattr(robots_module, "Protego", _ParseNotAllowed)

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        rules = await _rules_of(_groups_body(agent_line, 20, 20))

    # then every page of the origin is disallowed and the refusal is logged
    assert rules is robots_module._DISALLOW_ALL
    assert "399" in caplog.text


async def test_load_rules_parses_a_file_at_the_rule_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_RULES", 400)

    # when
    rules = await _rules_of(_groups_body("User-agent: a", 20, 20))

    # then
    assert rules is not robots_module._DISALLOW_ALL
    assert not rules.can_fetch("https://example.com/x", "a")


async def test_load_rules_does_not_count_comments_and_blank_lines_as_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given two agents, one rule and many lines that make no rule object
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_RULES", 2)
    padding = "# a comment\n\n   \n" * 100

    # when
    rules = await _rules_of("User-agent: a\nUser-agent: b\n" + padding + "Disallow: /x\n")

    # then
    assert rules is not robots_module._DISALLOW_ALL


async def test_load_rules_refuses_the_measured_hostile_file_without_parsing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given the file of 16000 agents and 23272 rules, under the byte cap, and the default limit
    monkeypatch.setattr(robots_module, "Protego", _ParseNotAllowed)
    body = "User-agent:a\n" * 16000 + "Disallow:/\n" * 23272
    assert len(body) < settings.CRAWL_ROBOTS_MAX_BYTES

    # when
    rules = await _rules_of(body)

    # then
    assert rules is robots_module._DISALLOW_ALL


async def test_load_rules_reads_a_group_that_names_the_crawler() -> None:
    # given
    body = f"User-agent: {CRAWL_USER_AGENT}\nDisallow: /named/\n\nUser-agent: *\nDisallow: /star/\n"

    # when
    rules = await _rules_of(body)

    # then the crawler obeys its own group and not the star group
    assert not rules.can_fetch("https://example.com/named/x", CRAWL_USER_AGENT)
    assert rules.can_fetch("https://example.com/star/x", CRAWL_USER_AGENT)


async def test_load_rules_reads_the_first_group_of_a_file_with_a_byte_order_mark() -> None:
    # given
    rules = await _rules_of("\ufeffUser-agent: *\nDisallow: /private/\n")

    # then
    assert not rules.can_fetch("https://example.com/private/x", CRAWL_USER_AGENT)
    assert rules.can_fetch("https://example.com/open", CRAWL_USER_AGENT)


async def test_load_rules_counts_the_first_agent_of_a_file_with_a_byte_order_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given one agent line behind the mark and two rules, which is two rule objects over a limit of 1
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_RULES", 1)
    monkeypatch.setattr(robots_module, "Protego", _ParseNotAllowed)

    # when
    rules = await _rules_of("\ufeffUser-agent: *\nDisallow: /a\nDisallow: /b\n")

    # then
    assert rules is robots_module._DISALLOW_ALL


async def test_load_rules_reads_a_lookup_failure_as_an_unreachable_file(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a guard refusal caused by a name that does not resolve
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        raise UnsafeUriError("host does not resolve") from socket.gaierror(-2, "Name or service not known")

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then every page of the origin is disallowed
    assert rules is robots_module._DISALLOW_ALL
    assert "absent" not in caplog.text
    assert "https://example.com/robots.txt" in caplog.text


async def test_load_rules_reads_any_other_guard_refusal_with_a_cause_as_an_absent_file() -> None:
    # given
    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        raise UnsafeUriError("invalid port in URI") from ValueError("bad port")

    # when
    rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then
    assert rules is None


async def test_load_rules_reads_a_slow_answer_as_an_unreachable_file(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given a robots.txt that never answers and a short deadline
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_TIMEOUT_SECONDS", 0.01)

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        await asyncio.Event().wait()
        return ROBOTS_FILE

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        rules = await load_rules("https://example.com/guide/", fetch, profile=None)

    # then
    assert rules is robots_module._DISALLOW_ALL
    assert "https://example.com/robots.txt" in caplog.text


async def test_robots_store_job_ids_names_the_jobs_it_remembers() -> None:
    # given
    store = RobotsStore(lambda url, profile: _answer(ROBOTS_FILE), _no_sitemap)
    await store.rules("j1", "https://example.com/a", profile=None)
    await store.sitemap_seed_urls("j2", "https://example.org/a", profile=None, max_urls=10)

    # when / then
    assert store.job_ids() == {"j1", "j2"}


async def test_robots_store_job_ids_forgets_a_dropped_job_and_its_sitemap_allowance() -> None:
    # given
    store = RobotsStore(lambda url, profile: _answer(ROBOTS_FILE), _no_sitemap)
    await store.sitemap_seed_urls("j1", "https://example.com/a", profile=None, max_urls=10)

    # when
    store.drop_job("j1")

    # then
    assert store.job_ids() == set()


async def _answer(answer: RobotsFetch) -> RobotsFetch:
    return answer


async def _no_sitemap(_url: str, _profile: str | None) -> str:
    return ""


async def test_robots_store_evicts_the_least_recently_used_origin_at_the_cache_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a cache of two origins that holds a and b, with a read last
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_CACHE_MAX_ORIGINS", 2)
    calls: list[str] = []

    async def fetch(url: str, profile: str | None) -> RobotsFetch:
        calls.append(url)
        return ROBOTS_FILE

    store = RobotsStore(fetch)
    await store.rules("j1", "https://a.example.com/", profile=None)
    await store.rules("j1", "https://b.example.com/", profile=None)
    await store.rules("j1", "https://a.example.com/", profile=None)

    # when a third origin arrives
    await store.rules("j1", "https://c.example.com/", profile=None)
    await store.rules("j1", "https://a.example.com/", profile=None)
    await store.rules("j1", "https://b.example.com/", profile=None)

    # then b, the least recently used, was evicted and fetched again, while a stayed
    assert calls == [
        "https://a.example.com/robots.txt",
        "https://b.example.com/robots.txt",
        "https://c.example.com/robots.txt",
        "https://b.example.com/robots.txt",
    ]
    assert len(store._cache) == 2


def _parsed_rule_objects(body: str) -> int:
    parsed = Protego.parse(body)

    return sum(len(rule_set._rules) for rule_set in parsed._user_agents.values())


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("User-agent: *\nDisallow: /a\n", 1),
        ("User-agent: a1*\nDisallow: /a\n", 2),
        ("User-agent: **\nDisallow: /a\n", 1),
        ("User-agent:\nDisallow: /a\n", 0),
        ("User-agent: a\nAllow: /a$\n", 2),
        ("User-agent: a\nDisallow: /a$\n", 2),
        ("User-agent: a\nAllow: /index.html\n", 2),
        ("User-agent: a\nDisallow: /index.html\n", 1),
        ("User-agent: a\nAllow: /$/index.html\n", 4),
        ("User-agent: a\nAllow: /%69ndex.html\n", 2),
        ("User-agent: a1*\nUser-agent: b\nAllow: /$/index.html\nDisallow: /b\n", (2 + 1) * (4 + 1)),
        ("User-agent a\nALLOW /$/index.html\n", 4),
        ("# only a comment\n\n", 0),
    ],
)
def test_rule_objects_of_is_the_exact_weighted_bound(body: str, expected: int) -> None:
    # when
    counted = robots_module._rule_objects_of(body)

    # then
    assert counted == expected
    assert _parsed_rule_objects(body) <= counted


@pytest.mark.parametrize(
    "body",
    [
        "User-agent: a1*\nUser-agent: a2*\nAllow: /$/index.html\nAllow: /$/x/index.html\n",
        "User-agent: a*\nDisallow: /a$\nDisallow: /b$\nAllow: /c\n",
        "User-agent: a\nDisallow: /a\nUser-agent: b\nAllow: /c$/index.html\n",
    ],
)
def test_protego_never_builds_more_rule_objects_than_counted(body: str) -> None:
    # then
    assert _parsed_rule_objects(body) <= robots_module._rule_objects_of(body)


async def test_load_rules_disallows_starred_agents_with_index_rules_at_the_default_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given 1000 starred agents and 1000 rules, which count 1,000,000 and expand to 8,000,000
    monkeypatch.setattr(robots_module, "Protego", _ParseNotAllowed)
    agents = "".join(f"User-agent: a{index}*\n" for index in range(1000))
    body = agents + "Allow: /$/index.html\n" * 1000

    # when
    rules = await _rules_of(body)

    # then
    assert robots_module._rule_objects_of(body) == 8_000_000
    assert rules is robots_module._DISALLOW_ALL


def _store_of_large_files(rules_each: int) -> RobotsStore:
    body = "User-agent: a\n" + "".join(f"Disallow: /p{index}\n" for index in range(rules_each))

    async def fetch(_url: str, _profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, body)

    return RobotsStore(fetch, _no_sitemap)


async def test_robots_store_keeps_the_cached_rule_total_under_its_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given files of 400 rules and a total of 1000 rules across the cache
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_CACHE_MAX_RULES", 1000)
    store = _store_of_large_files(400)

    # when
    for origin in range(5):
        await store.rules("j1", f"https://o{origin}.example.com/", profile=None)

    # then the oldest files went and the total the store counts is the real total
    assert store._cached_rules == 800
    assert sum(entry.rule_objects for entry in store._cache.values()) == 800
    assert [key[2] for key in store._cache] == ["https://o3.example.com:443", "https://o4.example.com:443"]


async def test_robots_store_answers_rules_a_size_eviction_took_by_fetching_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a cache with room for one file
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_CACHE_MAX_RULES", 500)
    store = _store_of_large_files(400)
    first = await store.rules("j1", "https://a.example.com/", profile=None)
    await store.rules("j1", "https://b.example.com/", profile=None)

    # when
    again = await store.rules("j1", "https://a.example.com/", profile=None)

    # then
    assert first is not None
    assert again is not None
    assert again is not first
    assert store._cached_rules == 400


async def test_robots_store_counts_nothing_for_an_evicted_or_dropped_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given two jobs with one file each and a limit that holds both
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_CACHE_MAX_ORIGINS", 2)
    store = _store_of_large_files(10)
    await store.rules("j1", "https://a.example.com/", profile=None)
    await store.rules("j2", "https://a.example.com/", profile=None)

    # when
    store.drop_job("j1")
    await store.rules("j3", "https://b.example.com/", profile=None)
    await store.rules("j3", "https://c.example.com/", profile=None)

    # then the origin limit also takes the count of the file it evicts
    assert len(store._cache) == 2
    assert store._cached_rules == 20


async def test_a_refused_file_counts_no_rules_in_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_RULES", 1)
    store = _store_of_large_files(5)

    # when
    rules = await store.rules("j1", "https://a.example.com/", profile=None)

    # then
    assert rules is robots_module._DISALLOW_ALL
    assert store._cached_rules == 0


_STEP = robots_module._SITEMAP_PARSE_STEP_CHARS
_ONE_PAGE = "<url><loc>https://example.com/a</loc></url>"


async def test_a_start_tag_spanning_a_whole_parse_step_yields_nothing_and_spends_nothing() -> None:
    # given a well formed sitemap whose second entry has an attribute of two parse steps
    allowance = _allowance(urls=10)
    body = f'<urlset>{_ONE_PAGE}<url a="{"x" * (2 * _STEP)}"><loc>https://example.com/b</loc></url></urlset>'

    # when
    answer = await sitemap_locations(
        body, allowance=allowance, max_nested=1, accept=lambda _u: True, accept_nested=lambda _u: True
    )

    # then
    assert answer == ([], [])
    assert allowance.urls == 10


async def test_a_start_tag_after_multibyte_text_spanning_a_parse_step_is_refused() -> None:
    # given text of two-byte characters before the oversized tag, so bytes and characters differ
    body = (
        f'<urlset>{_ONE_PAGE}<url><lastmod>{"ż" * _STEP}</lastmod><a b="{"x" * (2 * _STEP)}"/></url></urlset>'
    )

    # when
    answer = await _locations(body)

    # then
    assert answer == ([], [])


async def test_a_start_tag_whose_bracket_ends_a_parse_step_is_still_refused() -> None:
    # given a start tag whose opening bracket is the last character of the first step
    start = f"<urlset>{_ONE_PAGE}<url><lastmod>"
    padding = "x" * (_STEP - len(start) - len("</lastmod>") - 1)
    body = f'{start}{padding}</lastmod><a b="{"x" * (2 * _STEP)}"/></url></urlset>'

    # when
    answer = await _locations(body)

    # then
    assert answer == ([], [])


async def test_a_short_start_tag_across_a_parse_step_boundary_parses() -> None:
    # given a start tag that begins near the end of the first step and ends in the second
    padding = "x" * (_STEP - len('<urlset><url a="') - 10)
    body = (
        f'<urlset><url a="{padding}{"y" * 100}"><loc>https://example.com/a</loc></url>'
        f"<url><loc>https://example.com/b</loc></url></urlset>"
    )

    # when
    pages, _ = await _locations(body)

    # then
    assert pages == ["https://example.com/a", "https://example.com/b"]


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        ("<lastmod>", "</lastmod>"),
        ("<!-- ", " -->"),
        ("<?note ", "?>"),
        ("<![CDATA[", "]]>"),
    ],
)
async def test_a_value_longer_than_a_parse_step_outside_a_start_tag_parses(
    opening: str, closing: str
) -> None:
    # given
    long_value = "z" * (3 * _STEP)
    body = f"<urlset><url>{opening}{long_value}{closing}<loc>https://example.com/a</loc></url></urlset>"

    # when
    pages, _ = await _locations(body)

    # then
    assert pages == ["https://example.com/a"]


async def test_sitemap_locations_ignores_a_document_with_a_doctype() -> None:
    # given
    body = (
        '<!DOCTYPE urlset [<!ENTITY a "https://example.com/from-entity">]>'
        "<urlset><url><loc>https://example.com/a</loc></url><url><loc>&a;</loc></url></urlset>"
    )

    # when / then
    assert await _locations(body) == ([], [])


async def test_sitemap_locations_drops_an_address_longer_than_a_url_can_be() -> None:
    # given
    too_long = "https://example.com/" + "a" * MAX_URL_LENGTH
    much_too_long = "https://example.com/" + "a" * (3 * MAX_URL_LENGTH)
    body = (
        f"<urlset><url><loc>{too_long}</loc></url>"
        f"<url><loc>{much_too_long}</loc></url>"
        "<url><loc>https://example.com/short</loc></url></urlset>"
    )

    # when / then
    assert await _locations(body) == (["https://example.com/short"], [])


async def test_sitemap_locations_keeps_a_longest_address_inside_whitespace() -> None:
    # given
    longest = "https://example.com/" + "a" * (MAX_URL_LENGTH - len("https://example.com/"))
    body = f"<urlset><url><loc>\n  {longest}\n  </loc></url></urlset>"

    # when / then
    assert await _locations(body) == ([longest], [])


async def test_sitemap_locations_joins_the_pieces_of_one_address_and_reads_entities() -> None:
    # given
    body = "<urlset><url><loc>https://example.com/a?x=1&amp;y=<![CDATA[2]]></loc></url></urlset>"

    # when / then
    assert await _locations(body) == (["https://example.com/a?x=1&y=2"], [])


async def test_sitemap_locations_reads_one_address_per_entry_and_only_the_loc_of_the_entry() -> None:
    # given an entry with two locs, an image loc one level deeper, and a loc directly under the root
    body = (
        "<urlset>"
        "<loc>https://example.com/under-root</loc>"
        "<url><loc>  </loc><loc>https://example.com/first</loc><loc>https://example.com/second</loc>"
        "<image><loc>https://example.com/image</loc></image></url>"
        "</urlset>"
    )

    # when / then
    assert await _locations(body) == (["https://example.com/first"], [])


async def test_sitemap_locations_reads_namespaced_documents() -> None:
    # given
    namespace = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    urlset = f"<urlset {namespace}><url><loc>https://example.com/a</loc></url></urlset>"
    index = (
        f"<sitemapindex {namespace}><sitemap><loc>https://example.com/s.xml</loc></sitemap></sitemapindex>"
    )

    # when / then
    assert await _locations(urlset) == (["https://example.com/a"], [])
    assert await _locations(index) == ([], ["https://example.com/s.xml"])


async def test_sitemap_locations_ignores_a_loc_of_another_namespace() -> None:
    # given
    body = '<urlset xmlns:x="urn:x"><url><x:loc>https://example.com/other</x:loc></url></urlset>'

    # when / then
    assert await _locations(body) == ([], [])


async def test_sitemap_locations_stops_at_the_address_limit_and_reads_no_further() -> None:
    # given two addresses, then more than one parse step of entries and broken markup at the very end
    filler = "<url><loc>https://example.com/filler</loc></url>" * 20000
    body = (
        "<urlset><url><loc>https://example.com/a</loc></url>"
        "<url><loc>https://example.com/b</loc></url>" + filler + "<broken"
    )
    allowance = _allowance(urls=2)
    asked: list[str] = []

    def accept(url: str) -> bool:
        asked.append(url)
        return True

    # when
    pages, nested = await sitemap_locations(
        body, allowance=allowance, max_nested=10, accept=accept, accept_nested=lambda _url: True
    )

    # then the limit stopped the parser before the broken end, and accept never ran past it
    assert pages == ["https://example.com/a", "https://example.com/b"]
    assert nested == []
    assert allowance.urls == 0
    assert asked == pages


async def test_sitemap_locations_counts_only_accepted_addresses_against_the_limit() -> None:
    # given
    allowance = _allowance(urls=5)
    body = (
        "<urlset><url><loc>https://example.com/skip</loc></url>"
        "<url><loc>https://example.com/keep</loc></url></urlset>"
    )

    # when
    pages, _ = await sitemap_locations(
        body,
        allowance=allowance,
        max_nested=10,
        accept=lambda url: url.endswith("/keep"),
        accept_nested=lambda _url: True,
    )

    # then
    assert pages == ["https://example.com/keep"]
    assert allowance.urls == 4


async def test_sitemap_locations_refunds_the_allowance_of_a_broken_document() -> None:
    # given addresses followed by markup that never closes
    allowance = _allowance(urls=5)

    # when
    pages, nested = await sitemap_locations(
        "<urlset><url><loc>https://example.com/a</loc></url>",
        allowance=allowance,
        max_nested=10,
        accept=lambda _url: True,
        accept_nested=lambda _url: True,
    )

    # then
    assert (pages, nested) == ([], [])
    assert allowance.urls == 5


async def test_sitemap_locations_spends_no_address_on_a_broken_index() -> None:
    # given
    allowance = _allowance(urls=5)

    # when
    answer = await sitemap_locations(
        "<sitemapindex><sitemap><loc>https://example.com/a.xml</loc></sitemap>",
        allowance=allowance,
        max_nested=10,
        accept=lambda _url: True,
        accept_nested=lambda _url: True,
    )

    # then
    assert answer == ([], [])
    assert allowance.urls == 5


async def test_sitemap_locations_keeps_distinct_nested_sitemaps_up_to_the_limit_it_was_given() -> None:
    # given an index with a duplicate, a refused entry, then more than one parse step and broken markup
    filler = "<sitemap><loc>https://example.com/filler.xml</loc></sitemap>" * 20000
    body = (
        "<sitemapindex>"
        "<sitemap><loc>https://example.com/refused.xml</loc></sitemap>"
        "<sitemap><loc>https://example.com/a.xml</loc></sitemap>"
        "<sitemap><loc>https://example.com/a.xml</loc></sitemap>"
        "<sitemap><loc>https://example.com/b.xml</loc></sitemap>" + filler + "<broken"
    )

    # when
    pages, nested = await sitemap_locations(
        body,
        allowance=_allowance(),
        max_nested=2,
        accept=lambda _url: True,
        accept_nested=lambda url: "refused" not in url,
    )

    # then
    assert pages == []
    assert nested == ["https://example.com/a.xml", "https://example.com/b.xml"]


async def test_sitemap_locations_gives_the_event_loop_a_turn_during_a_large_document() -> None:
    # given more than three parse steps of entries and a task counting its turns
    body = "<urlset>" + "<url><loc>https://example.com/x</loc></url>" * 12000 + "</urlset>"
    turns = 0
    stop = asyncio.Event()

    async def count_turns() -> None:
        nonlocal turns
        while not stop.is_set():
            turns += 1
            await asyncio.sleep(0)

    ticker = asyncio.create_task(count_turns())

    # when
    pages, _ = await _locations(body)
    stop.set()
    await ticker

    # then
    assert len(pages) == 12000
    assert turns >= 4


async def test_collect_sitemap_urls_never_queues_more_sitemaps_than_documents_remain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given one index naming many sitemaps and two more named by robots.txt
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        return _index_of(100) if url.endswith("index.xml") else "<urlset/>"

    allowance = _allowance(documents=3)
    named = ["https://example.com/one.xml", "https://example.com/two.xml", "https://example.com/index.xml"]

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        await collect_sitemap_urls(
            [*named, "https://example.com/beyond.xml", "https://example.com/beyond-2.xml"],
            fetch,
            allowance=allowance,
        )

    # then the two addresses past the limit and every nested sitemap are left out
    assert fetched == list(reversed(named))
    assert allowance.documents == 0
    assert "sitemaps not fetched" in caplog.text


async def test_collect_sitemap_urls_fetches_a_repeated_sitemap_once() -> None:
    # given a sitemap named twice and an index that names a sitemap already waiting
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        if url.endswith("index.xml"):
            return "<sitemapindex><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>"
        return "<urlset/>"

    # when
    await collect_sitemap_urls(
        ["https://example.com/a.xml", "https://example.com/a.xml", "https://example.com/index.xml"],
        fetch,
        allowance=_allowance(documents=50),
    )

    # then
    assert fetched == ["https://example.com/index.xml", "https://example.com/a.xml"]


async def test_collect_sitemap_urls_logs_no_address_query_and_no_query_in_the_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a failing sitemap whose address and error text carry a secret query
    async def fetch(url: str) -> str:
        raise RuntimeError("failed at https://example.com/s.xml?token=in-the-error")

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        await collect_sitemap_urls(
            ["https://example.com/s.xml?token=in-the-address"], fetch, allowance=_allowance(documents=5)
        )

    # then
    assert "https://example.com/s.xml" in caplog.text
    assert "token=" not in caplog.text


def _sitemap_store(fetched: list[tuple[str, str | None]], robots_body: str) -> RobotsStore:
    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, robots_body)

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        fetched.append((url, profile))
        return f"<urlset><url><loc>{url}-page</loc></url></urlset>"

    return RobotsStore(robots_fetch, sitemap_fetch)


async def test_robots_store_counts_sitemap_documents_per_job_across_subdomains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a limit of three documents and origins that each name two sitemaps
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_MAX_DOCUMENTS", 3)
    fetched: list[tuple[str, str | None]] = []
    store = _sitemap_store(
        fetched, "Sitemap: https://example.com/one.xml\nSitemap: https://example.com/two.xml\n"
    )

    # when two origins of one job and one origin of another job are read
    first = await store.sitemap_seed_urls("j1", "https://a.example.com/", profile=None, max_urls=100)
    second = await store.sitemap_seed_urls("j1", "https://b.example.com/", profile=None, max_urls=100)
    other_job = await store.sitemap_seed_urls("j2", "https://a.example.com/", profile=None, max_urls=100)

    # then job j1 fetched three documents in all, and job j2 has its own count
    assert len(first) == 2
    assert len(second) == 1
    assert len(other_job) == 2
    assert len(fetched) == 5


async def test_robots_store_counts_queued_addresses_per_job_across_subdomains() -> None:
    # given
    fetched: list[tuple[str, str | None]] = []
    store = _sitemap_store(fetched, "Sitemap: https://example.com/one.xml\n")

    # when two origins of one job share a budget of one address
    first = await store.sitemap_seed_urls("j1", "https://a.example.com/", profile=None, max_urls=1)
    second = await store.sitemap_seed_urls("j1", "https://b.example.com/", profile=None, max_urls=1)

    # then
    assert first == ["https://example.com/one.xml-page"]
    assert second == []


async def test_robots_store_holds_the_job_limits_for_origins_read_at_the_same_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given many origins of one job that name large sitemaps and a limit of two documents and three pages
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_MAX_DOCUMENTS", 2)
    sitemap = "<urlset>" + "<url><loc>https://example.com/page</loc></url>" * 5000 + "</urlset>"
    fetched: list[str] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(
            200, "Sitemap: https://example.com/one.xml\nSitemap: https://example.com/two.xml\n"
        )

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        fetched.append(url)
        await asyncio.sleep(0)
        return sitemap

    store = RobotsStore(robots_fetch, sitemap_fetch)

    # when
    answers = await asyncio.gather(
        *(
            store.sitemap_seed_urls("j1", f"https://s{n}.example.com/", profile=None, max_urls=3)
            for n in range(6)
        )
    )

    # then the job as a whole spent no more than its limits
    assert len(fetched) == 2
    assert sum(len(answer) for answer in answers) == 3


async def test_robots_store_drops_a_foreign_sitemap_when_the_job_stays_on_its_seeds() -> None:
    # given
    fetched: list[tuple[str, str | None]] = []
    store = _sitemap_store(
        fetched,
        "Sitemap: https://www.example.com/own.xml\n"
        "Sitemap: https://other.example.org/foreign.xml\n"
        "Sitemap: http://[broken\n",
    )

    # when
    await store.sitemap_seed_urls(
        "j1", "https://example.com/", profile="alice", max_urls=10, seed_domains=frozenset({"example.com"})
    )

    # then
    assert fetched == [("https://www.example.com/own.xml", "alice")]


async def test_robots_store_drops_a_nested_foreign_sitemap_when_the_job_stays_on_its_seeds() -> None:
    # given
    fetched: list[str] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, "Sitemap: https://example.com/index.xml\n")

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        fetched.append(url)
        if url.endswith("index.xml"):
            return (
                "<sitemapindex><sitemap><loc>https://example.org/foreign.xml</loc></sitemap>"
                "<sitemap><loc>https://example.com/own.xml</loc></sitemap></sitemapindex>"
            )
        return "<urlset/>"

    store = RobotsStore(robots_fetch, sitemap_fetch)

    # when
    await store.sitemap_seed_urls(
        "j1", "https://example.com/", profile=None, max_urls=10, seed_domains=frozenset({"example.com"})
    )

    # then
    assert fetched == ["https://example.com/index.xml", "https://example.com/own.xml"]


async def test_robots_store_sends_no_stored_session_to_a_sitemap_of_another_domain() -> None:
    # given a job that may leave its seeds and a robots.txt naming sitemaps here and elsewhere
    fetched: list[tuple[str, str | None]] = []
    store = _sitemap_store(
        fetched,
        "Sitemap: https://other.example.org/foreign.xml\nSitemap: https://www.example.com/own.xml\n",
    )

    # when
    await store.sitemap_seed_urls("j1", "https://example.com/", profile="alice", max_urls=10)

    # then the sitemap of the same registrable domain keeps the profile and the other gets none
    assert fetched == [
        ("https://www.example.com/own.xml", "alice"),
        ("https://other.example.org/foreign.xml", robots_module._NO_SESSION_PROFILE),
    ]


async def test_the_no_session_profile_finds_no_cookies_even_where_the_default_profile_has_some(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a stored login under the default profile, the profile a None argument falls back to
    from src.reader.cloudflare.cookie_manager import cookie_manager

    stored = {
        "auth": {"storage_state": {"cookies": [{"name": "sid", "value": "secret"}]}, "expires_at": None},
    }

    async def load_record(_domain: str, profile: str) -> dict[str, Any] | None:
        return stored if profile == settings.SESSION_DEFAULT_PROFILE else None

    monkeypatch.setattr(cookie_manager, "_load_record", load_record)

    # when
    cookies = await cookie_manager.get_flat_cookies(
        "https://other.example.org/foreign.xml", robots_module._NO_SESSION_PROFILE
    )

    # then the reserved name matches no profile a session can be stored under
    assert cookies == {}
    assert not is_valid_profile(robots_module._NO_SESSION_PROFILE)


async def test_the_rule_parse_runs_off_the_event_loop_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    loop_thread = threading.current_thread()
    parse_threads: list[threading.Thread] = []
    real_parse = Protego.parse

    def spying_parse(content: str) -> Any:
        parse_threads.append(threading.current_thread())
        return real_parse(content)

    monkeypatch.setattr(Protego, "parse", spying_parse)

    async def fetch(_url: str, _profile: str | None) -> RobotsFetch:
        return ROBOTS_FILE

    # when
    rules = await load_rules("https://example.com/page", fetch, profile=None)

    # then
    assert rules is not None
    assert parse_threads
    assert parse_threads[0] is not loop_thread


async def test_a_file_over_the_rule_limit_is_refused_before_any_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_RULES", 1)
    spy = AsyncMock()
    monkeypatch.setattr(asyncio, "to_thread", spy)
    body = "User-agent: *\nDisallow: /a\nDisallow: /b\n"

    async def fetch(_url: str, _profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, body)

    # when
    rules = await load_rules("https://example.com/page", fetch, profile=None)

    # then
    assert rules is robots_module._DISALLOW_ALL
    spy.assert_not_awaited()
