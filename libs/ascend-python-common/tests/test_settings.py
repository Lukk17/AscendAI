from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import Field, ValidationError

from ascend_python_common.settings import (
    CsvTuple,
    LogLevel,
    McpFetchSettings,
    RateLimit,
    ServiceSettings,
)


class _TestSettings(ServiceSettings):
    API_PORT: int = Field(default=7022, ge=1, le=65535)
    RATE_LIMIT_DEFAULT: RateLimit = Field(default="600/minute")


class _TestFetchSettings(_TestSettings, McpFetchSettings):
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    FETCH_MAX_REDIRECT_HOPS: int = Field(default=10, ge=0)


_SETTINGS_ENV_VARS: tuple[str, ...] = (
    "API_HOST",
    "API_PORT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "RATE_LIMIT_DEFAULT",
    "READINESS_PROBE_TIMEOUT_SECONDS",
    "STARTUP_PROBE_TIMEOUT_SECONDS",
    "SECURITY_HSTS_MAX_AGE_SECONDS",
    "FETCH_MAX_REDIRECT_HOPS",
    "ALLOWED_PRIVATE_HOSTS",
    "MCP_FILE_URI_ROOT",
    "MCP_DOWNLOAD_TIMEOUT_SECONDS",
    "MCP_ALLOWED_HOSTS",
)


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_default_api_host_is_all_interfaces() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.API_HOST == "0.0.0.0"


def test_default_log_level_is_info() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.LOG_LEVEL == "INFO"


def test_default_log_format_is_json() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.LOG_FORMAT == "json"


def test_default_otel_endpoint_is_unset() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT is None


def test_empty_otel_endpoint_is_accepted_as_no_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    # when
    settings = _TestSettings()
    # then
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == ""


def test_valid_otel_endpoint_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    # when
    settings = _TestSettings()
    # then
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == "http://otel-collector:4317"


def test_default_allowed_private_hosts_is_empty() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestFetchSettings()
    # then
    assert env_isolated
    assert settings.ALLOWED_PRIVATE_HOSTS == ()


def test_default_file_uri_root_is_unset() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestFetchSettings()
    # then
    assert env_isolated
    assert settings.MCP_FILE_URI_ROOT is None


def test_lowercase_log_level_is_accepted_as_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("LOG_LEVEL", "debug")
    # when
    settings = _TestSettings()
    # then
    assert settings.LOG_LEVEL == "DEBUG"


def test_verbose_log_level_is_refused_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("LOG_LEVEL",)


def test_non_string_log_level_is_refused() -> None:
    # given
    invalid = cast("Any", 123)
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings(LOG_LEVEL=invalid)
    # then
    assert excinfo.value.errors()[0]["loc"] == ("LOG_LEVEL",)


def test_api_port_zero_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("API_PORT", "0")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("API_PORT",)


def test_api_port_above_range_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("API_PORT", "70000")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("API_PORT",)


def test_malformed_default_rate_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "not-a-limit")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("RATE_LIMIT_DEFAULT",)


def test_non_string_rate_limit_is_refused() -> None:
    # given
    invalid = cast("Any", None)
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings(RATE_LIMIT_DEFAULT=invalid)
    # then
    assert excinfo.value.errors()[0]["loc"] == ("RATE_LIMIT_DEFAULT",)


def test_relative_file_uri_root_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("MCP_FILE_URI_ROOT", "relative/uploads")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestFetchSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("MCP_FILE_URI_ROOT",)


def test_absolute_file_uri_root_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # given
    monkeypatch.setenv("MCP_FILE_URI_ROOT", str(tmp_path))
    # when
    settings = _TestFetchSettings()
    # then
    assert str(tmp_path) == settings.MCP_FILE_URI_ROOT


def test_non_url_otel_endpoint_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "not-a-url")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("OTEL_EXPORTER_OTLP_ENDPOINT",)


def test_allowed_private_hosts_read_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("ALLOWED_PRIVATE_HOSTS", "host.docker.internal,localhost,127.0.0.1")
    # when
    settings = _TestFetchSettings()
    # then
    assert settings.ALLOWED_PRIVATE_HOSTS == (
        "host.docker.internal",
        "localhost",
        "127.0.0.1",
    )


def test_allowed_private_hosts_csv_drops_empty_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("ALLOWED_PRIVATE_HOSTS", "  host.docker.internal , ,localhost  ")
    # when
    settings = _TestFetchSettings()
    # then
    assert settings.ALLOWED_PRIVATE_HOSTS == ("host.docker.internal", "localhost")


def test_legacy_allow_list_name_refuses_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "host.docker.internal")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert "MCP_ALLOWED_HOSTS" in str(excinfo.value)
    assert "ALLOWED_PRIVATE_HOSTS" in str(excinfo.value)


def test_shared_types_cover_the_settings_fields() -> None:
    # given
    annotated_names = ("CsvTuple", "LogLevel", "RateLimit")
    # when
    resolved = (CsvTuple, LogLevel, RateLimit)
    # then
    assert annotated_names == ("CsvTuple", "LogLevel", "RateLimit")
    assert len(resolved) == 3


def test_default_readiness_probe_timeout_is_three_seconds() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.READINESS_PROBE_TIMEOUT_SECONDS == 3.0


def test_default_startup_probe_timeout_is_two_seconds() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.STARTUP_PROBE_TIMEOUT_SECONDS == 2.0


def test_default_hsts_max_age_is_two_years_in_seconds() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestSettings()
    # then
    assert env_isolated
    assert settings.SECURITY_HSTS_MAX_AGE_SECONDS == 63072000


def test_default_fetch_max_redirect_hops_is_ten() -> None:
    # given
    env_isolated = True
    # when
    settings = _TestFetchSettings()
    # then
    assert env_isolated
    assert settings.FETCH_MAX_REDIRECT_HOPS == 10


def test_readiness_probe_timeout_at_zero_is_refused_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("READINESS_PROBE_TIMEOUT_SECONDS", "0")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("READINESS_PROBE_TIMEOUT_SECONDS",)


def test_startup_probe_timeout_at_zero_is_refused_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("STARTUP_PROBE_TIMEOUT_SECONDS", "0")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("STARTUP_PROBE_TIMEOUT_SECONDS",)


def test_hsts_max_age_below_zero_is_refused_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("SECURITY_HSTS_MAX_AGE_SECONDS", "-1")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("SECURITY_HSTS_MAX_AGE_SECONDS",)


def test_fetch_max_redirect_hops_below_zero_is_refused_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("FETCH_MAX_REDIRECT_HOPS", "-1")
    # when
    with pytest.raises(ValidationError) as excinfo:
        _TestFetchSettings()
    # then
    assert excinfo.value.errors()[0]["loc"] == ("FETCH_MAX_REDIRECT_HOPS",)


def test_fetch_policy_carries_the_configured_hop_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("FETCH_MAX_REDIRECT_HOPS", "2")
    # when
    policy = _TestFetchSettings().fetch_policy()
    # then
    assert policy.max_redirect_hops == 2
