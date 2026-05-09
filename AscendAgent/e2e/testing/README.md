### Testing Guide

Manual end-to-end tests for AscendAI capabilities. Each file is a short, focused checklist a tester can run against a live stack (AscendAgent + AscendMemory + Qdrant + Redis + the relevant MCP servers) using `curl`, Bruno, or Postman.

#### Test cases

| Capability | File | Verifies |
|---|---|---|
| Semantic memory | [semantic-memory.md](semantic-memory.md) | A fact stated in one turn is recalled in a later turn from Qdrant |
| RAG | [rag.md](rag.md) | Uploaded document is ingested and retrieved at prompt time |
| PDF read (per-prompt) | [pdf-read.md](pdf-read.md) | A PDF attached to a single prompt is parsed and used as context |
| Image description | [image-description.md](image-description.md) | An attached image is sent to a vision-capable model and described accurately |
| Weather MCP | [weather-mcp.md](weather-mcp.md) | AscendAgent discovers and calls the WeatherMCP tool |

#### Conventions

- Pin a fresh `X-User-Id` per run so prior state can't pollute results.
- `curl` examples are authoritative; Bruno / Postman copies are convenience.
- Pass criteria reference exact log substrings — `grep` them in `./gradlew bootRun` output during the run.
- Tests cover **functionality**, not specific bug fixes. Regression checks belong in the OpenSpec change that introduced the fix.

#### Adding a test case

1. Create `docs/testing/<capability>.md`.
2. Mirror the structure: short intro → **Pre-flight** → **Test 1..N** with **Pass** criteria.
3. Add a row to the table above.
