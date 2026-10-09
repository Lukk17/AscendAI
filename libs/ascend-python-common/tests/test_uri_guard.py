import asyncio
import socket
from pathlib import Path

import pytest
from aiohttp.abc import AbstractResolver, ResolveResult
from pydantic import Field

from ascend_python_common.settings import McpFetchSettings, RateLimit, ServiceSettings
from ascend_python_common.uri_guard import (
    MAX_REDIRECT_HOPS,
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    UnsafeUriError,
    check_fetch_uri,
    follow_guarded_redirects,
)
from ascend_python_common.uri_guard_aiohttp import PinnedResolver, guarded_get, pinned_scope

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_ALT = "93.184.216.35"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


class _FetchSettings(ServiceSettings, McpFetchSettings):
    API_PORT: int = Field(default=7022, ge=1, le=65535)
    RATE_LIMIT_DEFAULT: RateLimit = Field(default="600/minute")
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    FETCH_MAX_REDIRECT_HOPS: int = Field(default=10, ge=0)


@pytest.fixture(autouse=True)
def _clean_fetch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    for name in ("ALLOWED_PRIVATE_HOSTS", "MCP_FILE_URI_ROOT", "FETCH_MAX_REDIRECT_HOPS"):
        monkeypatch.delenv(name, raising=False)


async def _fake_dns(
    monkeypatch: pytest.MonkeyPatch,
    ips: list[str] | Exception,
    seen: list[tuple[str, int]],
) -> None:
    # given
    loop = asyncio.get_running_loop()

    async def fake(
        host: str,
        port: int,
        *args: object,
        **kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        # when
        seen.append((host, port))
        if isinstance(ips, Exception):
            raise ips
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    # then
    monkeypatch.setattr(loop, "getaddrinfo", fake)
    assert callable(loop.getaddrinfo)


def test_max_redirect_hops_is_ten() -> None:
    # given
    expected = 10
    # when
    actual = MAX_REDIRECT_HOPS
    # then
    assert actual == expected


@pytest.mark.parametrize(
    "uri",
    [
        "ftp://example.com/song.mp3",
        "data:text/plain,hello",
        "example.com/without-scheme",
        "C:\\Windows\\file.mp3",
        "gopher://example.com/song.mp3",
    ],
)
async def test_each_refused_scheme(uri: str) -> None:
    # given
    policy = FetchPolicy()
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri(uri, policy)
    # then
    assert "scheme" in str(excinfo.value)


async def test_uri_that_does_not_parse_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    def _boom(value: str) -> object:
        raise ValueError("bad uri")

    monkeypatch.setattr("ascend_python_common.uri_guard.urlparse", _boom)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("http://example.com/", FetchPolicy())
    # then
    assert "parse" in str(excinfo.value)


@pytest.mark.parametrize("uri", ["http://example.com:99999/", "http://example.com:abc/"])
async def test_invalid_port_is_refused(uri: str) -> None:
    # given
    policy = FetchPolicy()
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri(uri, policy)
    # then
    assert "port" in str(excinfo.value)


async def test_zero_port_is_refused() -> None:
    # given
    policy = FetchPolicy()
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("http://example.com:0/", policy)
    # then
    assert "port" in str(excinfo.value)


async def test_user_info_in_http_uri_is_refused() -> None:
    # given
    policy = FetchPolicy()
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("https://user:secret@example.com/a.mp3", policy)
    # then
    assert "secret" not in str(excinfo.value)
    assert "user:secret" not in str(excinfo.value)


async def test_uri_without_host_is_refused() -> None:
    # given
    policy = FetchPolicy()
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("http:///no-host", policy)
    # then
    assert "host" in str(excinfo.value)


async def test_host_that_does_not_resolve_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, socket.gaierror("nope"), seen)
    # when
    with pytest.raises(UnsafeUriError):
        await check_fetch_uri("http://missing.invalid/", FetchPolicy())
    # then
    assert seen == [("missing.invalid", 80)]


async def test_lookup_with_no_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [], seen)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("https://example.com/", FetchPolicy())
    # then
    assert "address" in str(excinfo.value)


