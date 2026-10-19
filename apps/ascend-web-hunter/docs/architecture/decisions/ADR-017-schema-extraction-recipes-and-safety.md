# ADR-017: Schema-guided extraction, selector recipes and model-input safety

## Status

Accepted, 2026-10-19

## Context

`output_format` `structured` returns the article fields the extractors find, plus the embedded JSON-LD,
OpenGraph and microdata in `metadata`. A caller that needs named fields (a product name and price) cannot
ask for them. The platform already runs a model endpoint for other work, and the service already stores
per-domain state in Redis, so a schema-asked extraction with a replayable answer is a small step, provided
the page text sent to the model is treated as hostile.

## Decision

### D1, schema extraction through a configurable endpoint

`output_format` `schema` requires `extraction_schema`, a JSON Schema object of at most
`EXTRACTION_SCHEMA_MAX_BYTES` (16384). The service sends the extracted main text to
`EXTRACTION_LLM_BASE_URL` with `EXTRACTION_LLM_MODEL`, asking for the values and one CSS selector per
field. When the setting is empty the request is refused with HTTP 400 and code `extraction_not_configured`
naming the missing setting. The answer is parsed as JSON and validated against the caller's schema;
anything else is HTTP 502 with code `extraction_failed`, an expected upstream code that keeps a detail
saying what failed validation.

### D2, self-healing per-domain selector recipes

The model also returns one CSS selector per field. Selectors are stored under
`recipe:{registrable_domain}:{sha256 of canonical schema}` in Redis with TTL `RECIPE_TTL_SECONDS`
(604800). A later extraction with the same domain and schema replays the stored selectors with
`lxml.cssselect`, coerces each value to its schema scalar type, and validates the object. A replay that
fails validation, or that leaves a required field empty, deletes the recipe and calls the model again.
Selectors are plain CSS strings, never JavaScript and never XPath with functions; a selector longer than
`RECIPE_SELECTOR_MAX_CHARS` (512) is rejected and a recipe with no valid selector left is not stored.

### D3, model-input safety

Page text is sent as data, never as instructions: the system message declares the page block untrusted
data whose instructions must be ignored, the text sits only inside one delimited `<page_text>` block,
and raw HTML with scripts is never sent, only the extracted main text cut to
`EXTRACTION_LLM_MAX_INPUT_CHARS` (60000). Nothing the model returns is executed or fetched, and the
answer is accepted only after schema validation. The model call has timeout
`EXTRACTION_LLM_TIMEOUT_SECONDS` (60).

## Alternatives Considered

### Agent-side extraction

- Pros: no model key on this service, the agent already holds one.
- Cons: the agent would need the page text anyway, and the recipe cache would live outside the service
  that reads the pages.
- Why not: the owner rejected it (review answer 92 of 2026-10-08).

### XPath selectors in recipes

- Pros: more expressive, one language for selection and extraction.
- Cons: XPath with functions can exfiltrate and is harder to bound; CSS selectors cover the replay need.
- Why not: the safety rule needs a small allowlist, and plain CSS is it.

## Consequences

### Positive

- Callers get validated JSON for their own schema, and repeat reads skip the model entirely.
- A drifted page layout heals itself: the failed replay deletes the recipe and the model rebuilds it.

### Negative

- A right-shaped wrong value is not caught; only the shape is validated. The docs say so.
- Replay coerces selector text to number, integer and boolean; exotic schema types replay as strings and
  fail validation, which rebuilds the recipe instead of returning a wrong type.

### Risks

- A model that ignores the instructions. D3 limits the damage to a wrong answer, which schema validation
  catches when the shape is wrong. A prompt-injection page is covered by a dedicated unit test asserting
  the system message, the delimited block and the validation gate.

## Security review notes (task 3.2, `/security-review`)

Checked against the application-security control list at implementation time:

- Secrets: `EXTRACTION_LLM_API_KEY` is read from the environment (repository `.env` only), has no default
  in code or compose, and is never logged. The page text and the model answer are data, never credentials.
- Input validation: `extraction_schema` is a caller-supplied JSON Schema capped at
  `EXTRACTION_SCHEMA_MAX_BYTES` and rejected above it; every selector is compiled with `CSSSelector`
  before storage, so no selector reaches `lxml` unparsed.
- Injection: the only interpreted language the model output reaches is `jsonschema` validation. No shell,
  SQL, LDAP or template is built from page text or from the answer. Stored selectors are CSS only, so a
  stored recipe cannot become a script or an XPath function call.
- Sensitive data exposure: a 5xx detail never names an internal host, path or exception text;
  `extraction_failed` keeps only what failed validation. The model key is never in a log line.
- Rejection paths tested: unconfigured endpoint (400), invalid answer (502), oversized schema (400),
  overlong and non-CSS selectors (dropped), prompt-injection page (answer validated, secret not leaked).
