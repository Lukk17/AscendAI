## Why

The service reads every document with a model nobody chose. `pyproject.toml` pins `paddleocr==3.6.0`, and at that
version the library's own resolution table (`PaddleOCR._get_ocr_model_names` in
`paddleocr/_pipelines/ocr.py`, read from this module's `.venv`) maps all twelve codes in `SUPPORTED_LANGUAGES` onto
one detector: `PP-OCRv5_server_det`. That detector is 88.4 MB of artifacts on Hugging Face, 84.3 MiB, and it is 94
percent of one call's transient memory (4984 of the fitted 5302 MiB per megapixel, recorded in
[ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md)) and most of its time. Nothing
in this repository names it. It arrived as a default and stayed as one.

PaddleOCR 3.7.0 ships a newer family, PP-OCRv6, in three sizes. On PaddleOCR's own published head-to-head, the same
test set for every row and an Intel Xeon for the timings (vendor numbers, not measured here):

| Family member | Detection | Recognition | Seconds per image |
|---|---|---|---|
| `PP-OCRv5_server` (what runs today) | 81.6 | 78.1 | 2.04 |
| `PP-OCRv6_small` | 84.1 | 81.3 | 0.79 |
| `PP-OCRv6_medium` | 86.2 | 83.2 | 2.05 |

So the small member is better than the incumbent on both accuracy axes and 2.6 times faster. PaddleOCR also states
that the new family covers 50 languages in a single model, Polish among them, with about 200 diacritical characters
added. Today this service loads a separate engine per language at a measured 143 MiB each (superseded 2026-09-25: an
idle engine costs about 209 MiB measured in the container, see `fix-ocr-page-resolution` design.md Decision 10), because the cache is keyed
by language rather than by the models a language resolves to.

Two smaller facts decide the shape of the change rather than whether to make it.

The library's own default in 3.7.0 is the **medium** member, not the small one: `_get_ocr_model_names` returns
`PP-OCRv6_medium_det` / `PP-OCRv6_medium_rec` for every language the family covers. Accepting that default would
repeat exactly the mistake this change exists to correct, and it would buy accuracy at the incumbent's speed rather
than at 2.6 times it. So the model pair becomes an explicit, configurable decision with the small pair as the shipped
default, and switching to medium is two environment variables rather than a code change.

The family does not cover every language this service declares. `_PPOCRV6_LANGS` in 3.7.0 is
`{ch, chinese_cht, en, japan}` plus every Latin language except `pi`. Of the twelve codes in `SUPPORTED_LANGUAGES`,
ten fall inside it and two do not: `ru` and `korean`. Those two keep the PP-OCRv5 pair they already run today, and
this change writes that pair down instead of leaving it to be resolved implicitly a second time.

## What Changes

**The pin.** `paddleocr==3.6.0` becomes `paddleocr==3.7.0`. Verified from package metadata before writing this, so
the one real risk is ruled out rather than hoped away: `paddleocr==3.7.0` requires `paddlex[ocr-core]>=3.7.0,<3.8.0`,
`paddlex` 3.7.2 declares the same eighteen core packages and the same six `ocr-core` extras as the installed 3.6.1
with `paddlepaddle` among neither, and paddlex's own runtime check for it is presence-only
(`importlib.util.find_spec("paddle")` in `paddlex/utils/deps.py`, byte-identical between the two versions) with no
version specifier anywhere. `paddlepaddle==3.3.1` therefore stays exactly where it is, and the only installed package
that moves is paddlex.

**The model choice becomes explicit and named.** `OcrService._get_engine` stops passing `lang=` and passes
`text_detection_model_name` and `text_recognition_model_name` instead, so the constructor takes the models this
service chose rather than the ones the library would pick. Two new settings carry the default pair,
`OCR_TEXT_DETECTION_MODEL=PP-OCRv6_small_det` and `OCR_TEXT_RECOGNITION_MODEL=PP-OCRv6_small_rec`. A named table in
`config.py` carries the pair for each language the default family does not cover, which today is `ru` and `korean`
and both keep what they run now. An unsupported language is still refused by the `SUPPORTED_LANGUAGES` allowlist
before any model is named, unchanged.

**The engine cache is keyed by the resolved model pair.** Keyed by language, the cache would now hold ten identical
engines for ten languages that resolve to one pair. Keyed by the pair, the tenth language costs nothing once the
first has warmed. The twelve declared languages collapse to three distinct engines: the default pair, `ru`'s
`PP-OCRv5_server_det` / `eslav_PP-OCRv5_mobile_rec`, and `korean`'s `PP-OCRv5_server_det` /
`korean_PP-OCRv5_mobile_rec`. Under today's key they collapse to none, and `en` and `pl` build two separate engines
for two rec models that differ by 0.2 MB of artifacts.

**`ENGINE_CACHE_MAX_SIZE` keeps its value and loses its reason.** It stays 2, because that is the configuration the
container's memory ceiling is sized against and no re-measurement is possible on the host as it is today. Its
documented reason, "the two languages `en` and `pl` the Dockerfile pre-caches", is now false twice over: those two
languages are one engine, and the image pre-caches one pair rather than two languages. The new reason is the pair
everything common uses, plus one slot so a `ru` or `korean` request does not evict it. Both alternatives are costed
in [design.md](design.md) Decision 4.

