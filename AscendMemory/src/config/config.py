from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Mem0 Configuration
    MEM0_LLM_MODEL: str = Field(default="meta-llama-3.1-8b-instruct", description="LLM Model for Mem0")
    MEM0_EMBEDDING_MODEL: str = Field(default="text-embedding-nomic-embed-text-v2-moe",
                                      description="Embedding Model for Mem0")
    MEM0_EMBEDDING_DIMS: int = Field(default=768, description="Embedding Dimensions for Mem0")
    MEM0_COLLECTION_NAME: str = Field(default="ascend_memory", description="Qdrant Collection Name for Mem0")
    MEM0_INFER_MEMORY: bool = Field(default=False, description="Whether to infer memory from interactions")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging Level")


settings = Settings()
