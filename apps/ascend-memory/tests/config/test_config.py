import os
from unittest.mock import patch

import pytest

from src.config.config import (
    PROVIDER_CONFIGS,
    Settings,
    provider_config,
    provider_settings_value,
    settings,
    supported_providers,
)


def test_settings_defaults():
    fresh = Settings()
    assert fresh.API_PORT == 7020
    assert fresh.API_HOST == "0.0.0.0"
    assert fresh.QDRANT_HOST == "localhost"
    assert fresh.MEM0_DEFAULT_PROVIDER == "lmstudio"
    assert fresh.MEM0_LLM_MODEL == "meta-llama-3.1-8b-instruct"


def test_settings_env_override():
    env_vars = {
        "API_PORT": "9090",
        "QDRANT_HOST": "qdrant-prod",
        "MEM0_DEFAULT_PROVIDER": "openai",
    }
    with patch.dict(os.environ, env_vars):
        fresh = Settings()
        assert fresh.API_PORT == 9090
        assert fresh.QDRANT_HOST == "qdrant-prod"
        assert fresh.MEM0_DEFAULT_PROVIDER == "openai"


def test_supported_providers_is_sorted_and_complete():
    providers = supported_providers()
    assert providers == sorted(PROVIDER_CONFIGS.keys())
    assert set(providers) == {"lmstudio", "openai", "gemini"}


def test_provider_config_returns_each_provider_block():
    for name in supported_providers():
        cfg = provider_config(name)
        assert cfg["embedding_model"]
        assert cfg["embedding_dims"] > 0
        assert cfg["collection_name"]
        assert cfg["base_url_setting"]
        assert cfg["api_key_setting"]
        assert cfg["llm_provider"] in {"lmstudio", "openai"}


def test_provider_config_raises_keyerror_for_unknown():
    with pytest.raises(KeyError):
        provider_config("not-a-real-provider")


def test_provider_settings_value_reads_from_settings_object():
    assert provider_settings_value("LMSTUDIO_BASE_URL") == settings.LMSTUDIO_BASE_URL


def test_lmstudio_provider_uses_lmstudio_llm_backend():
    assert provider_config("lmstudio")["llm_provider"] == "lmstudio"


def test_gemini_provider_uses_openai_compatible_llm_backend():
    assert provider_config("gemini")["llm_provider"] == "openai"
