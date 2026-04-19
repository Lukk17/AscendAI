import os
from unittest.mock import patch
from src.config.config import Settings


def test_settings_defaults():
    # When initializing settings without env vars
    settings = Settings()

    # then
    assert settings.API_PORT == 7020
    assert settings.API_HOST == "0.0.0.0"
    assert settings.QDRANT_HOST == "localhost"
    assert settings.MEM0_DEFAULT_PROVIDER == "lmstudio"
    assert settings.MEM0_LLM_MODEL == "meta-llama-3.1-8b-instruct"


def test_settings_env_override():
    # Mocking environment variables
    env_vars = {
        "API_PORT": "9090",
        "QDRANT_HOST": "qdrant-prod",
        "MEM0_DEFAULT_PROVIDER": "openai"
    }

    with patch.dict(os.environ, env_vars):
        # when
        settings = Settings()

        # then
        assert settings.API_PORT == 9090
        assert settings.QDRANT_HOST == "qdrant-prod"
        assert settings.MEM0_DEFAULT_PROVIDER == "openai"
