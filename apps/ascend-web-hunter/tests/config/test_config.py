import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config.config import Settings


def test_settings_defaults() -> None:
    # when
    settings = Settings()

    # then
    assert settings.API_PORT == 7021
    assert settings.API_HOST == "0.0.0.0"
    assert settings.SEARXNG_BASE_URL == "http://localhost:9020"


def test_redis_url_default_uses_ipv4_loopback_not_localhost(monkeypatch: Any) -> None:
    # given
    monkeypatch.delenv("REDIS_URL", raising=False)

    # when
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    # then
    assert settings.REDIS_URL == "redis://127.0.0.1:6379/0"


def test_settings_env_override() -> None:
    # given
    # Mocking environment variables
    with patch.dict(os.environ, {"API_PORT": "9000"}):
        # when
        settings = Settings()

        # then
        assert settings.API_PORT == 9000


def test_blocklist_path_defaults_to_vendored_asset() -> None:
    # when
    settings = Settings()

    # then
    assert settings.BLOCKLIST_PATH == "src/assets/fanboy-annoyance.txt"


def test_blocklist_path_env_override(tmp_path: Any) -> None:
    # given
    # Mocking environment variables
    override = str(tmp_path / "custom-blocklist.txt")
    with patch.dict(os.environ, {"BLOCKLIST_PATH": override}):
        # when
        settings = Settings()

        # then
        assert override == settings.BLOCKLIST_PATH


def test_blocklist_refresh_min_interval_default() -> None:
    # given
    settings = Settings()

    # then
    assert settings.BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS == 60.0


def test_novnc_max_concurrent_flows_default() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_MAX_CONCURRENT_FLOWS", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_MAX_CONCURRENT_FLOWS == 4


def test_novnc_max_concurrent_flows_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_MAX_CONCURRENT_FLOWS": "2"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_MAX_CONCURRENT_FLOWS == 2


def test_novnc_max_concurrent_flows_rejects_zero() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_MAX_CONCURRENT_FLOWS": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_dockerfile_novnc_display_size_matches_settings_default() -> None:
    # given
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    values = [
        line.split("=", 1)[1].strip()
        for line in dockerfile.read_text(encoding="utf-8").splitlines()
        if line.startswith("ENV NOVNC_DISPLAY_SIZE=")
    ]

    # when
    settings = Settings()

    # then
    assert values == [settings.NOVNC_DISPLAY_SIZE]


def test_novnc_display_size_default() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_DISPLAY_SIZE", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_DISPLAY_SIZE == "1920x1080"


def test_novnc_display_size_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_DISPLAY_SIZE": "1600x900"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_DISPLAY_SIZE == "1600x900"


def test_novnc_display_size_malformed_value_is_rejected() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_DISPLAY_SIZE": "wide"}):
        # when / then
        with pytest.raises(ValidationError, match="NOVNC_DISPLAY_SIZE"):
            Settings()


@pytest.mark.parametrize("value", ["1920", "1920x1080x24", "1920x", "x1080", "1920xhigh", "-5x5"])
def test_novnc_display_size_rejects_values_not_reading_width_by_height(value: Any) -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_DISPLAY_SIZE": value}):
        # when / then
        with pytest.raises(ValidationError, match="must read <width>x<height>"):
            Settings()


def test_novnc_display_size_rejects_display_narrower_than_window_width() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_DISPLAY_SIZE": "640x1080"}):
        # when / then
        with pytest.raises(ValidationError) as exc:
            Settings()

    # then
    message = str(exc.value)
    assert "NOVNC_DISPLAY_SIZE" in message
    assert "640x1080" in message
    assert "NOVNC_WINDOW_WIDTH_PX" in message


def test_novnc_display_size_rejects_display_shorter_than_window_height() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_DISPLAY_SIZE": "1920x400"}):
        # when / then
        with pytest.raises(ValidationError) as exc:
            Settings()

    # then
    message = str(exc.value)
    assert "NOVNC_DISPLAY_SIZE" in message
    assert "1920x400" in message
    assert "NOVNC_WINDOW_HEIGHT_PX" in message


