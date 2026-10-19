from urllib.parse import urlparse

from ascend_python_common.settings import CsvTuple, RateLimit, ServiceSettings
from pydantic import Field, field_validator, model_validator


class Settings(ServiceSettings):
    API_PORT: int = Field(default=7021, ge=1, le=65535, description="Port for the FastAPI/MCP server")

    # Default to localhost:9020 for local development (accessing host machine port).
    # Docker Compose overrides this to http://searxng:8080 (internal container communication).
    SEARXNG_BASE_URL: str = Field(
        default="http://localhost:9020",
        description="URL of the SearXNG instance.",
    )

    SEARXNG_USER_AGENT: str = Field(
        default="ascend-web-hunter/1.0",
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

    RATE_LIMIT_DEFAULT: RateLimit = Field(
        default="1200/minute",
        description="Default rate limit for REST routes and MCP tools",
    )

    ALLOWED_PRIVATE_HOSTS: CsvTuple = Field(
        default=(),
        description=(
            "Hosts the URI fetch guard may reach even at a private address. "
            "Leave empty, only an e2e sweep sets it."
        ),
    )
    FETCH_MAX_REDIRECT_HOPS: int = Field(
        default=10,
        ge=0,
        description="Redirect hops the URI fetch guard follows.",
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
    NOVNC_MAX_CONCURRENT_FLOWS: int = Field(
        default=4,
        ge=1,
        description=(
            "Maximum concurrent human-intervention windows per container. A per container "
            "memory constraint as much as a display one: each flow runs its own headful "
            "Chromium. A request past the cap answers 409."
        ),
    )
    NOVNC_DISPLAY_SIZE: str = Field(
        default="1920x1080",
        description=(
            "Size of the shared Xvfb display as <width>x<height>. Xvfb and the service read "
            "the same variable; the Dockerfile also sets it for a container started without compose."
        ),
    )
    NOVNC_WINDOW_WIDTH_PX: int = Field(
        default=1280,
        ge=1,
        description="Width in pixels of each intervention window. Wide enough for a reCAPTCHA image grid.",
    )
    NOVNC_WINDOW_HEIGHT_PX: int = Field(
        default=800,
        ge=1,
        description="Height in pixels of each intervention window.",
    )
    NOVNC_WINDOW_CASCADE_OFFSET_PX: int = Field(
        default=48,
        ge=1,
        description="Cascade step in pixels between intervention windows. Wider than a fluxbox title bar.",
    )
    NOVNC_FLOW_LEASE_GRACE_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description="Teardown grace added on top of NOVNC_TIMEOUT_SECONDS before a held flow is reclaimed.",
    )
    NOVNC_FLOW_SWEEP_INTERVAL_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description="Interval in seconds between lease-sweeper runs. One lease grace period.",
    )
    NOVNC_FLOW_CANCEL_GRACE_SECONDS: float = Field(
        default=10.0,
        gt=0,
        description="Bounds reclamation and shutdown. A browser that has not closed in this time will not.",
    )
    NOVNC_BUSY_RETRY_AFTER_SECONDS: int = Field(
        default=30,
        ge=1,
        description=(
            "Short actionable poll interval answered in the 409 Retry-After header, not the flow timeout."
        ),
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
    NOVNC_PUBLIC_URL: str | None = Field(
        default=None,
        description=(
            "One base address shared by every ascend-web-hunter container, the address of the "
            "web-hunter edge proxy, an absolute http or https URL with no path. Unset keeps "
            "today's PUBLIC_VNC_URL resolution and the one Ngrok tunnel, which serve one container."
        ),
    )
    REDIS_URL: str = Field(
        default="redis://127.0.0.1:6379/0",
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
        ge=1,
        description=(
            "Prefix length scanned by the vendor, structure and phrase families. "
            "Only the first bytes of a page are read for those signals."
        ),
    )
    CHALLENGE_WALL_MAX_BYTES: int = Field(
        default=50_000,
        ge=1,
        description=(
            "Page size under which a 403, 429 or 503 body counts as small, and under "
            "which the word floor is computed. Larger pages pass the word floor automatically."
        ),
    )

    # Challenge scoring: tuning values (design Decision 2, owner rule 98 of 2026-10-08)
    CHALLENGE_SCORE_THRESHOLD: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Score at or above which a page is a wall. No non-definitive signal reaches it alone.",
    )
    CHALLENGE_RICH_CONTENT_WORDS: int = Field(
        default=150,
        ge=1,
        description="Extracted words at or above which the rich-content guard fires.",
    )
    CHALLENGE_FORM_DOMINANCE_RATIO: float = Field(
        default=0.6,
        gt=0,
        le=1.0,
        description="Share of visible text inside forms at or above which form dominance fires.",
    )
    CHALLENGE_MIN_WORDS_PER_KB: float = Field(
        default=2.0,
        gt=0,
        description="Extracted words per kilobyte of HTML under which thin text fires.",
    )
    CHALLENGE_THIN_LINK_COUNT: int = Field(
        default=5,
        ge=0,
        description="Fewer anchors with href than this fires few links.",
    )
    CHALLENGE_RICH_LINK_COUNT: int = Field(
        default=20,
        ge=0,
        description="At least this many anchors with href fires the many-links guard.",
    )
    CHALLENGE_SHAPE_MAX_BYTES: int = Field(
        default=500_000,
        ge=1,
        description="Bounds the extraction the shape family uses. Larger pages contribute no shape signal.",
    )

    # Challenge scoring: per-signal weights (design Decision 2, owner rule 98 of 2026-10-08)
    CHALLENGE_WEIGHT_DEFINITIVE_HEADER: int = Field(
        default=200, ge=-1_000, le=1_000, description="Weight of the definitive_header signal."
    )
    CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE: int = Field(
        default=80, ge=-1_000, le=1_000, description="Weight of the interstitial_structure signal."
    )
    CHALLENGE_WEIGHT_VENDOR_SCRIPT: int = Field(
        default=60, ge=-1_000, le=1_000, description="Weight of the vendor_script signal."
    )
    CHALLENGE_WEIGHT_VENDOR_PRESENCE: int = Field(
        default=30, ge=-1_000, le=1_000, description="Weight of the vendor_presence signal."
    )
    CHALLENGE_WEIGHT_STATUS_EMPTY_BODY: int = Field(
        default=200, ge=-1_000, le=1_000, description="Weight of the status_empty_body signal."
    )
    CHALLENGE_WEIGHT_STATUS_SMALL_BODY: int = Field(
        default=50, ge=-1_000, le=1_000, description="Weight of the status_small_body signal."
    )
    CHALLENGE_WEIGHT_STATUS_LARGE_BODY: int = Field(
        default=20, ge=-1_000, le=1_000, description="Weight of the status_large_body signal."
    )
    CHALLENGE_WEIGHT_CAPTCHA_INPUT: int = Field(
        default=50, ge=-1_000, le=1_000, description="Weight of the captcha_input signal."
    )
    CHALLENGE_WEIGHT_CAPTCHA_ELEMENT: int = Field(
        default=40, ge=-1_000, le=1_000, description="Weight of the captcha_element signal."
    )
    CHALLENGE_WEIGHT_FORM_DOMINANCE: int = Field(
        default=40, ge=-1_000, le=1_000, description="Weight of the form_dominance signal."
    )
    CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY: int = Field(
        default=40, ge=-1_000, le=1_000, description="Weight of the script_only_body signal."
    )
    CHALLENGE_WEIGHT_THIN_TEXT: int = Field(
        default=20, ge=-1_000, le=1_000, description="Weight of the thin_text signal."
    )
    CHALLENGE_WEIGHT_FEW_LINKS: int = Field(
        default=20, ge=-1_000, le=1_000, description="Weight of the few_links signal."
    )
    CHALLENGE_WEIGHT_NO_ARTICLE: int = Field(
        default=20, ge=-1_000, le=1_000, description="Weight of the no_article signal."
    )
    CHALLENGE_WEIGHT_RICH_CONTENT: int = Field(
        default=-60, ge=-1_000, le=1_000, description="Weight of the rich_content guard signal."
    )
    CHALLENGE_WEIGHT_MANY_LINKS: int = Field(
        default=-20, ge=-1_000, le=1_000, description="Weight of the many_links guard signal."
    )
    CHALLENGE_WEIGHT_PHRASE_TITLE: int = Field(
        default=60, ge=-1_000, le=1_000, description="Weight of the phrase_title signal."
    )
    CHALLENGE_WEIGHT_PHRASE_BODY: int = Field(
        default=30, ge=-1_000, le=1_000, description="Weight of the phrase_body signal."
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

    # Group 4 - Anti-bot evasion: proxy seam (off by default)
    PROXY_URL: str = Field(
        default="",
        description=(
            "Optional outbound proxy URL for all fetch tiers (e.g. socks5://user:pass@host:port). "
            "Empty string (the default) disables proxy egress entirely."
        ),
    )

    # Group 5 - Extraction quality: readability fallback threshold
    READABILITY_FALLBACK_MIN_CHARS: int = Field(
        default=200,
        description=(
            "Minimum character count of trafilatura output below which the readability-lxml "
            "fallback is attempted.  The higher-scoring result (by character count) is returned."
        ),
    )
    CONTENT_RECALL_FALLBACK_RATIO: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description=(
            "Ratio of trafilatura's precision-mode output length to the page's plain text length "
            "(BeautifulSoup get_text after noise tags are removed) below which a second trafilatura "
            "pass runs with favor_recall=True. The longer of the two passes is returned. 0 never runs "
            "the recall pass, 1 always runs it."
        ),
    )

    # Group 7 - Caching: read-result cache TTL
    READ_CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL in seconds for the read-result cache-aside entries (default 5 min).",
    )

    # Group 7 - Observability: per-domain metric label cardinality cap
    DOMAIN_METRIC_CARDINALITY_CAP: int = Field(
        default=50,
        description=(
            "Maximum number of distinct registrable-domain label values tracked in "
            "STRATEGY_ATTEMPTS_TOTAL.  Domains beyond this cap are bucketed under 'other'."
        ),
    )

    # Group 7 - Circuit breaker thresholds
    BREAKER_FAILURE_THRESHOLD: int = Field(
        default=3,
        description="Consecutive failures before a circuit breaker opens.",
    )
    BREAKER_RECOVERY_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        description="Seconds after which an open breaker moves to half-open and allows one probe.",
    )

    @model_validator(mode="after")
    def _validate_novnc_display_size(self) -> "Settings":
        parts = self.NOVNC_DISPLAY_SIZE.split("x")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError(
                f"NOVNC_DISPLAY_SIZE {self.NOVNC_DISPLAY_SIZE!r} must read <width>x<height>, e.g. '1920x1080'"
            )
        width, height = int(parts[0]), int(parts[1])
        if width < self.NOVNC_WINDOW_WIDTH_PX:
            raise ValueError(
                f"NOVNC_DISPLAY_SIZE {self.NOVNC_DISPLAY_SIZE!r} is smaller than "
                f"NOVNC_WINDOW_WIDTH_PX ({self.NOVNC_WINDOW_WIDTH_PX}) on the x axis"
            )
        if height < self.NOVNC_WINDOW_HEIGHT_PX:
            raise ValueError(
                f"NOVNC_DISPLAY_SIZE {self.NOVNC_DISPLAY_SIZE!r} is smaller than "
                f"NOVNC_WINDOW_HEIGHT_PX ({self.NOVNC_WINDOW_HEIGHT_PX}) on the y axis"
            )
        return self

    @field_validator("NOVNC_PUBLIC_URL")
    @classmethod
    def _validate_novnc_public_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path != "":
            raise ValueError(
                f"NOVNC_PUBLIC_URL must be an absolute http or https URL with no path, got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_challenge_weights(self) -> "Settings":
        if self.CHALLENGE_WALL_MAX_BYTES > self.CHALLENGE_SHAPE_MAX_BYTES:
            raise ValueError(
                "CHALLENGE_WALL_MAX_BYTES must not exceed CHALLENGE_SHAPE_MAX_BYTES"
            )
        if self.CHALLENGE_THIN_LINK_COUNT > self.CHALLENGE_RICH_LINK_COUNT:
            raise ValueError(
                "CHALLENGE_THIN_LINK_COUNT must not exceed CHALLENGE_RICH_LINK_COUNT"
            )
        if self.CHALLENGE_WEIGHT_RICH_CONTENT > 0:
            raise ValueError(
                "CHALLENGE_WEIGHT_RICH_CONTENT must not be positive"
            )
        if self.CHALLENGE_WEIGHT_MANY_LINKS > 0:
            raise ValueError(
                "CHALLENGE_WEIGHT_MANY_LINKS must not be positive"
            )
        negative_guards = {
            "CHALLENGE_WEIGHT_RICH_CONTENT",
            "CHALLENGE_WEIGHT_MANY_LINKS",
        }
        allowed_single = {
            "CHALLENGE_WEIGHT_DEFINITIVE_HEADER",
            "CHALLENGE_WEIGHT_STATUS_EMPTY_BODY",
        }
        weight_names = (
            "CHALLENGE_WEIGHT_DEFINITIVE_HEADER",
            "CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE",
            "CHALLENGE_WEIGHT_VENDOR_SCRIPT",
            "CHALLENGE_WEIGHT_VENDOR_PRESENCE",
            "CHALLENGE_WEIGHT_STATUS_EMPTY_BODY",
            "CHALLENGE_WEIGHT_STATUS_SMALL_BODY",
            "CHALLENGE_WEIGHT_STATUS_LARGE_BODY",
            "CHALLENGE_WEIGHT_CAPTCHA_INPUT",
            "CHALLENGE_WEIGHT_CAPTCHA_ELEMENT",
            "CHALLENGE_WEIGHT_FORM_DOMINANCE",
            "CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY",
            "CHALLENGE_WEIGHT_THIN_TEXT",
            "CHALLENGE_WEIGHT_FEW_LINKS",
            "CHALLENGE_WEIGHT_NO_ARTICLE",
            "CHALLENGE_WEIGHT_RICH_CONTENT",
            "CHALLENGE_WEIGHT_MANY_LINKS",
            "CHALLENGE_WEIGHT_PHRASE_TITLE",
            "CHALLENGE_WEIGHT_PHRASE_BODY",
        )
        for name in weight_names:
            if name in negative_guards or name in allowed_single:
                continue
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        for name in weight_names:
            if name in allowed_single:
                continue
            value = getattr(self, name)
            if value >= self.CHALLENGE_SCORE_THRESHOLD:
                raise ValueError(
                    f"{name} must stay below CHALLENGE_SCORE_THRESHOLD"
                )
        return self


settings = Settings()
