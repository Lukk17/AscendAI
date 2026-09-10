## Why

`enhance-web-search-scraping` (already implemented) gave ascend-web-hunter coherent browser fingerprints, session replay across tiers, trafilatura structured output with a readability-lxml fallback, an optional proxy seam, read caching, per-domain metrics, and circuit breakers. That closed the "can it log in and render" gap. It did not make extraction best-in-class, and it left the tier ladder on FlareSolverr — a barely-maintained Cloudflare-bypass proxy whose detection rate keeps climbing and which is the weakest rung.

To compete with Firecrawl and Zyte on the two things buyers actually evaluate — extraction quality and unblocking reliability — two gaps remain. Extraction still returns one main-content blob: no embedded structured data (JSON-LD / OpenGraph / microdata), no scored choice between extractors, no schema-guided structured output, and no reuse of the platform's own document-understanding stack for linked PDFs and images. And the browser ladder is a single vanilla-Playwright tier behind FlareSolverr, with no memory of what worked per domain.

This change is scoped strictly to that delta. It does not redo anything `enhance-web-search-scraping` already ships.

## What Changes

- **Tier ladder restructure (retire FlareSolverr):** the ladder becomes curl_cffi → Patchright (patched Chromium, a drop-in replacement for the current Playwright tier) → Camoufox (hardened Firefox, tried automatically when Patchright is detected or fails) → NoVNC human. FlareSolverr is removed; the patched browsers subsume its Cloudflare-challenge job and render the page in one step. Both Patchright and Camoufox are free and self-hosted; no external paid dependency.
- **Per-domain tier memory with decay:** record the cheapest tier that last succeeded per registrable domain in Redis and start there next time, decaying back toward curl_cffi over time so a one-off block does not pin a domain to an expensive tier forever.
- **Local CAPTCHA solver rung:** a free, self-hosted open-source solver for the common CAPTCHA types is tried before escalating to the existing NoVNC human tier. No paid CAPTCHA-solving API is used (sovereignty: nothing leaves the deployment to a solving farm).
- **Embedded structured data first:** parse JSON-LD, OpenGraph, and microdata before any heuristic or model runs, and return it alongside the text — free, deterministic structure present on most commercial pages.
- **Scored ensemble extraction:** run trafilatura and the readability extractor over the same DOM, score both (text vs link density, boilerplate ratio) and keep the winner, instead of trafilatura-primary-with-fallback.
- **Schema-guided extraction endpoint:** a read mode where the caller supplies a JSON schema and gets back validated JSON, produced by an LLM call to a configurable OpenAI-compatible endpoint (which can be a local model, ascend-ai-agent's provider proxy, or a cloud provider) so the extraction can run fully on-premises.
- **Self-healing domain recipes:** on the first schema extraction for a domain, persist the LLM-emitted CSS/XPath selectors as a recipe; subsequent extractions replay the cheap selectors and skip the model, regenerating the recipe on drift (empty or type-mismatched fields).
- **Route non-HTML into the platform stack:** linked PDFs go to Docling, image-heavy pages/linked images to ascend-ocr, linked audio to ascend-audio-scribe — reusing services the platform already runs, which no standalone scraper ships with.
- **Multi-format output:** add full-page screenshot and extracted-tables-as-rows to the existing output formats, selectable per request.

## Capabilities

### New Capabilities

- `web-search-tier-ladder`: the restructured curl_cffi → Patchright → Camoufox → NoVNC ladder with FlareSolverr retired, per-domain tier memory with decay, and a local open-source CAPTCHA rung before human escalation.
- `web-search-structured-extraction`: embedded structured-data parsing (JSON-LD / OpenGraph / microdata), scored ensemble main-content extraction, schema-guided LLM extraction returning validated JSON via a configurable endpoint, self-healing per-domain selector recipes, routing of linked PDFs/images/audio into Docling/apps/ascend-ocr/ascend-audio-scribe, and screenshot + table output formats.

### Modified Capabilities

(none as spec deltas — `enhance-web-search-scraping`'s capabilities are not archived to `openspec/specs/`, so they cannot be modified here. This change is additive and names distinct new capabilities; where it supersedes a rung — FlareSolverr — the tasks call out the removal and the migration of session/cookie replay onto the patched-browser tiers.)

## Impact

- **Depends on**: `enhance-web-search-scraping` (fingerprints, session replay, proxy seam, caching, per-domain metrics it builds on) — ideally archived first. The schema-extraction endpoint optionally integrates with ascend-ai-agent's provider router for tenant-policy-aware, local-capable extraction, but works standalone against any OpenAI-compatible endpoint.
- **ascend-web-hunter (code)**: `pyproject.toml` adds `patchright` and `camoufox` (and a local CAPTCHA-solver library); `src/reader/strategies/` gains `patchright_strategy.py` and `camoufox_strategy.py`, removes `flaresolverr_strategy.py`; `src/reader/web_reader.py` orchestrator ladder and per-domain tier memory (Redis); `src/reader/` gains structured-data parsing, ensemble scoring, schema extraction + recipe store, and non-HTML routing clients (Docling/apps/ascend-ocr/ascend-audio-scribe); `src/api/rest` + `src/api/mcp` gain the schema-extraction mode and new output formats; `src/config/config.py` new settings.
- **Config**: extraction LLM endpoint + model, recipe store TTL, tier-memory decay, CAPTCHA-solver toggle, non-HTML routing service URLs.
- **Docs**: `apps/ascend-web-hunter/AGENTS.md` tier ladder and extraction modes; ADRs for the tier restructure and the self-healing recipe model.
- **Tests**: ladder escalation Patchright→Camoufox; tier-memory start point and decay; JSON-LD/OG/microdata extraction; ensemble scoring picks the better extractor on a messy page; schema extraction returns schema-valid JSON; recipe replay then regenerate-on-drift; linked-PDF routed to Docling; screenshot and table outputs.

## Relevant Skills

- `/python-patterns`
- `/python-testing`
- `/api-design`
- `/docker-patterns`
- `/security-review`
