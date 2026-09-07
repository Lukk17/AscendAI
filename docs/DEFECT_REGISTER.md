# Defect register

As of 2026-09-07, HEAD `814a1b33f0ec816177009ed4c4e02e83a9edd850` on `master`. Compiled while the audio module's
rename from `AudioScribe` to `ascend-audio-scribe` was completing live in a concurrent session, so any entry below
that touches that module names it as observed at verification time, not as a promise the path is still current by
the time you read this.

### Why this exists

Bugs were being found and fixed across several sessions with nothing written down. The ones somebody acted on lived
only in a chat transcript; the ones nobody acted on existed nowhere at all. This register exists so the second kind
cannot be lost. Every entry below was checked against the running repository (source, tests, docs, CI workflows, and
`.git/logs/HEAD`) rather than accepted on say-so. Where that check could not be completed with the tools available in
this session, the entry says so plainly instead of guessing.

### How to maintain it

Add an entry the moment a defect is found, whether or not it gets fixed in the same sitting. Move it to Fixed with a
commit reference the moment a fix lands, not before. An entry with no commit is not fixed, no matter how confident
the report. When a Found and not fixed entry is closed, move it to Fixed rather than deleting it, since the register
proves the fix landed, not just that a bug once existed.

Prune Fixed entries older than roughly two release cycles once the corresponding code has survived without
regression, unless the entry documents a pattern worth remembering (the several path-anchored-to-old-name defects
below are a pattern, not one bug, and are worth keeping longer). Never prune Found and not fixed or Declined entries;
those are exactly the ones a stale document would let disappear.

### Reading paths

Operator about to rename a module or cut a release: read Actionable now and Actionable, dormant in full before you
start.
Anyone reviewing the OCR service: read the OCR request-budget block under Fixed, including its deployment caveat,
before assuming the fix is live in production.
Owner triaging what to do next: read Actionable now top to bottom, then Declined, then skim Fixed for commit
references if you need to confirm one.

### Verification notes: entries that turned out to be wrong

Two entries reported as "found and not fixed" are not currently reproducible. Both are recorded below under
Actionable now with their corrected status rather than silently dropped, per the instruction that a wrong entry gets
recorded as wrong, not deleted.

The claim that `.gitignore` has ignore rules anchored to old directory names, including the one keeping scraped page
content out of the repository, does not hold against the current file. Every module-scoped rule in
[.gitignore](../.gitignore) already uses the current directory names, including `apps/ascend-web-hunter/src/storage/`,
`apps/ascend-web-hunter/.crawlee_storage/`, and, as of this session, `apps/ascend-audio-scribe/e2e/testing/runs/*`. The most
likely explanation is that the concurrent rename session updated it during this verification; either way, there is
nothing to fix in it right now.

The claim that ascend-ocr's end-to-end README claims six specifications where twelve exist does not hold either.
[apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md) and [apps/ascend-ocr/README.md](../apps/ascend-ocr/README.md) both say
twelve, correctly, and so does [.github/workflows/e2e.yaml](../.github/workflows/e2e.yaml) ("ascend-ocr (12 of
12 free specs)"). No file anywhere under `apps/ascend-ocr/` was found claiming six.

One entry in Fixed could not be pinned to a specific recent change and is flagged there rather than here: the
"compatibility patch dead against its own pinned dependency" most plausibly maps to AscendMemory's
[ADR-006](../apps/ascend-memory/docs/architecture/decisions/ADR-006-mem0ai-2x-upgrade.md), but that ADR is dated
2026-06-01, roughly three months before the window this register otherwise covers, and describes a patch retired by
a deliberate major-version upgrade rather than one found silently dead. See its entry below for the full caveat.

---

## Actionable now

Ordered by whether the defect is already biting or only waiting for a trigger. This block first.

### Currently active

