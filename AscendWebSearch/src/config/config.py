from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_PORT: int = Field(default=7021, description="Port for the FastAPI/MCP server")
    API_HOST: str = Field(default="0.0.0.0", description="Host to bind the server to")

    # Default to localhost:9020 for local development (accessing host machine port).
    # Docker Compose overrides this to http://searxng:8080 (internal container communication).
    SEARXNG_BASE_URL: str = Field(
        default="http://localhost:9020",
        description="URL of the SearXNG instance.",
    )

    SEARXNG_USER_AGENT: str = Field(
        default="AscendWebSearch/1.0",
        description="User-Agent header for SearXNG requests",
    )
    SEARXNG_X_REAL_IP: str = Field(
        default="127.0.0.1",
        description="X-Real-IP header for SearXNG requests",
    )
    SEARXNG_X_FORWARDED_FOR: str = Field(
        default="127.0.0.1",
        description="X-Forwarded-For header for SearXNG requests",
    )

    BLOCKLIST_URL: str = Field(
        default="https://secure.fanboy.co.nz/fanboy-annoyance.txt",
        description="URL the blocklist refresh endpoint downloads from. Never fetched at startup.",
    )
    BLOCKLIST_PATH: str = Field(
        default="src/assets/fanboy-annoyance.txt",
        description=(
            "Path to the vendored ad/annoyance blocklist file. Loaded from disk at startup and never "
            "downloaded automatically. A successful POST /api/v1/blocklist/refresh overwrites this same "
            "file in place, so the next load (and the next process restart) sees the refreshed list."
        ),
    )
    BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS: float = Field(
        default=60.0,
        description=(
            "Minimum seconds between accepted blocklist refresh attempts. A request inside the "
            "window is rejected with 429 rather than hitting the network again."
        ),
    )
    VALIDATION_MIN_WORDS: int = Field(
        default=10,
        description="Minimum word count for valid content",
    )

    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    USER_AGENTS_PATH: str = Field(
        default="src/assets/user_agents.json",
        description="Path to the user agents JSON file",
    )
    FILE_ENCODING: str = Field(default="utf-8", description="Default file encoding")

    DEFAULT_TIMEOUT: float = Field(default=30.0, description="Default HTTP request timeout in seconds")
    SEARCH_TIMEOUT: float = Field(default=10.0, description="Timeout for search requests")
    EXTRACT_TIMEOUT: float = Field(default=30.0, description="Timeout for web extraction")
    CHALLENGE_CLEAR_WAIT_SECONDS: float = Field(
        default=12.0,
        description=(
            "How long the headful Playwright tier waits for a Cloudflare JS/managed challenge "
            "to auto-clear before escalating to NoVNC. JS challenges resolve in ~5-10s in a real "
            "browser; a true interactive Turnstile never auto-clears and escalates after this window. "
            "Bounded by EXTRACT_TIMEOUT."
        ),
    )
    READ_TOTAL_BUDGET: float = Field(
        default=90.0,
        description=(
            "Total wall-clock budget across the strategy chain (tiers 1-5). Once exceeded, "
            "the remaining tiers are skipped and the last partial error is returned. "
            "NoVNC is exempt because it returns 428 immediately."
        ),
    )
    NOVNC_TIMEOUT_SECONDS: int = Field(
        default=600,
        description="Timeout in seconds for NoVNC manual intervention (default 10 mins)",
    )
    NOVNC_COOKIE_SYNC_POLL_SECONDS: float = Field(
        default=5.0,
        description="Poll interval in seconds for the NoVNC cookie-sync background monitor",
    )
    PLAYWRIGHT_HEADLESS: bool = Field(
        default=False,
        description=(
            "Run Chromium in headless mode. Default False keeps the stealth posture; "
            "set True in environments without an X server."
        ),
    )

    MAX_REQUESTS_PER_CRAWL: int = Field(default=5, description="Max requests for adaptive crawler")
    DYNAMIC_CONTENT_WAIT: int = Field(
        default=2000,
        description="Wait time in ms for dynamic content to load",
    )
    SCROLL_ITERATIONS: int = Field(
        default=5,
        description="Number of scroll steps to trigger infinite-scroll content loading",
    )
    SCROLL_STEP_PX: int = Field(
        default=1500,
        description="Pixels to scroll per step when loading dynamic content",
    )

    MIN_FLESCH_SCORE: float = Field(default=20.0, description="Minimum Flesch reading ease score")
    MIN_TTR: float = Field(default=0.1, description="Minimum Type-Token Ratio for repetition check")
    ERROR_KEYWORDS: list[str] = Field(
        default=[
            "Access Denied",
            "403 Forbidden",
            "Captcha",
            "Security Check",
            "Enable JavaScript",
            "Additional Verification Required",
            "Ray ID",
        ],
        description="Keywords indicating extraction failure",
    )

    FLARESOLVERR_URL: str = Field(
        default="http://localhost:8191/v1",
        description="URL for FlareSolverr instance",
    )
    SELENIUM_BROWSER_CDP_URL: str = Field(
        default="ws://localhost:4444/playwright",
        description="CDP URL for remote browser",
    )
    SELENIUM_BROWSER_VNC_URL: str = Field(
        default="http://localhost:7900",
        description="VNC URL for manual captcha solve",
    )
    PUBLIC_VNC_URL: str = Field(
        default="http://localhost:7900",
        description="Public Internet-facing VNC URL (can be Ngrok api string)",
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for cookie storage",
    )

    # Session TTLs
    SESSION_AUTH_TTL_SECONDS: int = Field(
        default=1_209_600,
        description="Sliding TTL for auth cookies (long-lived; default 14 days)",
    )
    SESSION_WAF_TTL_SECONDS: int = Field(
        default=1800,
        description="TTL for WAF-clearance cookies (short-lived; default 30 min)",
    )
    SESSION_DEFAULT_PROFILE: str = Field(
        default="default",
        description="Profile label used when no profile is specified per-request",
    )

    # Challenge detection
    CHALLENGE_DETECTION_MAX_BYTES: int = Field(
        default=50_000,
        description=(
            "Prefix length scanned by ChallengeDetector. Pages larger than this "
            "were previously skipped entirely; now we scan only the prefix."
        ),
    )
    CHALLENGE_WALL_MAX_BYTES: int = Field(
        default=50_000,
        description=(
            "Max page size for a weak marker (an embedded Turnstile widget or a "
            "cf_clearance token) to count as a block. A real page can host a Turnstile "
            "widget while serving full content (e.g. nowsecure.nl), so these only signal "
            "a challenge wall on an interstitial-sized page. Strong markers (Ray ID, "
            "interstitial phrases, third-party captcha scripts) fire regardless of size."
        ),
    )

    # Crawlee storage root (outside src/ to avoid committing runtime state)
    CRAWLEE_STORAGE_DIR: str = Field(
        default=".crawlee_storage",
        description="Out-of-tree directory for Crawlee request queues and key-value stores",
    )
    CRAWLEE_MEMORY_MBYTES: int | None = Field(
        default=None,
        description=(
            "Explicit memory budget in MB for Crawlee's autoscaler, propagated to the "
            "CRAWLEE_MEMORY_MBYTES environment variable Crawlee itself reads. When unset, "
            "Crawlee infers a budget as a ratio of total system memory instead."
        ),
    )

    # Group 4 — Anti-bot evasion: proxy seam (off by default)
    PROXY_URL: str = Field(
        default="",
        description=(
            "Optional outbound proxy URL for all fetch tiers (e.g. socks5://user:pass@host:port). "
            "Empty string (the default) disables proxy egress entirely."
        ),
    )

    # Group 5 — Extraction quality: readability fallback threshold
    READABILITY_FALLBACK_MIN_CHARS: int = Field(
        default=200,
        description=(
            "Minimum character count of trafilatura output below which the readability-lxml "
            "fallback is attempted.  The higher-scoring result (by character count) is returned."
        ),
    )

    # Group 7 — Caching: read-result cache TTL
    READ_CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL in seconds for the read-result cache-aside entries (default 5 min).",
    )

    # Group 7 — Observability: per-domain metric label cardinality cap
    DOMAIN_METRIC_CARDINALITY_CAP: int = Field(
        default=50,
        description=(
            "Maximum number of distinct registrable-domain label values tracked in "
            "STRATEGY_ATTEMPTS_TOTAL.  Domains beyond this cap are bucketed under 'other'."
        ),
    )

    # Group 7 — Circuit breaker thresholds
    BREAKER_FAILURE_THRESHOLD: int = Field(
        default=3,
        description="Consecutive failures before a circuit breaker opens.",
    )
    BREAKER_RECOVERY_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        description="Seconds after which an open breaker moves to half-open and allows one probe.",
    )


settings = Settings()