def test_novnc_window_width_px_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_WINDOW_WIDTH_PX", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_WINDOW_WIDTH_PX == 1280

    # given
    with patch.dict(os.environ, {"NOVNC_WINDOW_WIDTH_PX": "640"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_WINDOW_WIDTH_PX == 640

    # given
    with patch.dict(os.environ, {"NOVNC_WINDOW_WIDTH_PX": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_window_height_px_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_WINDOW_HEIGHT_PX", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_WINDOW_HEIGHT_PX == 800

    # given
    with patch.dict(os.environ, {"NOVNC_WINDOW_HEIGHT_PX": "600"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_WINDOW_HEIGHT_PX == 600

    # given
    with patch.dict(os.environ, {"NOVNC_WINDOW_HEIGHT_PX": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_window_cascade_offset_px_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_WINDOW_CASCADE_OFFSET_PX", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_WINDOW_CASCADE_OFFSET_PX == 48

    # given
    with patch.dict(os.environ, {"NOVNC_WINDOW_CASCADE_OFFSET_PX": "24"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_WINDOW_CASCADE_OFFSET_PX == 24

    # given
    with patch.dict(os.environ, {"NOVNC_WINDOW_CASCADE_OFFSET_PX": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_flow_lease_grace_seconds_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_FLOW_LEASE_GRACE_SECONDS", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_FLOW_LEASE_GRACE_SECONDS == 30.0

    # given
    with patch.dict(os.environ, {"NOVNC_FLOW_LEASE_GRACE_SECONDS": "45.0"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_FLOW_LEASE_GRACE_SECONDS == 45.0

    # given
    with patch.dict(os.environ, {"NOVNC_FLOW_LEASE_GRACE_SECONDS": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_flow_sweep_interval_seconds_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_FLOW_SWEEP_INTERVAL_SECONDS", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_FLOW_SWEEP_INTERVAL_SECONDS == 30.0

    # given
    with patch.dict(os.environ, {"NOVNC_FLOW_SWEEP_INTERVAL_SECONDS": "10.0"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_FLOW_SWEEP_INTERVAL_SECONDS == 10.0

    # given
    with patch.dict(os.environ, {"NOVNC_FLOW_SWEEP_INTERVAL_SECONDS": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_flow_cancel_grace_seconds_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_FLOW_CANCEL_GRACE_SECONDS", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_FLOW_CANCEL_GRACE_SECONDS == 10.0

    # given
    with patch.dict(os.environ, {"NOVNC_FLOW_CANCEL_GRACE_SECONDS": "5.0"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_FLOW_CANCEL_GRACE_SECONDS == 5.0

    # given
    with patch.dict(os.environ, {"NOVNC_FLOW_CANCEL_GRACE_SECONDS": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_busy_retry_after_seconds_default_override_and_rejected() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_BUSY_RETRY_AFTER_SECONDS", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_BUSY_RETRY_AFTER_SECONDS == 30

    # given
    with patch.dict(os.environ, {"NOVNC_BUSY_RETRY_AFTER_SECONDS": "15"}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_BUSY_RETRY_AFTER_SECONDS == 15

    # given
    with patch.dict(os.environ, {"NOVNC_BUSY_RETRY_AFTER_SECONDS": "0"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_novnc_public_url_unset_by_default() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVNC_PUBLIC_URL", None)

        # when
        settings = Settings()

        # then
        assert settings.NOVNC_PUBLIC_URL is None


def test_novnc_public_url_empty_string_means_unset() -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_PUBLIC_URL": ""}):
        # when
        settings = Settings()

        # then
        assert settings.NOVNC_PUBLIC_URL is None


@pytest.mark.parametrize("value", ["https://edge.example.com", "http://edge.example.com:8443"])
def test_novnc_public_url_accepts_absolute_url_without_path(value: Any) -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_PUBLIC_URL": value}):
        # when
        settings = Settings()

        # then
        assert value == settings.NOVNC_PUBLIC_URL


@pytest.mark.parametrize("value", ["edge.example.com", "/novnc", "ftp://edge.example.com"])
def test_novnc_public_url_refuses_non_absolute_url(value: Any) -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_PUBLIC_URL": value}):
        # when / then
        with pytest.raises(ValidationError, match="NOVNC_PUBLIC_URL"):
            Settings()


@pytest.mark.parametrize("value", ["https://edge.example.com/novnc", "https://edge.example.com/"])
def test_novnc_public_url_refuses_url_with_path(value: Any) -> None:
    # given
    with patch.dict(os.environ, {"NOVNC_PUBLIC_URL": value}):
        # when / then
        with pytest.raises(ValidationError, match="NOVNC_PUBLIC_URL"):
            Settings()


_CHALLENGE_DEFAULTS: dict[str, Any] = {
    "CHALLENGE_SCORE_THRESHOLD": 100,
    "CHALLENGE_RICH_CONTENT_WORDS": 150,
    "CHALLENGE_FORM_DOMINANCE_RATIO": 0.6,
    "CHALLENGE_MIN_WORDS_PER_KB": 2.0,
    "CHALLENGE_THIN_LINK_COUNT": 5,
    "CHALLENGE_RICH_LINK_COUNT": 20,
    "CHALLENGE_SHAPE_MAX_BYTES": 500_000,
    "CHALLENGE_WEIGHT_DEFINITIVE_HEADER": 200,
    "CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE": 80,
    "CHALLENGE_WEIGHT_VENDOR_SCRIPT": 60,
    "CHALLENGE_WEIGHT_VENDOR_PRESENCE": 30,
    "CHALLENGE_WEIGHT_STATUS_EMPTY_BODY": 200,
    "CHALLENGE_WEIGHT_STATUS_SMALL_BODY": 50,
    "CHALLENGE_WEIGHT_STATUS_LARGE_BODY": 20,
    "CHALLENGE_WEIGHT_CAPTCHA_INPUT": 50,
    "CHALLENGE_WEIGHT_CAPTCHA_ELEMENT": 40,
    "CHALLENGE_WEIGHT_FORM_DOMINANCE": 40,
    "CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY": 40,
    "CHALLENGE_WEIGHT_THIN_TEXT": 20,
    "CHALLENGE_WEIGHT_FEW_LINKS": 20,
    "CHALLENGE_WEIGHT_NO_ARTICLE": 20,
    "CHALLENGE_WEIGHT_RICH_CONTENT": -60,
    "CHALLENGE_WEIGHT_MANY_LINKS": -20,
    "CHALLENGE_WEIGHT_PHRASE_TITLE": 60,
    "CHALLENGE_WEIGHT_PHRASE_BODY": 30,
}

_CHALLENGE_VALID_OVERRIDES: dict[str, str] = {
    "CHALLENGE_SCORE_THRESHOLD": "120",
    "CHALLENGE_RICH_CONTENT_WORDS": "200",
    "CHALLENGE_FORM_DOMINANCE_RATIO": "0.5",
    "CHALLENGE_MIN_WORDS_PER_KB": "1.5",
    "CHALLENGE_THIN_LINK_COUNT": "3",
    "CHALLENGE_RICH_LINK_COUNT": "25",
    "CHALLENGE_SHAPE_MAX_BYTES": "600000",
    "CHALLENGE_WEIGHT_DEFINITIVE_HEADER": "210",
    "CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE": "70",
    "CHALLENGE_WEIGHT_VENDOR_SCRIPT": "55",
    "CHALLENGE_WEIGHT_VENDOR_PRESENCE": "25",
    "CHALLENGE_WEIGHT_STATUS_EMPTY_BODY": "210",
    "CHALLENGE_WEIGHT_STATUS_SMALL_BODY": "45",
    "CHALLENGE_WEIGHT_STATUS_LARGE_BODY": "15",
    "CHALLENGE_WEIGHT_CAPTCHA_INPUT": "45",
    "CHALLENGE_WEIGHT_CAPTCHA_ELEMENT": "35",
    "CHALLENGE_WEIGHT_FORM_DOMINANCE": "35",
    "CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY": "35",
    "CHALLENGE_WEIGHT_THIN_TEXT": "15",
    "CHALLENGE_WEIGHT_FEW_LINKS": "15",
    "CHALLENGE_WEIGHT_NO_ARTICLE": "15",
    "CHALLENGE_WEIGHT_RICH_CONTENT": "-50",
    "CHALLENGE_WEIGHT_MANY_LINKS": "-10",
    "CHALLENGE_WEIGHT_PHRASE_TITLE": "55",
    "CHALLENGE_WEIGHT_PHRASE_BODY": "25",
}

_CHALLENGE_REJECTED: dict[str, str] = {
    "CHALLENGE_SCORE_THRESHOLD": "0",
    "CHALLENGE_RICH_CONTENT_WORDS": "0",
    "CHALLENGE_FORM_DOMINANCE_RATIO": "0",
    "CHALLENGE_MIN_WORDS_PER_KB": "0",
    "CHALLENGE_THIN_LINK_COUNT": "-1",
    "CHALLENGE_RICH_LINK_COUNT": "-1",
    "CHALLENGE_SHAPE_MAX_BYTES": "0",
    "CHALLENGE_WEIGHT_DEFINITIVE_HEADER": "2000",
    "CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE": "2000",
    "CHALLENGE_WEIGHT_VENDOR_SCRIPT": "2000",
    "CHALLENGE_WEIGHT_VENDOR_PRESENCE": "2000",
    "CHALLENGE_WEIGHT_STATUS_EMPTY_BODY": "2000",
    "CHALLENGE_WEIGHT_STATUS_SMALL_BODY": "2000",
    "CHALLENGE_WEIGHT_STATUS_LARGE_BODY": "2000",
    "CHALLENGE_WEIGHT_CAPTCHA_INPUT": "2000",
    "CHALLENGE_WEIGHT_CAPTCHA_ELEMENT": "2000",
    "CHALLENGE_WEIGHT_FORM_DOMINANCE": "2000",
    "CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY": "2000",
    "CHALLENGE_WEIGHT_THIN_TEXT": "2000",
    "CHALLENGE_WEIGHT_FEW_LINKS": "2000",
    "CHALLENGE_WEIGHT_NO_ARTICLE": "2000",
    "CHALLENGE_WEIGHT_RICH_CONTENT": "-2000",
    "CHALLENGE_WEIGHT_MANY_LINKS": "-2000",
    "CHALLENGE_WEIGHT_PHRASE_TITLE": "2000",
    "CHALLENGE_WEIGHT_PHRASE_BODY": "2000",
}


def test_challenge_tuning_and_weight_defaults() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        for name in list(_CHALLENGE_DEFAULTS):
            os.environ.pop(name, None)

        # when
        settings = Settings()

        # then
        for name, expected in _CHALLENGE_DEFAULTS.items():
            assert getattr(settings, name) == expected


@pytest.mark.parametrize("name", sorted(_CHALLENGE_DEFAULTS))
def test_challenge_setting_valid_override(name: str) -> None:
    # given
    raw = _CHALLENGE_VALID_OVERRIDES[name]

    # when
    with patch.dict(os.environ, {name: raw}):
        settings = Settings()

    # then
    value = getattr(settings, name)
    if isinstance(_CHALLENGE_DEFAULTS[name], float):
        assert value == pytest.approx(float(raw))
    else:
        assert value == int(raw)


@pytest.mark.parametrize("name", sorted(_CHALLENGE_DEFAULTS))
def test_challenge_setting_rejects_value_outside_constraint(name: str) -> None:
    # given
    with patch.dict(os.environ, {name: _CHALLENGE_REJECTED[name]}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_challenge_detection_and_wall_byte_limits_keep_defaults() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CHALLENGE_DETECTION_MAX_BYTES", None)
        os.environ.pop("CHALLENGE_WALL_MAX_BYTES", None)

        # when
        settings = Settings()

        # then
        assert settings.CHALLENGE_DETECTION_MAX_BYTES == 50_000
        assert settings.CHALLENGE_WALL_MAX_BYTES == 50_000


def test_challenge_validator_rejects_wall_above_shape() -> None:
    # given
    env = {"CHALLENGE_WALL_MAX_BYTES": "600000", "CHALLENGE_SHAPE_MAX_BYTES": "500000"}

    # when / then
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError, match=r"CHALLENGE_WALL_MAX_BYTES.*CHALLENGE_SHAPE_MAX_BYTES"):
            Settings()


def test_challenge_validator_rejects_single_signal_at_threshold() -> None:
    # given
    env = {"CHALLENGE_WEIGHT_VENDOR_SCRIPT": "100"}

    # when / then
    with patch.dict(os.environ, env):
        with pytest.raises(
            ValidationError, match=r"CHALLENGE_WEIGHT_VENDOR_SCRIPT.*CHALLENGE_SCORE_THRESHOLD"
        ):
            Settings()


def test_challenge_validator_rejects_positive_rich_content() -> None:
    # given
    env = {"CHALLENGE_WEIGHT_RICH_CONTENT": "10"}

    # when / then
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError, match="CHALLENGE_WEIGHT_RICH_CONTENT"):
            Settings()


def test_challenge_validator_rejects_positive_many_links() -> None:
    # given
    env = {"CHALLENGE_WEIGHT_MANY_LINKS": "5"}

    # when / then
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError, match="CHALLENGE_WEIGHT_MANY_LINKS"):
            Settings()


def test_challenge_validator_rejects_negative_other_signal() -> None:
    # given
    env = {"CHALLENGE_WEIGHT_VENDOR_SCRIPT": "-5"}

    # when / then
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError, match="CHALLENGE_WEIGHT_VENDOR_SCRIPT"):
            Settings()


def test_challenge_validator_rejects_thin_above_rich_link_count() -> None:
    # given
    env = {"CHALLENGE_THIN_LINK_COUNT": "30", "CHALLENGE_RICH_LINK_COUNT": "20"}

    # when / then
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError, match=r"CHALLENGE_THIN_LINK_COUNT.*CHALLENGE_RICH_LINK_COUNT"):
            Settings()


def test_flaresolverr_enabled_default() -> None:
    # when
    settings = Settings()

    # then
    assert settings.FLARESOLVERR_ENABLED is False


def test_flaresolverr_enabled_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"FLARESOLVERR_ENABLED": "true"}):
        # when
        settings = Settings()

        # then
        assert settings.FLARESOLVERR_ENABLED is True


def test_flaresolverr_enabled_rejects_non_boolean() -> None:
    # given
    with patch.dict(os.environ, {"FLARESOLVERR_ENABLED": "maybe"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_camoufox_enabled_default() -> None:
    # when
    settings = Settings()

    # then
    assert settings.CAMOUFOX_ENABLED is True


def test_camoufox_enabled_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"CAMOUFOX_ENABLED": "false"}):
        # when
        settings = Settings()

        # then
        assert settings.CAMOUFOX_ENABLED is False


def test_camoufox_enabled_rejects_non_boolean() -> None:
    # given
    with patch.dict(os.environ, {"CAMOUFOX_ENABLED": "maybe"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_tier_memory_ttl_seconds_default() -> None:
    # when
    settings = Settings()

    # then
    assert settings.TIER_MEMORY_TTL_SECONDS == 86400


def test_tier_memory_ttl_seconds_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"TIER_MEMORY_TTL_SECONDS": "3600"}):
        # when
        settings = Settings()

        # then
        assert settings.TIER_MEMORY_TTL_SECONDS == 3600


def test_tier_memory_ttl_seconds_rejects_below_minimum() -> None:
    # given
    with patch.dict(os.environ, {"TIER_MEMORY_TTL_SECONDS": "59"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_networkidle_poll_ms_default() -> None:
    # when
    settings = Settings()

    # then
    assert settings.NETWORKIDLE_POLL_MS == 1000


def test_networkidle_poll_ms_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"NETWORKIDLE_POLL_MS": "500"}):
        # when
        settings = Settings()

        # then
        assert settings.NETWORKIDLE_POLL_MS == 500


def test_networkidle_poll_ms_rejects_non_integer() -> None:
    # given
    with patch.dict(os.environ, {"NETWORKIDLE_POLL_MS": "soon"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


def test_scroll_pause_ms_default() -> None:
    # when
    settings = Settings()

    # then
    assert settings.SCROLL_PAUSE_MS == 200


def test_scroll_pause_ms_valid_override() -> None:
    # given
    with patch.dict(os.environ, {"SCROLL_PAUSE_MS": "100"}):
        # when
        settings = Settings()

        # then
        assert settings.SCROLL_PAUSE_MS == 100


def test_scroll_pause_ms_rejects_non_integer() -> None:
    # given
    with patch.dict(os.environ, {"SCROLL_PAUSE_MS": "soon"}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()


_EXTRACTION_DEFAULTS: dict[str, Any] = {
    "EXTRACTION_SCHEMA_MAX_BYTES": 16384,
    "EXTRACTION_LLM_BASE_URL": "",
    "EXTRACTION_LLM_MODEL": "",
    "EXTRACTION_LLM_API_KEY": "",
    "EXTRACTION_LLM_MAX_INPUT_CHARS": 60000,
    "EXTRACTION_LLM_TIMEOUT_SECONDS": 60.0,
    "RECIPE_TTL_SECONDS": 604800,
    "RECIPE_SELECTOR_MAX_CHARS": 512,
    "DOCUMENT_MAX_BYTES": 52428800,
    "DOCLING_SERVE_URL": "http://docling-serve:5001",
    "ASCEND_OCR_URL": "http://ascend-ocr:7022",
    "OCR_ROUTE_TIMEOUT_SECONDS": 300.0,
    "AUDIO_SCRIBE_URL": "http://ascend-audio-scribe:7017",
    "READ_CACHE_PURGE_RECONNECT_SECONDS": 5.0,
}

_EXTRACTION_VALID_OVERRIDES: dict[str, str] = {
    "EXTRACTION_SCHEMA_MAX_BYTES": "8192",
    "EXTRACTION_LLM_BASE_URL": "http://localhost:11434",
    "EXTRACTION_LLM_MODEL": "test-model",
    "EXTRACTION_LLM_API_KEY": "test-key",
    "EXTRACTION_LLM_MAX_INPUT_CHARS": "1000",
    "EXTRACTION_LLM_TIMEOUT_SECONDS": "30",
    "RECIPE_TTL_SECONDS": "3600",
    "RECIPE_SELECTOR_MAX_CHARS": "256",
    "DOCUMENT_MAX_BYTES": "1048576",
    "DOCLING_SERVE_URL": "http://localhost:5001",
    "ASCEND_OCR_URL": "http://localhost:7022",
    "OCR_ROUTE_TIMEOUT_SECONDS": "60",
    "AUDIO_SCRIBE_URL": "http://localhost:7017",
    "READ_CACHE_PURGE_RECONNECT_SECONDS": "1",
}

_EXTRACTION_REJECTED: dict[str, str] = {
    "EXTRACTION_SCHEMA_MAX_BYTES": "0",
    "EXTRACTION_LLM_MAX_INPUT_CHARS": "0",
    "EXTRACTION_LLM_TIMEOUT_SECONDS": "0",
    "RECIPE_TTL_SECONDS": "59",
    "RECIPE_SELECTOR_MAX_CHARS": "0",
    "DOCUMENT_MAX_BYTES": "0",
    "OCR_ROUTE_TIMEOUT_SECONDS": "0",
    "READ_CACHE_PURGE_RECONNECT_SECONDS": "0",
}


def test_extraction_and_routing_setting_defaults() -> None:
    # given
    with patch.dict(os.environ, {}, clear=False):
        for name in list(_EXTRACTION_DEFAULTS):
            os.environ.pop(name, None)

        # when
        settings = Settings()

        # then
        for name, expected in _EXTRACTION_DEFAULTS.items():
            assert getattr(settings, name) == expected


@pytest.mark.parametrize("name", sorted(_EXTRACTION_DEFAULTS))
def test_extraction_and_routing_setting_valid_override(name: str) -> None:
    # given
    raw = _EXTRACTION_VALID_OVERRIDES[name]

    # when
    with patch.dict(os.environ, {name: raw}):
        settings = Settings()

    # then
    value = getattr(settings, name)
    expected = _EXTRACTION_DEFAULTS[name]
    if isinstance(expected, float):
        assert value == pytest.approx(float(raw))
    elif isinstance(expected, int):
        assert value == int(raw)
    else:
        assert value == raw


@pytest.mark.parametrize("name", sorted(_EXTRACTION_REJECTED))
def test_extraction_and_routing_setting_rejects_value_outside_constraint(name: str) -> None:
    # given
    with patch.dict(os.environ, {name: _EXTRACTION_REJECTED[name]}):
        # when / then
        with pytest.raises(ValidationError):
            Settings()
