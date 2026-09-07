from prometheus_client import Counter, Histogram

# Outcome label values: "success" | "error" | "validation_error"
MEMORY_INSERT_TOTAL = Counter(
    "memory_insert_total",
    "memory_insert outcomes",
    ["provider", "outcome"],
)

MEMORY_SEARCH_TOTAL = Counter(
    "memory_search_total",
    "memory_search outcomes",
    ["provider", "outcome"],
)

MEMORY_DELETE_TOTAL = Counter(
    "memory_delete_total",
    "memory_delete outcomes",
    ["provider", "outcome"],
)

MEMORY_WIPE_TOTAL = Counter(
    "memory_wipe_total",
    "memory_wipe outcomes",
    ["provider", "outcome"],
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
    ["provider"],
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
