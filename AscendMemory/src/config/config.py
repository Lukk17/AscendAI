from typing import Dict, Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Embedding provider configs — each maps to a Qdrant collection by dimension
# and to the Settings attributes that hold its base_url + api_key.
# Providers sharing the same dims share the same collection.
PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "lmstudio": {
        "embedding_model": "text-embedding-nomic-embed-text-v2-moe",
        "embedding_dims": 768,
        "collection_name": "ascend_memory_768",
        "base_url_setting": "LMSTUDIO_BASE_URL",
        "api_key_setting": "LMSTUDIO_API_KEY",
    },
    "openai": {
        "embedding_model": "text-embedding-3-small",
        "embedding_dims": 1536,
        "collection_name": "ascend_memory_1536",
        "base_url_setting": "OPENAI_BASE_URL",
        "api_key_setting": "OPENAI_API_KEY",
    },
    "gemini": {
        "embedding_model": "gemini-embedding-001",
        "embedding_dims": 768,
        "collection_name": "ascend_memory_768",
        "base_url_setting": "GEMINI_BASE_URL",
        "api_key_setting": "GEMINI_API_KEY",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Configuration
    API_PORT: int = Field(default=7020, description="Port for the FastAPI server")
    API_HOST: str = Field(default="0.0.0.0", description="Host to bind the server to")

    # Per-provider credentials. Each provider routes to its own (base_url, api_key) pair
    # so e.g. provider=openai hits api.openai.com while provider=lmstudio hits LM Studio.
    LMSTUDIO_BASE_URL: str = Field(default="http://localhost:1234/v1", description="LM Studio OpenAI-compatible base URL")
    LMSTUDIO_API_KEY: str = Field(default="sk_local", description="LM Studio API key (placeholder, LM Studio doesn't validate)")

    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1", description="Real OpenAI base URL")
    OPENAI_API_KEY: str = Field(default="", description="Real OpenAI API key (required for provider=openai)")

    GEMINI_BASE_URL: str = Field(default="https://generativelanguage.googleapis.com/v1beta/openai/",
                                 description="Gemini OpenAI-compatible base URL")
    GEMINI_API_KEY: str = Field(default="", description="Gemini API key (required for provider=gemini)")

    # Qdrant
    QDRANT_HOST: str = Field(default="localhost", description="Qdrant Host")
    QDRANT_PORT: int = Field(default=6333, description="Qdrant Port")

    # Mem0 — default provider (used when no provider param supplied by caller)
    MEM0_DEFAULT_PROVIDER: str = Field(default="lmstudio", description="Default embedding provider for Mem0")

    # Mem0 LLM (shared across providers)
    MEM0_LLM_MODEL: str = Field(default="meta-llama-3.1-8b-instruct", description="LLM Model for Mem0")
    MEM0_INFER_MEMORY: bool = Field(default=False, description="Whether to infer memory from interactions")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging Level")


settings = Settings()
