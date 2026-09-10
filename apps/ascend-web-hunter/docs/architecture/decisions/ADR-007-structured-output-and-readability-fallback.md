# ADR-007: Structured article output and readability-lxml fallback

## Status

Accepted — 2026-06-15

## Context

The `WebReader` extraction chain currently returns a flat text string from every strategy. Three quality gaps
were identified:

1. **No article metadata.** Title, author, publication date, and site name are available from trafilatura when
   called in JSON mode but are discarded. Callers (ascend-ai-agent RAG pipeline) benefit from structured metadata
   for citation and display.

2. **Thin trafilatura extractions.** On pages with heavy boilerplate, navigation, or JavaScript-rendered text,
   trafilatura may return little or no content even though the page has substantial main content. There is no
   fallback.

3. **`SCROLL_*` settings ignored.** `SCROLL_ITERATIONS` and `SCROLL_STEP_PX` were defined in `Settings` since
   the service was first built but never wired into the Playwright tier. Pages that load content on scroll
   (infinite scroll, lazy-load) therefore only received content visible above the fold.

## Decision

### D1 — Structured output is opt-in via `output_format=structured`

When `read()` or `read_with_links()` is called with `output_format="structured"`, `WebReader._execute_strategy`
calls `strategy.get_html(url)` then `extract_structured(html)` from `src/reader/extraction.py`, and includes
the `title`, `author`, `date`, `sitename`, and `source` fields alongside `content` in the response.

When `output_format` is absent or `"text"`, the response shape is byte-for-byte identical to the pre-change
flat `{"content": ..., "status": ..., "mode": ...}` dict. No existing caller is affected.

`output_format` is included in the cache key so the two formats can coexist in the cache for the same URL.

### D2 — readability-lxml fallback scored by content length

`src/reader/extraction.py` exposes two public functions:

- `extract_structured(html) -> dict[str, Any]` — used for `output_format=structured`.
- `extract_text_with_fallback(html) -> str` — used for `output_format=text` (and the default).

Both functions follow the same policy: run trafilatura first; if the output is shorter than
`READABILITY_FALLBACK_MIN_CHARS` (default 200 characters), run `readability-lxml` and return whichever result
is longer by character count of the main content field. The `source` field in structured output records which
extractor provided the winning result.

`readability-lxml` is added as a direct project dependency (`pyproject.toml`).

### D3 — Scroll loop wired in `PlaywrightStrategy._scroll_page`

After the dynamic content wait (`DYNAMIC_CONTENT_WAIT` ms), `PlaywrightStrategy` now calls
`page.evaluate(f"window.scrollBy(0, {settings.SCROLL_STEP_PX})")` in a loop of `settings.SCROLL_ITERATIONS`
iterations with a 200 ms pause between steps. This is bounded: if the per-strategy budget (`EXTRACT_TIMEOUT`)
expires, Playwright's own timeout mechanism terminates the page session rather than the scroll loop.

## Alternatives Considered

### Alternative 1: Always return structured output; break flat callers
- **Pros**: Simpler code — no `output_format` branching.
- **Cons**: All existing REST and MCP callers expect the flat shape. A breaking API change would require
  updating ascend-ai-agent and any integration tests at the same time as this slice.
- **Why not**: The spec explicitly requires backward compatibility. Additive opt-in has zero migration cost.

### Alternative 2: Use trafilatura's `bare_extraction` instead of `output_format="json"`
- **Pros**: Returns a `Extractor` result object without JSON serialisation round-trip.
- **Cons**: `bare_extraction` returns an object whose public API is less stable across trafilatura versions than
  the JSON format (which is a documented contract).
- **Why not**: JSON mode is the documented stable interface.

### Alternative 3: Use Newspaper3k instead of readability-lxml
- **Pros**: Richer metadata extraction (author, keywords).
- **Cons**: `newspaper3k` is not actively maintained as of 2026; `newspaper4k` exists but is a fork with an
  unstable API. `readability-lxml` is more focused (boilerplate removal only) and is actively maintained.
- **Why not**: Trafilatura already provides metadata when it succeeds. `readability-lxml` is needed only for the
  boilerplate-removal fallback, where author/keyword extraction is secondary.

## Consequences

### Positive
- ascend-ai-agent RAG and display layers gain access to article metadata without a separate extraction pass.
- Pages with heavy boilerplate that produce thin trafilatura output now have a fallback extractor.
- Scroll handling lands on existing `SCROLL_*` settings without new config surface.

### Negative
- The readability-lxml fallback runs even when trafilatura returns empty content on pages that genuinely have no
  extractable text (e.g. login walls), adding latency. This is mitigated by the 200-char threshold: an empty
  trafilatura result (0 chars < 200) always triggers the fallback.
- `readability-lxml` may include navigation fragments that trafilatura's article model correctly excludes. The
  length-scoring heuristic can therefore promote noisier content.

### Risks
- **readability-lxml returns HTML, not plain text.** `Document.summary()` returns HTML. The structured response
  `content` field for readability results therefore contains HTML tags. Callers consuming `output_format=structured`
  should strip tags if plain text is required. This is a known limitation noted in the `readability-lxml` docs.

## Related

- `src/reader/extraction.py` — `extract_structured`, `extract_text_with_fallback`.
- `src/reader/strategies/trafilatura_strategy.py` — uses `extract_text_with_fallback`.
- `src/reader/web_reader.py` — `_execute_strategy` branches on `output_format`.
- `src/reader/strategies/playwright_strategy.py` — `_scroll_page` wires `SCROLL_ITERATIONS` / `SCROLL_STEP_PX`.
- `src/config/config.py` — `READABILITY_FALLBACK_MIN_CHARS`, `SCROLL_ITERATIONS`, `SCROLL_STEP_PX`.
- `pyproject.toml` — `readability-lxml>=0.8.1` dependency added.
