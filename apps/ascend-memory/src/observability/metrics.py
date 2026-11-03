from prometheus_client import Counter, Histogram

# Outcome label values follow the closed set of the `service-metrics`
# capability: "ok" | "error" | "timeout" | "rate_limited" | "not_found".


def outcome_for_exception(exc: BaseException) -> str:
    """Map a handler failure onto the closed outcome set.

    TimeoutError (asyncio.TimeoutError is its alias since 3.11) maps to
    "timeout". Rate-limit refusals, either the middleware text or a 429
    from upstream, map to "rate_limited". A missing memory maps to
    "not_found". Everything else maps to "error".
    """

    if isinstance(exc, TimeoutError):
        return "timeout"
    text = f"{type(exc).__name__}: {exc}".lower()
    if "rate_limited" in text or "rate limit" in text or "429" in text:
        return "rate_limited"
    if "not_found" in text or "not found" in text:
        return "not_found"
    if isinstance(exc, (KeyError, FileNotFoundError, LookupError)):
        return "not_found"
    return "error"


MEMORY_OPERATIONS_TOTAL = Counter(
    "memory_operations_total",
    "memory operation outcomes",
    ["operation", "outcome"],
)

# Bucket choices target the realistic latency spread: LM Studio embed
# (~50-300 ms), OpenAI embed (~200-800 ms), wipe of mid-thousands of
# memories (~10-60 s after the delete_all batching fix).
MEMORY_INSERT_DURATION_SECONDS = Histogram(
    "memory_insert_duration_seconds",
    "Wall-clock duration of insert operations",
    ["provider"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)

MEMORY_SEARCH_DURATION_SECONDS = Histogram(
    "memory_search_duration_seconds",
    "Wall-clock duration of search operations",
    ["embedding_provider"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)

MEMORY_DELETE_DURATION_SECONDS = Histogram(
    "memory_delete_duration_seconds",
    "Wall-clock duration of delete operations",
    ["provider"],
    buckets=(0.05, 0.1, 0.5, 1, 2, 5),
)

MEMORY_WIPE_DURATION_SECONDS = Histogram(
    "memory_wipe_duration_seconds",
    "Wall-clock duration of wipe operations",
    ["provider"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
