from typing import TypedDict

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(TypedDict):
    """Shape of each entry in PROVIDER_CONFIGS so PyCharm / pyright can verify
    consumer access patterns instead of seeing untyped Any."""

    embedding_model: str
    embedding_dims: int
    collection_name: str
    base_url_setting: str
    api_key_setting: str
    llm_provider: str


# Each entry maps a logical provider name (the value callers send as
# `provider=...`) to its Qdrant collection (collections are dimension-keyed,
# so providers sharing dims share the collection), the env-var Settings keys
# holding base_url and api_key, and the mem0 LLM provider to instantiate.
# LM Studio gets mem0's native `lmstudio` LLM provider — it knows the
# response_format quirks natively, so the old OpenAILLM monkey-patch is gone.
PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
    "lmstudio": {
        "embedding_model": "text-embedding-nomic-embed-text-v2-moe",
        "embedding_dims": 768,
        "collection_name": "ascend_memory_768",
        "base_url_setting": "LMSTUDIO_BASE_URL",
        "api_key_setting": "LMSTUDIO_API_KEY",
        "llm_provider": "lmstudio",
    },
    "openai": {
        "embedding_model": "text-embedding-3-small",
        "embedding_dims": 1536,
        "collection_name": "ascend_memory_1536",
        "base_url_setting": "OPENAI_BASE_URL",
        "api_key_setting": "OPENAI_API_KEY",
        "llm_provider": "openai",
    },
    "gemini": {
        "embedding_model": "gemini-embedding-001",
        "embedding_dims": 768,
        "collection_name": "ascend_memory_768",
        "base_url_setting": "GEMINI_BASE_URL",
        "api_key_setting": "GEMINI_API_KEY",
        "llm_provider": "openai",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    API_PORT: int = Field(default=7020, description="Port for the FastAPI server")
    API_HOST: str = Field(default="0.0.0.0", description="Host to bind the server to")

    LMSTUDIO_BASE_URL: str = Field(
        default="http://localhost:1234/v1",
        description="LM Studio OpenAI-compatible base URL",
    )
    LMSTUDIO_API_KEY: str = Field(
        default="sk_local",
        description="LM Studio API key (placeholder, LM Studio doesn't validate)",
    )

    OPENAI_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="Real OpenAI base URL",
    )
    OPENAI_API_KEY: str = Field(
        default="",
        description="Real OpenAI API key (required for provider=openai)",
    )

    GEMINI_BASE_URL: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        description="Gemini OpenAI-compatible base URL",
    )
    GEMINI_API_KEY: str = Field(
        default="",
        description="Gemini API key (required for provider=gemini)",
    )

    QDRANT_HOST: str = Field(default="localhost", description="Qdrant Host")
    QDRANT_PORT: int = Field(default=6333, description="Qdrant Port")

    MEM0_DEFAULT_PROVIDER: str = Field(
        default="lmstudio",
        description="Default embedding provider when callers omit the param",
    )

    MEM0_LLM_MODEL: str = Field(
        default="meta-llama-3.1-8b-instruct",
        description="LLM Model for Mem0",
    )
    MEM0_INFER_MEMORY: bool = Field(
        default=False,
        description="Whether to infer memory from interactions",
    )

    DEFAULT_USER_ID: str = Field(
        default="default_user",
        description="Default user_id when callers (REST or MCP) omit it",
    )

    MAX_USER_ID_LENGTH: int = Field(default=128, description="user_id input cap")
    MAX_QUERY_LENGTH: int = Field(default=2048, description="search query input cap")
    MAX_MEMORY_TEXT_LENGTH: int = Field(default=32_768, description="memory text input cap")
    MAX_SEARCH_LIMIT: int = Field(default=100, description="search limit upper bound")

    LOG_LEVEL: str = Field(default="INFO", description="Logging Level")


settings = Settings()


def supported_providers() -> list[str]:
    """Returns the sorted list of provider names the service recognises.
    PROVIDER_CONFIGS is the source of truth; resolve_provider validates
    against this set instead of silently lowercasing arbitrary strings."""

    return sorted(PROVIDER_CONFIGS.keys())


def provider_config(provider: str) -> ProviderConfig:
    """Lookup with KeyError-on-miss; callers should validate via
    resolve_provider before calling this."""

    return PROVIDER_CONFIGS[provider]


def provider_settings_value(setting_name: str, settings_obj: Settings = settings) -> str:
    """Resolve the env-var-backed value (base_url or api_key) for a provider.
    Returns the raw value; callers decide whether empty is valid."""

    return str(getattr(settings_obj, setting_name))