async def test_lookup_answer_that_is_not_an_ip_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, ["not-an-ip"], seen)
    # when
    with pytest.raises(UnsafeUriError):
        await check_fetch_uri("https://example.com/", FetchPolicy())
    # then
    assert seen == [("example.com", 443)]


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "255.255.255.255",
        "::1",
        "fe80::1",
    ],
)
async def test_non_public_address_is_refused(ip: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [ip], seen)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("https://example.com/", FetchPolicy())
    # then
    assert ip not in str(excinfo.value)


async def test_one_public_and_one_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4, "10.0.0.5"], seen)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("https://example.com/", FetchPolicy())
    # then
    assert "10.0.0.5" not in str(excinfo.value)
    assert PUBLIC_V4 not in str(excinfo.value)


async def test_public_host_passes_with_its_checked_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4, PUBLIC_V4_ALT], seen)
    # when
    target = await check_fetch_uri("https://example.com/article", FetchPolicy())
    # then
    assert target == FetchTarget(
        url="https://example.com/article",
        host="example.com",
        port=443,
        addresses=(PUBLIC_V4, PUBLIC_V4_ALT),
    )


async def test_lookup_uses_the_uri_port(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    # when
    target = await check_fetch_uri("https://example.com:8443/", FetchPolicy())
    # then
    assert target.port == 8443
    assert seen == [("example.com", 8443)]


async def test_lookup_uses_the_scheme_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    # when
    target = await check_fetch_uri("http://example.com/", FetchPolicy())
    # then
    assert target.port == 80
    assert seen == [("example.com", 80)]


async def test_duplicate_addresses_are_kept_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4, PUBLIC_V4], seen)
    # when
    target = await check_fetch_uri("https://example.com/", FetchPolicy())
    # then
    assert target.addresses == (PUBLIC_V4,)


async def test_allowed_host_with_private_address_passes_without_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, ["10.0.0.5"], seen)
    policy = FetchPolicy(allowed_hosts=("internal.example",))
    # when
    target = await check_fetch_uri("http://internal.example/x", policy)
    # then
    assert target.host == "internal.example"
    assert target.addresses == ()
    assert seen == []


async def test_lookup_runs_without_blocking_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    def _boom(host: str, port: int, *args: object, **kwargs: object) -> object:
        raise AssertionError("blocking lookup used")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    # when
    target = await check_fetch_uri("https://example.com/", FetchPolicy())
    # then
    assert target.addresses == (PUBLIC_V4,)


async def test_ip_literal_carries_no_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, AssertionError("must not resolve"), seen)
    # when
    target = await check_fetch_uri("http://93.184.216.34/song.mp3", FetchPolicy())
    # then
    assert target.addresses == ()
    assert seen == []


async def test_private_ip_literal_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, AssertionError("must not resolve"), seen)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("http://10.0.0.5/secret", FetchPolicy())
    # then
    assert "10.0.0.5" not in str(excinfo.value)
    assert seen == []


async def test_file_uri_without_root_is_refused() -> None:
    # given
    policy = FetchPolicy()
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri("file:///srv/audio/a.mp3", policy)
    # then
    assert "file" in str(excinfo.value)


async def test_file_uri_with_dot_dot_outside_root_is_refused(tmp_path: Path) -> None:
    # given
    root = tmp_path / "root"
    root.mkdir()
    policy = FetchPolicy(file_root=root)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri(root.as_uri() + "/../outside.txt", policy)
    # then
    assert str(root) not in str(excinfo.value)


async def test_symlink_inside_root_pointing_outside_is_refused(tmp_path: Path) -> None:
    # given
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (root / "link.txt").symlink_to(outside)
    policy = FetchPolicy(file_root=root)
    # when
    with pytest.raises(UnsafeUriError) as excinfo:
        await check_fetch_uri(root.as_uri() + "/link.txt", policy)
    # then
    assert "outside" not in str(excinfo.value)