| # | Defect | Where | Effect | Trigger |
| :- | :--- | :--- | :--- | :--- |
| A1 | Bruno request bodies for four ascend-ocr specs hardcode an absolute Windows path | [docs/api/request/AscendAI/ocr/ocr.yml:18](../docs/api/request/AscendAI/ocr/ocr.yml), `testing/ocr-default-lang.yml:18`, `testing/ocr-unsupported-mime.yml:18`, `testing/ocr-polish.yml:18`, all `D:\Development\projekty-IT\AscendAI\ascend-ocr\e2e\fixtures\...` | These four specs (English OCR, default-language OCR, unsupported-MIME rejection, Polish OCR) cannot resolve the fixture file on any machine but this one, including the `ubuntu-latest` runner [.github/workflows/e2e.yaml](../.github/workflows/e2e.yaml) already dispatches them against nightly | Already active. The nightly and on-push e2e workflow runs these specs against a hosted runner today and they fail there |
| A2 | `.gitattributes` anchors `/gradlew text eol=lf` to the repository root | [.gitattributes:1](../.gitattributes) | Matches nothing. The only `gradlew` files in the repo are `apps/ascend-ai-agent/gradlew` and `apps/ascend-weather-mcp/gradlew`; a leading `/` in a root `.gitattributes` anchors to the directory containing that file, not to any nested one | Already active, unrelated to any module move. Nobody's `gradlew` gets its line-ending rule enforced |
| A3 | docling-serve peaked at 7755 MiB against its own 8 GiB compose limit | [compose.yaml:23](../compose.yaml), measured in [docs/architecture/memory-budget.md](architecture/memory-budget.md) "Limits that look wrong, and the evidence" | 95 percent of its own ceiling before any interaction with ascend-ocr is even counted. Of every capped service in the stack, this is the one most likely to be killed by its own limit rather than by the host | Already active; watch it, raise the limit or lower `pdf-parallel-pages` concurrency, see the same section for the trade |
| A4 | Qdrant has no memory limit anywhere in this repository | [docs/architecture/memory-budget.md](architecture/memory-budget.md) "Per-service inventory: external prerequisites" | Its own peak went from 222 MiB to 1954 MiB, nearly ninefold, in one day on this host, and per ADR-M003 it is a deliberately unmanaged external prerequisite so nothing in this repo bounds it | Already active and already growing; the growth mechanism (collection size at RAM-mode creation) is understood, the ceiling is not |
| A5 | `.claude/settings.local.json` allowlists a container name and a module path that no longer exist | `.claude/settings.local.json:93,107` (gitignored, not tracked; see [.gitignore:49](../.gitignore)) | Line 93 is `docker cp AscendWebSearch/e2e/harness/* ascend-web-search:/tmp/*`, line 107 execs into container `ascend-web-search`. Both the module path and the container name predate the rename to `ascend-web-hunter` | Already active. Harmless on its own (a stale allow-list entry just never matches), but confusing to anyone reading the file to understand what an agent is permitted to touch |
| A6 | `apps/ascend-memory/skills/ascend-memory/SKILL.md` and `.agents/skills/ascend-memory/SKILL.md` have drifted apart | [apps/ascend-memory/skills/ascend-memory/SKILL.md](../apps/ascend-memory/skills/ascend-memory/SKILL.md) vs [.agents/skills/ascend-memory/SKILL.md](../.agents/skills/ascend-memory/SKILL.md) | Same content, different formatting conventions: one uses `##` headings with no section dividers and a plain prose style, the other uses `###` headings with `---` dividers per the `markdown-writer` skill's own rules. Nothing keeps the two synchronised | Already active. Whichever copy an agent happens to load first is the one whose conventions it will imitate next |

### Currently dormant

| # | Defect | Where | Effect | What would make it bite |
| :- | :--- | :--- | :--- | :--- |
| A7 | `.pre-commit-config.yaml` scoped every hook to `^PaddleOCR/` | [.pre-commit-config.yaml:7,9,15](../.pre-commit-config.yaml) | Ruff, ruff-format and mypy currently only ever run against ascend-ocr; no other Python module has a pre-commit lint or type gate at all, which is itself worth knowing, but the specific defect here is narrower | `AscendWebSearch/` and `AudioScribe/` already lived through this trigger this session. PaddleOCR's own rename to `apps/ascend-ocr/` retargets the filter to `^apps/ascend-ocr/` in the same change that moves the directory ([.pre-commit-config.yaml:7,9,15](../.pre-commit-config.yaml)), so this third instance of the pattern never actually bites, pending that change landing as a commit |
| A8 | [.github/workflows/release.yaml](../.github/workflows/release.yaml) reads each app's previous version via `git show <prev-tag>:<manifest-path>`, using today's path | lines ~127-197, `check_and_add` calling `read_prev_java_version` / `read_prev_python_version` | If the manifest path did not exist at the previous `ascend-ai_*` tag, `git show` fails and, under `set -euo pipefail`, aborts the whole `prepare` job for every selected app, not just the renamed one | Dormant today only because no `ascend-ai_*` tag exists yet; the one tag in the repo is `0.1.0-beta` ([.git/packed-refs:8](../.git/packed-refs)), so the bump guard is currently skipped entirely. It fires the first time a stack release is cut, a module is renamed afterward, and a second release is attempted |
| A9 | ascend-weather-mcp and ascend-memory sit at 73 and 58 percent of their own container memory caps | [docs/architecture/memory-budget.md](architecture/memory-budget.md) "Limits that look wrong, and the evidence" (ascend-weather-mcp 512 MiB limit, ascend-memory 512 MiB limit) | Both are JVM or proxy services whose peak is drifting upward on every fresh counter reading, and both would be killed by their own limit long before the host noticed anything | Safe today. Bites the next time either service's peak drifts past its own ceiling under sustained load; they are named as the two most likely next container-limit kills in the stack |

