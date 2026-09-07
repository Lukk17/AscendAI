# Tasks — enhance-web-search-extraction-and-tiers

## 1. Tier ladder restructure

- [ ] 1.1 Add `patchright` and `camoufox` to `pyproject.toml`; select and add a free local CAPTCHA-solver library; update the lock/build
- [ ] 1.2 Create `src/reader/strategies/patchright_strategy.py` as the default browser tier (drop-in for the current Playwright tier), carrying over session `storage_state` replay from `enhance-web-search-scraping`
- [ ] 1.3 Create `src/reader/strategies/camoufox_strategy.py` as the auto-escalation tier tried when Patchright is detected/blocked or fails
- [ ] 1.4 Remove `src/reader/strategies/flaresolverr_strategy.py` and its config/orchestrator wiring; confirm cookie/session persistence is fully covered by the browser-tier replay
- [ ] 1.5 Update `src/reader/web_reader.py` ladder to curl_cffi → Patchright → Camoufox → (local CAPTCHA) → NoVNC
- [ ] 1.6 Tests: a page that blocks Patchright escalates to Camoufox and succeeds; FlareSolverr no longer referenced anywhere

## 2. Per-domain tier memory and local CAPTCHA rung

- [ ] 2.1 Store the cheapest successful tier per registrable domain in Redis; start subsequent reads there
- [ ] 2.2 Decay the stored tier back toward curl_cffi on a time schedule (configurable)
- [ ] 2.3 Add the local CAPTCHA-solver attempt before NoVNC escalation; no paid solver API
- [ ] 2.4 Tests: tier memory sets the start tier; decay returns a domain toward curl_cffi after the window; unsolved CAPTCHA escalates to NoVNC

## 3. Embedded structured data and scored ensemble

- [ ] 3.1 Parse JSON-LD, OpenGraph, and microdata and return them as structured fields alongside the text
- [ ] 3.2 Run trafilatura and readability over the same DOM, score both (text-vs-link density, boilerplate ratio), keep the winner
- [ ] 3.3 Tests: JSON-LD/OG/microdata extracted from a fixture page; ensemble picks readability on a page where it scores higher and trafilatura otherwise

## 4. Schema-guided extraction and self-healing recipes

- [ ] 4.1 Add a schema-extraction read mode (REST + MCP): caller supplies a JSON schema, service returns schema-valid JSON via a configurable OpenAI-compatible endpoint (`EXTRACTION_LLM_BASE_URL` / model — local, AscendAgent proxy, or cloud)
- [ ] 4.2 On first extraction per domain, persist LLM-emitted CSS/XPath selectors as a recipe (store with TTL); replay selectors on subsequent extractions and skip the model
- [ ] 4.3 Validate every replay against the caller's schema; on drift (empty/type-mismatched fields) regenerate the recipe
- [ ] 4.4 Tests: schema extraction returns schema-valid JSON; second call for the same domain is model-free (recipe replay); induced drift regenerates the recipe

## 5. Non-HTML routing and output formats

- [ ] 5.1 Route linked PDFs to Docling, image-heavy pages / linked images to PaddleOCR, linked audio to AudioScribe (service URLs from config); merge extracted text into the result
- [ ] 5.2 Add full-page screenshot and extracted-tables-as-rows to the selectable output formats
- [ ] 5.3 Tests: a page linking a PDF yields Docling-extracted text; a table page yields structured rows; screenshot output returns image bytes

## 6. Documentation

- [ ] 6.1 Update `ascend-web-hunter/AGENTS.md`: new tier ladder, extraction modes, output formats, config variables
- [ ] 6.2 ADRs for the tier restructure (FlareSolverr retirement) and the self-healing recipe model
- [ ] 6.3 Run `pytest` for ascend-web-hunter; all green
