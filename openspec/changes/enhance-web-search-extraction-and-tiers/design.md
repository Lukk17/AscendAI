# Design — enhance-web-search-extraction-and-tiers

## Context

ascend-web-hunter escalates reads through curl_cffi → FlareSolverr → Playwright → Crawlee with NoVNC for human intervention. `enhance-web-search-scraping` already added session replay into every tier, coherent fingerprints (`src/reader/fingerprint.py`), an optional proxy seam (`src/proxy/proxy_provider.py`), read caching, per-domain metrics, and circuit breakers. FlareSolverr's only job is solving the Cloudflare challenge and returning cookies; a patched stealth browser both solves the challenge and renders the page, so the middle tiers can collapse. Patchright is a drop-in Playwright replacement (patched Chromium); Camoufox is a hardened Firefox driven through Playwright — both free and self-hosted.

Extraction returns trafilatura output with a readability fallback: a single main-content blob, no embedded structured data, no schema-guided output, and linked PDFs/images are ignored even though the platform runs Docling, ascend-ocr, and ascend-audio-scribe.

## Goals / Non-Goals

**Goals:**

- Retire FlareSolverr; ladder curl_cffi → Patchright → Camoufox → NoVNC with per-domain memory and a local CAPTCHA rung.
- Extraction that beats a single-extractor blob: embedded structure, scored ensemble, schema-guided JSON, self-healing recipes, non-HTML routing, richer output formats.
- Keep every capability free and self-hostable; the schema-extraction LLM endpoint is configurable and can be fully local.

**Non-Goals:**

- Crawling at scale, the frontier, incremental recrawl, and the RAG connector (owned by the sibling `enhance-web-search-crawl-at-scale`).
- Paid CAPTCHA-solving APIs and paid proxy networks (explicitly excluded).
- Redoing session replay, fingerprints, caching, or metrics (`enhance-web-search-scraping` owns them).

## Decisions

### D1 — Collapse FlareSolverr + Playwright into a patched-browser tier, add Camoufox as auto-escalation

Patchright replaces the Playwright tier as a drop-in (same API, patched Chromium), so the existing Playwright flow, including the session `storage_state` replay from `enhance-web-search-scraping`, carries over unchanged. Camoufox becomes the next rung, tried automatically when Patchright is detected/blocked or fails. FlareSolverr is removed; its cookie-persistence behaviour is already superseded by the session replay the earlier change installed on the browser tiers.

### D2 — Per-domain tier memory in Redis, with decay

Keyed by registrable domain, store the cheapest tier that last succeeded and start there. Decay the stored tier back toward curl_cffi on a time schedule so a transient block does not pin a domain to Camoufox forever. This reuses the Redis the service already has (sessions, `enhance-web-search-scraping`).

### D3 — Structured data before heuristics; scored ensemble for the main body

Parse JSON-LD, OpenGraph, and microdata first and return them as structured fields — deterministic and free. For the main body, run trafilatura and readability over the same DOM and score both on text-vs-link density and boilerplate ratio, keeping the winner, rather than trafilatura-primary-with-fallback which loses on pages where readability is better.

### D4 — Schema-guided extraction with self-healing recipes

A schema mode: the caller supplies a JSON schema; the service returns validated JSON. The first extraction for a domain asks the LLM to emit CSS/XPath selectors alongside the values, and the selectors are persisted as a recipe. Later extractions replay the cheap selectors and skip the model; on drift (empty or type-mismatched fields against the schema) the recipe is regenerated. The LLM call targets a configurable OpenAI-compatible endpoint, so it can be a local model, AscendAgent's provider proxy (tenant-policy-aware, keeps data on-prem), or a cloud provider — the service stays decoupled and sovereign by default.

### D5 — Route non-HTML into the existing platform services

Linked PDFs → Docling, image-heavy pages / linked images → ascend-ocr, linked audio → ascend-audio-scribe, over HTTP to the services the compose stack already runs. This is configuration (service URLs), not new parsing code, and gives the scraper document-understanding depth no standalone competitor ships.

## Risks / Trade-offs

- [Camoufox is heavier than Patchright] → it is the escalation rung, not the default; most domains resolve at curl_cffi or Patchright per the tier memory.
- [Self-healing recipe returns stale/wrong data silently] → every replay validates against the caller's schema; drift triggers regeneration, so a broken recipe self-repairs rather than serving garbage.
- [Schema extraction cost/latency] → recipes make the common path model-free; the model runs on first-seen domains and on drift only.
- [Local CAPTCHA solver accuracy is limited] → it is a cheap first attempt for common types; anything it cannot solve escalates to the existing NoVNC human tier, unchanged.

## Open Questions

- None blocking. The exact local CAPTCHA-solver library is an implementation choice validated during task 1; the ladder and interfaces do not depend on which one.