### Unverifiable in this session

| # | Defect | Status |
| :- | :--- | :--- |
| A10 | Sixteen OpenSpec validations failing on placeholder sections, one change missing its deltas | Could not run `openspec validate` from this session (no shell tool available). A text search for placeholder markers (`TBD`, `TODO`, `[PLACEHOLDER]`, `{{...}}`) across `openspec/changes/` found two hits, [openspec/changes/add-web-search-scraping-e2e/test-spec.md](../openspec/changes/add-web-search-scraping-e2e/test-spec.md) and one archived design doc that would not count toward an active-change validation count. That is not enough to confirm or refute "sixteen." Whoever next has shell access should run `openspec validate --all` (or the project's equivalent) and update this row with the real count and the specific change missing its deltas |

---

## Declined

| # | Defect | Status |
| :- | :--- | :--- |
| D1 | Several databases are reachable on every network interface with no password | Declined by the owner for his own machine. Per [ADR-M003](architecture/decisions/ADR-M003-external-infrastructure-prerequisites.md), PostgreSQL, Redis, Qdrant and the object store are deliberately external prerequisites this repository does not configure, so there is no compose file or settings file this register can point at as the source; the bind address and auth posture live entirely in the operator's own local setup, which is exactly why this is an accepted risk rather than a repository defect |

---

## Fixed

Grouped by area. Each row names the current evidence in the running repository; where a specific commit could be
matched from `.git/logs/HEAD`, it is given. Several of these predate the reflog window this session could read
(entries below note that explicitly rather than inventing a SHA).

### ascend-ai-agent and cross-service

| # | Defect | Evidence | Commit |
| :- | :--- | :--- | :--- |
| F1 | Embedding provider configuration key never bound, so requests omitting it failed | [apps/ascend-memory/src/config/config.py:25-116](../apps/ascend-memory/src/config/config.py), `PROVIDER_CONFIGS` plus `MEM0_DEFAULT_PROVIDER` with a bound default (`lmstudio`); a request omitting `provider` now resolves through `provider_config()` correctly | Not identifiable in the available `.git/logs/HEAD` window; current code is unambiguously correct |
| F2 | Testcontainers restarted per test class instead of once per run | [apps/ascend-ai-agent/src/test/java/com/lukk/ascend/ai/agent/integration/TestcontainersBase.java:29-42](../apps/ascend-ai-agent/src/test/java/com/lukk/ascend/ai/agent/integration/TestcontainersBase.java), a static initializer with an explicit Javadoc explaining the original bug (the `@Container` annotation tearing down the first subclass's containers while Spring's context cache kept reusing stale ports) and the fix (a singleton static block, no `@Container`) | Not identifiable in the available window |
| F3 | The document converter's workers died without retry | [apps/ascend-ai-agent/src/main/java/com/lukk/ascend/ai/agent/service/ingestion/client/DoclingClient.java:97-114](../apps/ascend-ai-agent/src/main/java/com/lukk/ascend/ai/agent/service/ingestion/client/DoclingClient.java), `postWithRetry` retries a transient `ResourceAccessException` up to `MAX_ATTEMPTS = 3` with a 500 ms backoff before giving up | Not identifiable in the available window |
| F4 | A client sent its file under the wrong multipart field, so every OCR call returned 422 | ascend-ai-agent's ascend-ocr REST client now sends the field ascend-ocr's own endpoint expects | `fix(agent): send the field the OCR service actually asks for` (`814a1b33f0ec816177009ed4c4e02e83a9edd850`) |
| F5 | The same client sent the language in the body while the service reads it from the query | Same fix as F4, same commit | `814a1b33f0ec816177009ed4c4e02e83a9edd850` |
| F6 | A container metrics exporter was blind on this host while scraping green | [infra/observability/README.md:45](../infra/observability/README.md), the exporter now reads the Docker Engine API stats endpoint directly over the Docker socket rather than a host-filesystem cgroup path that did not resolve on this host | `feat(observability): bound three services by measurement and see it happen` (`264ebcc0a8b84fbfb5a73c990f4cdf7102afa874`) |
| F7 | Around fifty tests silently reached the internet | Not independently confirmed. No `pytest-socket`, `disable_socket`, or equivalent network-blocking fixture was found in any module's `pyproject.toml` or `conftest.py` in this session. Recorded as reported-fixed; whoever can diff the actual test suite against its prior state should confirm what mechanism, if any, now blocks outbound calls |
| F8 | An unnecessary type suppression failed the type check | Partial match only. `warn_unused_ignores = true` is set in four Python modules' `pyproject.toml` (`ascend-audio-scribe`, `ascend-web-hunter`, `ascend-ocr`, `AscendMemory`), which is the mechanism that would surface this class of defect, but that setting predates this session. The closest concrete instance found is [openspec/changes/stop-ocr-getting-stuck-on-large-jobs/tasks.md:292-297](../openspec/changes/stop-ocr-getting-stuck-on-large-jobs/tasks.md), which removed two unused ruff `noqa: N802` directives, a ruff suppression rather than a mypy `type: ignore`. Recorded with that caveat rather than a confident match | `5bb86191855cb1173ff8c3b4031958acc7c0af0b` (ruff cleanup only; mypy instance not located) |
| F9 | A coverage gate was declared but never enforced in two modules, leaving one at 98.98 percent | [.github/workflows/ci.yaml:142-155](../.github/workflows/ci.yaml), the comment names both: `ascend-web-hunter` and `ascend-memory` declare `fail_under = 100` in `[tool.coverage.report]` but do not bake it into pytest addopts, so a bare `pytest` used to pass without enforcing it; CI now runs `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` explicitly for both | `test: run the coverage gate two modules declared but never enforced` (`d92c2b6e59b19e5a7c379a985c2a9ee0adcd2600` to `e3472d9f0e1bf1c675ee2bb79eef6dab02bd8885`) |
| F10 | Three continuous integration references pointed at request files that had moved | [.github/workflows/e2e.yaml](../.github/workflows/e2e.yaml) now consistently uses `web-hunter/testing/...`, `ocr/...`, `memory/testing/...` and `weather-mcp/...` under [docs/api/request/AscendAI/](../docs/api/request/AscendAI/), matching the current Bruno collection layout | `refactor: rename the web service to ascend-web-hunter, everywhere` (`d89fb420e727a144ecdf6aa83a814c12c25982b1`) and `docs(api): give every endpoint a request, in one place per module` (`d4d0de3039a41852d491c7c1e1c7460d63c1b991`) |
| F11 | Documentation across two modules described thread-pool execution years after it moved to a separate process | Not confirmed. A search for stale `ThreadPoolExecutor` language in ascend-ocr and `ascend-web-hunter` docs found only current, accurate references (ascend-ocr's own arc42 constraints page correctly describes its `ProcessPoolExecutor`). Could not identify the two modules this entry refers to; recorded as unconfirmed rather than mapped to evidence that does not fit |
| F12 | A compatibility patch was dead against its own pinned dependency | Weak match. The closest candidate is AscendMemory's [ADR-006](../apps/ascend-memory/docs/architecture/decisions/ADR-006-mem0ai-2x-upgrade.md), which removes an `OpenAILLM.generate_response` monkey-patch, but it is dated 2026-06-01 (roughly three months before this register's window) and describes the patch being retired by a deliberate mem0ai 1.0.3 to 2.0.4 upgrade, not found silently dead while still pinned. See the verification notes above; this entry may be misattributed | `ADR-006`, dated 2026-06-01; no matching recent commit found |
| F13 | Stale specification counts in the cost document | [docs/E2E_COST.md](../docs/E2E_COST.md) now states "as they stood on 2026-09-04" and reconciles every per-module spec count against the current suite | `docs(cost): price the remaining gaps and correct the sweep totals` (`4cd292a0a97a3ab09b3d82368105727a36fe68b0`) |
| F14 | An observability document claimed six containers and listed five | [infra/observability/README.md:91-93](../infra/observability/README.md) now states the reconciliation directly: five of the six application containers get a `service` log label, `ascend-weather-mcp` is deliberately console-silent per its own `application.yml`, and the doc says so instead of leaving the discrepancy unexplained | Not identifiable to a single commit in the available window; consistent with `264ebcc0a8b84fbfb5a73c990f4cdf7102afa874` |

### ascend-web-hunter

| # | Defect | Evidence | Commit |
| :- | :--- | :--- | :--- |
| F15 | Two block pages were scored as successful scrapes, on Amazon and on Allegro | Scraper now classifies real block pages rather than returning HTTP 200 as success | `fix(web-search): make the scraper detect real block pages and stop hanging` (`0947f99ebf6cd9662460ad45069c2b243de26235`) |
| F16 | A crawler ran past its own deadline because it swallowed cancellation | Same fix, same commit ("stop hanging" half) | `0947f99ebf6cd9662460ad45069c2b243de26235` |
| F17 | A blocklist was committed into the package instead of cached | [apps/ascend-web-hunter/AGENTS.md](../apps/ascend-web-hunter/AGENTS.md), `BLOCKLIST_PATH` is now a vendored, refreshable file (default `src/assets/fanboy-annoyance.txt`) overwritten in place by `POST /api/v1/blocklist/refresh`, rather than a fetch baked into the package with no update path | `fix(web-search): stop a third-party website being able to stop the service` (`2333ba1acf9a5f059a3a4263d0002c003100162e`) |
| F18 | A blocklist was downloaded on every startup with no cache, so a third-party outage stopped the service starting | Same AGENTS.md line: `BLOCKLIST_URL` is "only reached by `POST /api/v1/blocklist/refresh`; never fetched at startup" | `2333ba1acf9a5f059a3a4263d0002c003100162e` |
| F19 | A dependency pin crashed the crawler when bumped | Not independently confirmed. No pin comment naming a crash was found in `apps/ascend-web-hunter/pyproject.toml`; recorded as reported-fixed without direct evidence in this session |  |
| F20 | A session profile argument was accepted and silently discarded | `profile` is threaded through [apps/ascend-web-hunter/src/session/session_manager.py](../apps/ascend-web-hunter/src/session/session_manager.py) and every reader strategy that consults it; current code does not discard it | Not identifiable in the available window |
| F21 | A session was reported active for days after its cookie expired | Session liveness now checks the actual cookie state rather than trusting a cached flag | `fix(web-search): stop reporting dead sessions as live, and lock the browser` (`02bacdbd3743cf1f1d36d12ad7ff02848de2edf3`) |
| F22 | Two browser intervention flows collided and silently lost the captured session | Same commit, the "lock the browser" half | `02bacdbd3743cf1f1d36d12ad7ff02848de2edf3` |

### ascend-ocr

All seven of the rows below (F23-F29) share one deployment caveat, stated once here rather than seven times: the
fixes are complete in source and covered by tests (`openspec/changes/stop-ocr-getting-stuck-on-large-jobs/tasks.md`,
every section but 1.2, 1.3, 1.4, 1.6, and 8.7 checked off), but as of task 8.8's own live-verification note the
running `ascend-ocr` container was still built from pre-fix code, and the change has not been archived into
`openspec/specs/`. Read Fixed here as fixed in source, not yet confirmed rebuilt and deployed.

| # | Defect | Evidence | Commit |
| :- | :--- | :--- | :--- |
| F23 | An OCR request timeout abandoned work while the worker ran for thirty more minutes | [apps/ascend-ocr/src/service/ocr_service.py](../apps/ascend-ocr/src/service/ocr_service.py), the worker now consumes `predict_iter()` page by page and checks its own cooperative deadline between pages instead of being cancelled out from under a still-running `ProcessPoolExecutor` job. Deployment caveat above applies | `fix(paddle-ocr): stop abandoning work and let one page cost four gigabytes less` (`5bb86191855cb1173ff8c3b4031958acc7c0af0b`) |
| F24 | An OCR call cost roughly ten gigabytes regardless of input | `OCR_DETECTOR_MAX_SIDE` now defaults to `1536` in [apps/ascend-ocr/src/config/config.py](../apps/ascend-ocr/src/config/config.py), measured at 8.80 GiB peak for one A4 page (task 8.9), down from the unbounded 11.0 GiB baseline. Deployment caveat above applies | `5bb86191855cb1173ff8c3b4031958acc7c0af0b` |
| F25 | An OCR image path had no pixel limit at all | [apps/ascend-ocr/src/api/limits.py](../apps/ascend-ocr/src/api/limits.py), header-only pixel inspection enforced at both REST and MCP boundaries before any decode, `OCR_MAX_INFERENCE_PIXELS` defaulting to 2,500,000. Deployment caveat above applies | `5bb86191855cb1173ff8c3b4031958acc7c0af0b` |
| F26 | OCR readiness reported healthy for five hours with no worker process | [apps/ascend-ocr/src/observability/metrics.py:81-103](../apps/ascend-ocr/src/observability/metrics.py), `is_engine_warm()` reads the same cross-process metric the worker itself writes, and `/ready` composes `is_pool_usable()`, `is_rebuild_in_progress()`, and `is_job_overrunning()`. Deployment caveat above applies | `5bb86191855cb1173ff8c3b4031958acc7c0af0b` |
| F27 | Two OCR language codes were advertised but always failed | [apps/ascend-ocr/src/config/config.py:64-66](../apps/ascend-ocr/src/config/config.py), `SUPPORTED_LANGUAGES` now uses PaddleOCR's own internal codes (`ch`, `japan`, `korean`) rather than ISO codes the underlying library does not recognise | `fix(paddle-ocr): serve the two languages it advertised but could not read` (`d92c2b6e59b19e5a7c379a985c2a9ee0adcd2600`) |
| F28 | An OCR cache eviction log and metric were invisible because they lived in the wrong process | [apps/ascend-ocr/src/observability/metrics.py:1-2,86-90](../apps/ascend-ocr/src/observability/metrics.py), `ENGINE_CACHE_EVICTIONS_TOTAL` is now read back through `prometheus_client.multiprocess.MultiProcessCollector` against `PROMETHEUS_MULTIPROC_DIR`, the same cross-process mechanism `is_engine_warm()` uses, so a counter incremented inside the `ProcessPoolExecutor` worker (`ocr_service.py:183-187`) reaches `/metrics` in the parent | Not identifiable to a single commit; consistent with `5bb86191855cb1173ff8c3b4031958acc7c0af0b` |
| F29 | An OCR warm-up built an engine nothing used, while readiness reported on it | Same `is_engine_warm()` mechanism as F28: readiness now reads the real worker's own warm-up metric rather than a separate engine instantiated only to answer the readiness check | Consistent with `5bb86191855cb1173ff8c3b4031958acc7c0af0b` |
| F30 | The OCR service starved its own event loop through the interpreter lock | [apps/ascend-ocr/src/service/ocr_service.py](../apps/ascend-ocr/src/service/ocr_service.py), inference already runs inside a `ProcessPoolExecutor`, isolated from the API process's event loop. This is confirmed as currently true, but the architecture appears to predate this session's work (the large OCR change treats the process pool as pre-existing infrastructure it builds on, not something it introduces), so this may not be a "past several days" fix at all | Not identifiable; likely predates the available reflog window entirely |

### Not independently verifiable

| # | Defect | Status |
| :- | :--- | :--- |
| F31 | The audio service double-encoded its tool responses | Not re-verified against current source. `AudioScribe`'s rename to `ascend-audio-scribe` completed live during this verification session, and that module is explicitly out of scope to touch per this task's boundaries. Carried forward as fixed from the prior report; nobody has re-confirmed it against the module's current code in this pass |

---

## What changed underneath this register while it was being written

`AudioScribe` became `ascend-audio-scribe` mid-session, the same rename `AscendWebSearch` went through earlier.
`.gitignore` was already updated to match by the time this register was finished (see the verification note above).
`.github/workflows/ci.yaml` and `.github/workflows/release.yaml` were read before that rename completed and, at
read time, still referenced the `AudioScribe` path (`"path":"AudioScribe"` in the CI matrix, `AudioScribe/pyproject.toml`
in the release manifest reader). Whether that has since been corrected by the same concurrent session was not
re-checked, since re-reading those files was outside this task's scope once the rename was observed in progress.
Whoever owns that rename should confirm `ci.yaml` and `release.yaml` both resolve against `apps/ascend-audio-scribe/`
before the next push or release dispatch, since a stale path there means the audio service silently stops being
built and tested, not merely mislinted.
