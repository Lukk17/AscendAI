from prometheus_client import Counter, Histogram

STRATEGY_ATTEMPTS_TOTAL = Counter(
    "strategy_attempts_total",
    "Strategy invocation outcomes",
    ["strategy", "outcome"],
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
    ["intervention_type"],
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
