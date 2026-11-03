"""Task 4.8: ALLOWED_PRIVATE_HOSTS read with CsvTuple, empty by default (owner answer 67.3)."""

import asyncio
import os
import socket
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri

from src.config.config import Settings


def test_allowed_private_hosts_empty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("ALLOWED_PRIVATE_HOSTS", raising=False)

    # when
    settings = Settings()

    # then
    assert settings.ALLOWED_PRIVATE_HOSTS == ()


def test_allowed_private_hosts_read_from_comma_separated_string() -> None:
    # given
    env = {"ALLOWED_PRIVATE_HOSTS": "e2e-fake-site, internal.example"}

    # when
    with patch.dict(os.environ, env, clear=False):
        settings = Settings()

    # then
    assert settings.ALLOWED_PRIVATE_HOSTS == ("e2e-fake-site", "internal.example")


@pytest.mark.asyncio
async def test_host_on_allow_list_read_with_no_address_check() -> None:
    # given
    policy = FetchPolicy(allowed_hosts=("e2e-fake-site",), file_root=None, max_redirect_hops=10)

    # when
    target = await check_fetch_uri("http://e2e-fake-site:7021/page", policy)

    # then
    assert target.host == "e2e-fake-site"
    assert target.addresses == ()


@pytest.mark.asyncio
async def test_same_address_off_list_host_refused_with_unsafe_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    async def fake_getaddrinfo(host: object, port: object, **kwargs: object) -> list[tuple[Any, ...]]:
        # when
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.9.9.9", 0))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    policy = FetchPolicy(allowed_hosts=("e2e-fake-site",), file_root=None, max_redirect_hops=10)

    # when
    with pytest.raises(UnsafeUriError, match="non-public"):
        await check_fetch_uri("http://other.example/page", policy)

    # then
    assert policy.allowed_hosts == ("e2e-fake-site",)


def test_production_settings_leave_allow_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("ALLOWED_PRIVATE_HOSTS", raising=False)
    monkeypatch.delenv("WEB_HUNTER_ALLOWED_PRIVATE_HOSTS", raising=False)
    root = Path(__file__).resolve().parents[4]
    dev_compose = root / "compose.ascend-web-hunter.yaml"
    standalone_compose = root / "apps/ascend-web-hunter/deploy-standalone/compose.yaml"
    env_files = [
        root / ".env.example",
        root / "apps/ascend-web-hunter/deploy-standalone/.env.example",
    ]

    # when
    settings = Settings()
    dev_lines = [
        line.strip().lstrip("- ").strip() for line in dev_compose.read_text(encoding="utf-8").splitlines()
    ]
    allow_lines = [line for line in dev_lines if line.startswith("ALLOWED_PRIVATE_HOSTS=")]
    standalone_text = standalone_compose.read_text(encoding="utf-8")

    # then
    assert settings.ALLOWED_PRIVATE_HOSTS == ()
    assert allow_lines == ["ALLOWED_PRIVATE_HOSTS=${WEB_HUNTER_ALLOWED_PRIVATE_HOSTS:-}"]
    for path in env_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped.startswith("WEB_HUNTER_ALLOWED_PRIVATE_HOSTS="):
                assert stripped.split("=", 1)[1].strip().strip("\"'") == ""
            assert not stripped.startswith("ALLOWED_PRIVATE_HOSTS=")
    assert "ALLOWED_PRIVATE_HOSTS" not in standalone_text
    assert "WEB_HUNTER_ALLOWED_PRIVATE_HOSTS" not in standalone_text