**The image pre-caches the models it actually runs.** The Dockerfile's warm-up `RUN` currently constructs
`PaddleOCR(lang='en')` and `PaddleOCR(lang='pl')`, which bakes `PP-OCRv5_server_det` plus two rec models, 104.6 MB of
detection and recognition artifacts. It now constructs one engine from the two settings, so the baked pair cannot
drift from the deployed default, and the detection and recognition artifacts drop to 31.6 MB. Sizes are the Hugging
Face repository trees for each model, read at the time of writing.

**The observability label follows the key.** `ascendocr_engine_cache_evictions_total` is labelled `language` today.
A label named `language` carrying `PP-OCRv6_small_det/PP-OCRv6_small_rec` would be a lie, so the label becomes
`engine`. Nothing outside the service reads it: no dashboard, alert rule, or document in this repository mentions the
metric (verified by grep across `*.md`, `*.json`, `*.yaml`, `*.yml`).

**No contract changes.** No request parameter, no response field, no error code, and no endpoint moves. The `lang`
parameter keeps meaning exactly what it meant: which language the caller is submitting. What changed is which model
answers it.

**What a caller can see** is the output of a different model. PaddleOCR's published numbers say that is better on
both detection and recognition, and it cannot be confirmed against the owner's own documents on this host today, so
the accuracy verification is written as tasks with the exact commands rather than claimed. The one place a
regression would show first is end-to-end spec 3, which asserts Polish diacritics in the recognised text.

## Capabilities

### New Capabilities

- `ocr-model-selection`: which detection and recognition models the service runs, how a language resolves to a pair,
  how that choice is configured, and what the engine cache is keyed by.

### Modified Capabilities

None. No capability under `openspec/specs/` covers the ascend-ocr module today. The four capabilities in
`openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` are not archived yet, so this change touches none of them
directly. Where it makes one of their statements narrower or wider, `design.md` Decision 6 says which and why.

## Impact

Code, all under `apps/ascend-ocr/`:

- `pyproject.toml`: the `paddleocr` pin.
- `src/config/config.py`: `OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL`, the `ModelPair` value object,
  the `LANGUAGE_MODEL_OVERRIDES` table for languages outside the default family, and a corrected reason on
  `ENGINE_CACHE_MAX_SIZE`.
- `src/service/ocr_service.py`: `_resolve_model_pair`, an engine cache keyed by `ModelPair`, explicit model names on
  the `PaddleOCR(...)` call in place of `lang`, and an eviction log line that names the engine rather than a
  language.
- `src/observability/metrics.py`: the eviction counter's label.
- `Dockerfile`: the warm-up `RUN` reads the two settings instead of naming two languages.

Tests, under `apps/ascend-ocr/tests/`. The gate is `--cov-fail-under=100` with `--cov-branch`, so every branch added
needs a test. `tests/service/test_ocr_service.py` gains the resolution and cache-key cases and loses the assumption
that two languages mean two engines, `tests/config/test_config.py` gains the two settings and the override table, and
`tests/test_main.py` follows the metric label.

Dependencies: `paddleocr` 3.6.0 to 3.7.0, pulling `paddlex` 3.6.1 to 3.7.x. No new package, no removed package, and
`paddlepaddle==3.3.1` untouched. Both statements are read from metadata, not assumed.

Docs: `apps/ascend-ocr/AGENTS.md`, `README.md`, `docs/CONFIGURATION.md`, arc42 chapters 04, 07, 08, 11 and 12, an
amendment to [ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md) where it says the
cache key is the language and names the detector's export geometry, and one new ADR recording the family choice, the
size within it, and the two languages that keep the old pair.

Operational: the first container built from this change downloads the new models at build time, as the current one
does. A running container with a `.paddlex` cache from the old image has no cached copy of the new pair, so the first
request after the upgrade downloads it unless the image is rebuilt. Rebuilding is the intended path and the
Dockerfile change covers it.

Memory: the fitted model `peak_MiB = 635 + 5302 x megapixels + 11.5 x pages` was measured against
`PP-OCRv5_server_det`. The detection term is that detector's cost. The new default detector is 10.1 MB of artifacts
against 88.4 MB, so the fitted model is expected to over-state the new default pair and to stay exactly right for
`ru` and `korean`, which still run the old detector. Expected is not measured, so every number in the startup banner,
in `docs/architecture/memory-budget.md` and in 07-deployment-view.md is left as it stands, correct as an upper bound,
with re-measurement written as a task. Lowering a memory estimate on a guess would be worse than leaving a
conservative one in place.

Reconciled on 2026-09-24. The expectation above is now measured: one A4 page at 300 dots per inch costs about 440 MB
flat on the new pair (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.), which makes the fitted model void rather than conservative for every language but `ru` and
`korean`. [read-long-documents](../read-long-documents/design.md) records that measurement and is its one account.
Task 4.6 still owns updating the startup banner constants and the two documents named above from it.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/tdd-workflow`, `/ai-regression-testing`
- `/coding-standards`, `/code-formatter`, `/review-duplication`
- `/build-dependency-management` for the pin and its transitive extras
- `/docker-patterns` for the pre-cache step
- `/observability-and-logging` for the metric label
- `/performance-optimization` for the measure-before-claiming discipline the verification tasks rest on
