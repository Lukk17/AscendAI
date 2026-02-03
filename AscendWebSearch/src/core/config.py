from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Configuration
    API_PORT: int = 7021
    API_HOST: str = "0.0.0.0"
    
    # SearXNG
    SEARXNG_BASE_URL: str

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_case_sensitive = True

settings = Settings()