async def test_file_inside_root_passes(tmp_path: Path) -> None:
    # given
    root = tmp_path / "root"
    root.mkdir()
    inner = root / "a.mp3"
    inner.write_text("audio")
    policy = FetchPolicy(file_root=root)
    # when
    target = await check_fetch_uri(root.as_uri() + "/a.mp3", policy)
    # then
    assert target.file_path == inner.resolve()
    assert target.host is None


def test_fetch_policy_from_mixin_names_hosts_root_and_hops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given
    monkeypatch.setenv("ALLOWED_PRIVATE_HOSTS", "internal.example")
    monkeypatch.setenv("MCP_FILE_URI_ROOT", str(tmp_path))
    monkeypatch.setenv("FETCH_MAX_REDIRECT_HOPS", "0")
    # when
    policy = _FetchSettings().fetch_policy()
    # then
    assert policy == FetchPolicy(
        allowed_hosts=("internal.example",),
        file_root=tmp_path,
        max_redirect_hops=0,
    )


def test_fetch_policy_without_root_leaves_file_guard_disabled() -> None:
    # given
    settings = _FetchSettings()
    # when
    policy = settings.fetch_policy()
    # then
    assert policy.file_root is None
    assert policy.max_redirect_hops == 10
    assert policy.allowed_hosts == ()


class _StaticResolver(AbstractResolver):
    def __init__(self, hosts: list[str]) -> None:
        # given
        self.hosts = hosts
        self.closed = False

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        # when
        return [
            {
                "hostname": host,
                "host": ip,
                "port": port,
                "family": int(socket.AF_INET),
                "proto": 0,
                "flags": 0,
            }
            for ip in self.hosts
        ]

    async def close(self) -> None:
        # when
        self.closed = True
        # then
        assert self.closed


async def test_pinned_resolver_keeps_the_first_public_answer() -> None:
    # given
    inner = _StaticResolver(["127.0.0.1"])
    resolver = PinnedResolver(inner)
    target = FetchTarget(
        url="https://public.example/",
        host="public.example",
        port=443,
        addresses=(PUBLIC_V4,),
    )
    # when
    with pinned_scope(target):
        found = await resolver.resolve("public.example", 443)
    # then
    assert [entry["host"] for entry in found] == [PUBLIC_V4]


async def test_pinned_resolver_reports_ipv6_family() -> None:
    # given
    inner = _StaticResolver(["127.0.0.1"])
    resolver = PinnedResolver(inner)
    target = FetchTarget(
        url="https://public.example/",
        host="public.example",
        port=443,
        addresses=(PUBLIC_V6,),
    )
    # when
    with pinned_scope(target):
        found = await resolver.resolve("public.example", 443)
    # then
    assert [entry["family"] for entry in found] == [int(socket.AF_INET6)]


async def test_pinned_resolver_delegates_without_a_pin() -> None:
    # given
    inner = _StaticResolver(["127.0.0.1"])
    resolver = PinnedResolver(inner)
    # when
    found = await resolver.resolve("other.example", 443)
    # then
    assert [entry["host"] for entry in found] == ["127.0.0.1"]


async def test_pinned_resolver_delegates_for_another_host() -> None:
    # given
    inner = _StaticResolver(["127.0.0.1"])
    resolver = PinnedResolver(inner)
    target = FetchTarget(
        url="https://public.example/",
        host="public.example",
        port=443,
        addresses=(PUBLIC_V4,),
    )
    # when
    with pinned_scope(target):
        found = await resolver.resolve("other.example", 443)
    # then
    assert [entry["host"] for entry in found] == ["127.0.0.1"]


async def test_pinned_resolver_delegates_for_an_ip_literal_target() -> None:
    # given
    inner = _StaticResolver(["127.0.0.1"])
    resolver = PinnedResolver(inner)
    target = FetchTarget(url="http://93.184.216.34/", host="93.184.216.34", port=80)
    # when
    with pinned_scope(target):
        found = await resolver.resolve("93.184.216.34", 80)
    # then
    assert [entry["host"] for entry in found] == ["127.0.0.1"]


async def test_pinned_resolver_close_closes_the_wrapped_resolver() -> None:
    # given
    inner = _StaticResolver(["127.0.0.1"])
    resolver = PinnedResolver(inner)
    # when
    await resolver.close()
    # then
    assert inner.closed


