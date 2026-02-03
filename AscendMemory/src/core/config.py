from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Configuration
    API_PORT: int = 7020
    API_HOST: str = "0.0.0.0"
    
    # OpenAI
    OPENAI_API_KEY: str ="sk_local"
    OPENAI_BASE_URL: str = "http://host.docker.internal:1234/v1"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Mem0 Configuration
    MEM0_LLM_MODEL: str = "meta-llama-3.1-8b-instruct"
    MEM0_EMBEDDING_MODEL: str = "text-embedding-nomic-embed-text-v2-moe"
    MEM0_EMBEDDING_DIMS: int = 768
    MEM0_COLLECTION_NAME: str = "ascend_memory"
    MEM0_INFER_MEMORY: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"

settings = Settings()
