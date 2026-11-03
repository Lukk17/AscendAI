from prometheus_client import Counter, Gauge, Histogram

from src.config.config import settings

# outcome label value "ok", observed once per completed search
SEARCH_RESULTS_RETURNED = Histogram(
    "search_results_returned",
    "Number of search results returned per search",
    ["engine", "outcome"],
    buckets=(1, 2, 3, 5, 10, 20, 50),
)

STRATEGY_ATTEMPTS_TOTAL = Counter(
    "strategy_attempts_total",
    "Strategy invocation outcomes",
    ["strategy", "outcome", "domain"],
)

STRATEGY_DURATION_SECONDS = Histogram(
    "strategy_duration_seconds",
    "Wall-clock duration of each strategy invocation",
    ["strategy"],
    # Buckets extend past READ_TOTAL_BUDGET=90s plus a head-room tail
    # for NoVNC monitor tasks (10 min default).
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 90, 120, 300, 600),
)

HUMAN_INTERVENTION_TOTAL = Counter(
    "human_intervention_total",
    "HumanInterventionRequiredException surfaces (428 responses)",
    ["intervention_type", "joined"],
)

SEARXNG_REQUESTS_TOTAL = Counter(
    "searxng_requests_total",
    "SearXNG client outcomes",
    ["outcome"],
)

SEARXNG_DURATION_SECONDS = Histogram(
    "searxng_duration_seconds",
    "Wall-clock duration of SearXNG search calls",
    buckets=(0.1, 0.5, 1, 2, 5, 10),
)

REDIS_OPS_TOTAL = Counter(
    "redis_ops_total",
    "Redis operations from CookieManager",
    ["op", "result"],
)

READ_BUDGET_EXHAUSTED_TOTAL = Counter(
    "read_budget_exhausted_total",
    "Reads that exited because READ_TOTAL_BUDGET was exceeded before any strategy succeeded",
)

READ_CACHE_HITS_TOTAL = Counter(
    "read_cache_hits_total",
    "Read requests served from cache without re-running the strategy chain",
)

CIRCUIT_BREAKER_OPEN_TOTAL = Counter(
    "circuit_breaker_open_total",
    "Number of times a circuit breaker transitioned to OPEN state",
    ["dependency"],
)

NOVNC_FLOW_BUSY_TOTAL = Counter(
    "novnc_flow_busy_total",
    "Requests rejected because a NoVNC intervention was already holding the shared browser/display",
)

NOVNC_ACTIVE_FLOWS = Gauge(
    "novnc_active_flows",
    "Live human-intervention flows of this container",
)

NOVNC_FLOWS_RECLAIMED_TOTAL = Counter(
    "novnc_flows_reclaimed_total",
    "Intervention flows reclaimed by reason",
    ["reason"],
)

_CHALLENGE_SCORE_BUCKETS_BASE = (0, 20, 40, 60, 80, 100, 120, 160, 200, 300)


def challenge_score_buckets(threshold: int) -> tuple[int, ...]:
    """Histogram boundaries for the scored verdict: one boundary at each score
    that matters at the default weights, plus the configured threshold when an
    override moves it off the list, so near misses on both sides stay visible."""
    return tuple(sorted(set(_CHALLENGE_SCORE_BUCKETS_BASE) | {threshold}))


CHALLENGE_SIGNALS_FIRED_TOTAL = Counter(
    "challenge_signals_fired_total",
    "Fired challenge signals per verdict",
    ["signal", "vendor"],
)

CHALLENGE_VERDICTS_TOTAL = Counter(
    "challenge_verdicts_total",
    "Challenge verdicts per tier",
    ["verdict", "tier"],
)

CHALLENGE_SCORE = Histogram(
    "challenge_score",
    "Scored challenge verdict totals",
    buckets=tuple(float(bound) for bound in challenge_score_buckets(settings.CHALLENGE_SCORE_THRESHOLD)),
)