class _HopRoutes:
    def __init__(self, table: dict[str, tuple[int, str | None, str]]) -> None:
        # given
        self.table = table
        self.calls: list[str] = []

    async def __call__(self, target: FetchTarget) -> HopAnswer[str]:
        # when
        self.calls.append(target.url)
        status, location, body = self.table[target.url]
        return HopAnswer(status=status, location=location, answer=body)


async def _public_target(monkeypatch: pytest.MonkeyPatch, url: str) -> FetchTarget:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    # when
    target = await check_fetch_uri(url, FetchPolicy())
    # then
    assert target.addresses == (PUBLIC_V4,)
    return target


async def test_redirect_to_private_address_raises_and_is_never_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    first = await _public_target(monkeypatch, "https://public.example/a.mp3")
    send = _HopRoutes({"https://public.example/a.mp3": (302, "http://10.0.0.5/a.mp3", "")})
    # when
    with pytest.raises(UnsafeUriError):
        await follow_guarded_redirects(first, FetchPolicy(), send)
    # then
    assert send.calls == ["https://public.example/a.mp3"]


async def test_relative_location_resolves_against_its_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    first = await _public_target(monkeypatch, "https://public.example/a.mp3")
    send = _HopRoutes(
        {
            "https://public.example/a.mp3": (302, "/b.mp3", ""),
            "https://public.example/b.mp3": (200, None, "audio"),
        }
    )
    # when
    final = await follow_guarded_redirects(first, FetchPolicy(), send)
    # then
    assert final.answer == "audio"
    assert send.calls == [
        "https://public.example/a.mp3",
        "https://public.example/b.mp3",
    ]


async def test_file_location_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    policy = FetchPolicy(file_root=tmp_path)
    first = await check_fetch_uri("https://public.example/a.mp3", policy)
    send = _HopRoutes({"https://public.example/a.mp3": (302, "file:///etc/passwd", "")})
    # when
    with pytest.raises(UnsafeUriError):
        await follow_guarded_redirects(first, policy, send)
    # then
    assert send.calls == ["https://public.example/a.mp3"]


async def test_redirect_hop_to_allowed_host_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    policy = FetchPolicy(allowed_hosts=("internal.example",))
    first = await check_fetch_uri("https://public.example/a.mp3", policy)
    send = _HopRoutes(
        {
            "https://public.example/a.mp3": (302, "http://internal.example/b.mp3", ""),
            "http://internal.example/b.mp3": (200, None, "audio"),
        }
    )
    # when
    final = await follow_guarded_redirects(first, policy, send)
    # then
    assert final.answer == "audio"
    assert send.calls == [
        "https://public.example/a.mp3",
        "http://internal.example/b.mp3",
    ]


async def test_loop_hands_back_the_last_3xx_after_max_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    first = await _public_target(monkeypatch, "https://public.example/a")
    send = _HopRoutes(
        {
            "https://public.example/a": (302, "/b", ""),
            "https://public.example/b": (302, "/c", ""),
            "https://public.example/c": (200, None, "audio"),
        }
    )
    # when
    final = await follow_guarded_redirects(first, FetchPolicy(max_redirect_hops=1), send)
    # then
    assert final.status == 302
    assert send.calls == [
        "https://public.example/a",
        "https://public.example/b",
    ]


async def test_zero_max_hops_hands_back_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    first = await _public_target(monkeypatch, "https://public.example/a")
    expected = HopAnswer(status=302, location="/b", answer="")
    calls: list[str] = []

    async def send(target: FetchTarget) -> HopAnswer[str]:
        # when
        calls.append(target.url)
        return expected

    # when
    final = await follow_guarded_redirects(first, FetchPolicy(max_redirect_hops=0), send)
    # then
    assert final is expected
    assert calls == ["https://public.example/a"]


async def test_3xx_without_location_is_handed_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    first = await _public_target(monkeypatch, "https://public.example/a")
    send = _HopRoutes({"https://public.example/a": (302, None, "")})
    # when
    final = await follow_guarded_redirects(first, FetchPolicy(), send)
    # then
    assert final.status == 302
    assert send.calls == ["https://public.example/a"]


