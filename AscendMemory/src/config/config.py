from typing import Dict, Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Embedding provider configs — each maps to a Qdrant collection by dimension
# Providers sharing the same dims share the same collection
PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "lmstudio": {
        "embedding_model": "text-embedding-nomic-embed-text-v2-moe",
        "embedding_dims": 768,
        "collection_name": "ascend_memory_768",
    },
    "openai": {
        "embedding_model": "text-embedding-3-small",
        "embedding_dims": 1536,
        "collection_name": "ascend_memory_1536",
    },
    "gemini": {
        "embedding_model": "gemini-embedding-001",
        "embedding_dims": 768,
        "collection_name": "ascend_memory_768",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Configuration
    API_PORT: int = Field(default=7020, description="Port for the FastAPI server")
    API_HOST: str = Field(default="0.0.0.0", description="Host to bind the server to")

    # OpenAI
    OPENAI_API_KEY: str = Field(default="sk_local", description="OpenAI API Key")
    OPENAI_BASE_URL: str = Field(default="http://localhost:1234/v1", description="OpenAI Base URL")

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