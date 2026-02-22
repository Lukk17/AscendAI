from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # API Configuration
    API_PORT: int = Field(default=7021, description="Port for the FastAPI/MCP server")
    API_HOST: str = Field(default="0.0.0.0", description="Host to bind the server to")

    # SearXNG Configuration
    # Default to localhost:9020 for local development (accessing host machine port)
    # Docker Compose overrides this to http://searxng:8080 (internal container communication)
    SEARXNG_BASE_URL: str = Field(default="http://localhost:9020", description="URL of the SearXNG instance.")

    # SearXNG Request Headers (Anti-Bot / Auth)
    SEARXNG_USER_AGENT: str = Field(default="AscendWebSearch/1.0", description="User-Agent header for SearXNG requests")
    SEARXNG_X_REAL_IP: str = Field(default="127.0.0.1", description="X-Real-IP header for SearXNG requests")
    SEARXNG_X_FORWARDED_FOR: str = Field(default="127.0.0.1", description="X-Forwarded-For header for SearXNG requests")

    # Blocklist & Validation
    BLOCKLIST_URL: str = Field(default="https://secure.fanboy.co.nz/fanboy-annoyance.txt",
                               description="URL for adblock list")
    VALIDATION_MIN_WORDS: int = Field(default=200, description="Minimum word count for valid content")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")

    # File Assets
    USER_AGENTS_PATH: str = Field(default="src/assets/user_agents.json",
                                  description="Path to the user agents JSON file")
    FILE_ENCODING: str = Field(default="utf-8", description="Default file encoding")

    # Timeouts & Limits
    DEFAULT_TIMEOUT: float = Field(default=30.0, description="Default HTTP request timeout in seconds")
    SEARCH_TIMEOUT: float = Field(default=10.0, description="Timeout for search requests")
    EXTRACT_TIMEOUT: float = Field(default=30.0, description="Timeout for web extraction")

    MAX_REQUESTS_PER_CRAWL: int = Field(default=5, description="Max requests for adaptive crawler")
    DYNAMIC_CONTENT_WAIT: int = Field(default=2000, description="Wait time in ms for dynamic content to load")
    SCROLL_ITERATIONS: int = Field(default=5,
                                   description="Number of scroll steps to trigger infinite-scroll content loading")
    SCROLL_STEP_PX: int = Field(default=1500, description="Pixels to scroll per step when loading dynamic content")

    # Validation Thresholds
    MIN_FLESCH_SCORE: float = Field(default=20.0, description="Minimum Flesch reading ease score")
    MIN_TTR: float = Field(default=0.1, description="Minimum Type-Token Ratio for repetition check")
    ERROR_KEYWORDS: list[str] = Field(
        default=["Access Denied", "403 Forbidden", "Captcha", "Security Check", "Enable JavaScript",
                 "Additional Verification Required", "Ray ID"],
        description="Keywords indicating extraction failure"
    )

    # Cloudflare Bypass / External Services
    FLARESOLVERR_URL: str = Field(default="http://localhost:8191/v1", description="URL for FlareSolverr instance")
    SELENIUM_BROWSER_CDP_URL: str = Field(default="http://localhost:4444", description="CDP URL for remote browser")
    SELENIUM_BROWSER_VNC_URL: str = Field(default="http://localhost:7900",
                                          description="VNC URL for manual captcha solve")
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL for cookie storage")


settings = Settings()