async def test_non_redirect_answer_is_handed_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    first = await _public_target(monkeypatch, "https://public.example/a")
    send = _HopRoutes({"https://public.example/a": (200, None, "audio")})
    # when
    final = await follow_guarded_redirects(first, FetchPolicy(), send)
    # then
    assert final.answer == "audio"
    assert send.calls == ["https://public.example/a"]


class _FakeResponse:
    def __init__(self, url: str, status: int, location: str | None) -> None:
        # given
        self.url = url
        self.status = status
        self.headers = {"Location": location} if location is not None else {}
        self.released = False

    def release(self) -> None:
        # when
        self.released = True
        # then
        assert self.released


class _FakeSession:
    def __init__(self, table: dict[str, tuple[int, str | None]]) -> None:
        # given
        self.table = table
        self.calls: list[str] = []
        self.made: list[_FakeResponse] = []

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        # when
        self.calls.append(url)
        assert kwargs.get("allow_redirects") is False
        status, location = self.table[url]
        response = _FakeResponse(url, status, location)
        self.made.append(response)
        return response


async def test_guarded_get_follows_a_relative_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    session = _FakeSession(
        {
            "https://public.example/a.mp3": (302, "/b.mp3"),
            "https://public.example/b.mp3": (200, None),
        }
    )
    # when
    async with guarded_get(session, "https://public.example/a.mp3", FetchPolicy()) as response:  # type: ignore[arg-type]
        observed = (response.status, str(response.url))
    # then
    assert observed == (200, "https://public.example/b.mp3")
    assert session.calls == [
        "https://public.example/a.mp3",
        "https://public.example/b.mp3",
    ]


async def test_guarded_get_refuses_a_private_redirect_without_sending_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    session = _FakeSession({"https://public.example/a.mp3": (302, "http://10.0.0.5/a.mp3")})
    # when
    with pytest.raises(UnsafeUriError):
        async with guarded_get(session, "https://public.example/a.mp3", FetchPolicy()):  # type: ignore[arg-type]
            raise AssertionError("must not yield")
    # then
    assert session.calls == ["https://public.example/a.mp3"]
    assert session.made[0].released


async def test_guarded_get_with_zero_hops_hands_back_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    session = _FakeSession({"https://public.example/a.mp3": (302, "/b.mp3")})
    # when
    async with guarded_get(
        session,  # type: ignore[arg-type]
        "https://public.example/a.mp3",
        FetchPolicy(max_redirect_hops=0),
    ) as response:
        observed = response.status
    # then
    assert observed == 302
    assert session.calls == ["https://public.example/a.mp3"]


async def test_guarded_get_refuses_a_file_redirect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    session = _FakeSession({"https://public.example/a.mp3": (302, "file:///etc/passwd")})
    # when
    with pytest.raises(UnsafeUriError):
        async with guarded_get(
            session,  # type: ignore[arg-type]
            "https://public.example/a.mp3",
            FetchPolicy(file_root=tmp_path),
        ):
            raise AssertionError("must not yield")
    # then
    assert session.calls == ["https://public.example/a.mp3"]


async def test_guarded_get_hands_back_a_3xx_without_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    session = _FakeSession({"https://public.example/a.mp3": (302, None)})
    # when
    async with guarded_get(session, "https://public.example/a.mp3", FetchPolicy()) as response:  # type: ignore[arg-type]
        observed = response.status
    # then
    assert observed == 302
    assert session.calls == ["https://public.example/a.mp3"]


async def test_guarded_get_hands_back_a_direct_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[tuple[str, int]] = []
    await _fake_dns(monkeypatch, [PUBLIC_V4], seen)
    session = _FakeSession({"https://public.example/a.mp3": (200, None)})
    # when
    async with guarded_get(session, "https://public.example/a.mp3", FetchPolicy()) as response:  # type: ignore[arg-type]
        observed = (response.status, str(response.url))
    # then
    assert observed == (200, "https://public.example/a.mp3")
