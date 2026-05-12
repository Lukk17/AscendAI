# semantic-memory-provider-routing Specification

## Purpose
TBD - created by archiving change fix-ascend-agent-bugs. Update Purpose after archive.
## Requirements
### Requirement: AscendMemory routes embedder credentials per provider

`AscendMemory` SHALL resolve a distinct `base_url` + `api_key` pair for each supported embedding provider (`lmstudio`, `openai`, `gemini`) when constructing the mem0 embedder and LLM config, instead of sharing a single `OPENAI_BASE_URL` / `OPENAI_API_KEY` across providers. This SHALL make `provider=openai` requests reach `api.openai.com` (where `text-embedding-3-small` exists) and `provider=lmstudio` requests reach the local LM Studio server, even when both are configured in the same deployment.

#### Scenario: openai-provider request reaches the real OpenAI

- **WHEN** the agent calls `POST /api/v1/memory/insert` with body `{"user_id":"frosty","text":"...","provider":"openai"}`
- **THEN** AscendMemory builds a mem0 embedder with `base_url=https://api.openai.com/v1` and the `OPENAI_API_KEY` env value
- **AND** the embedding request is sent to `api.openai.com` (not to LM Studio)

#### Scenario: lmstudio-provider request reaches LM Studio

- **WHEN** the agent calls `POST /api/v1/memory/insert` with body `{"user_id":"frosty","text":"...","provider":"lmstudio"}`
- **THEN** AscendMemory builds a mem0 embedder with `base_url` pointing at the configured LM Studio URL (e.g. `http://host.docker.internal:1234/v1`) and the LM Studio API key
- **AND** the embedding request is sent to LM Studio (not to `api.openai.com`)

#### Scenario: gemini-provider request reaches Gemini

- **WHEN** the agent calls `POST /api/v1/memory/insert` with body `{"user_id":"frosty","text":"...","provider":"gemini"}`
- **THEN** AscendMemory builds a mem0 embedder with `base_url` pointing at Gemini's OpenAI-compatible endpoint and the `GEMINI_API_KEY` env value
- **AND** the embedding request is sent to Gemini

### Requirement: Provider env vars are independent and required only when used

The AscendMemory `Settings` model SHALL expose three independent base-URL / API-key pairs (`LMSTUDIO_BASE_URL`/`LMSTUDIO_API_KEY`, `OPENAI_BASE_URL`/`OPENAI_API_KEY`, `GEMINI_BASE_URL`/`GEMINI_API_KEY`) with safe defaults where applicable. A missing or blank API key for a provider SHALL only cause failure when that specific provider is invoked, not at startup.

#### Scenario: Boot succeeds when only the default provider's key is configured

- **WHEN** AscendMemory boots with `LMSTUDIO_API_KEY=sk_local` set and no `GEMINI_API_KEY`
- **THEN** the application starts successfully on port 7020
- **AND** requests with `provider=lmstudio` succeed
- **AND** requests with `provider=gemini` fail with a clear error mentioning the missing `GEMINI_API_KEY`

#### Scenario: Default base URLs match expected vendor endpoints

- **WHEN** no `OPENAI_BASE_URL` env var is set
- **THEN** `Settings.OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`
- **AND** `Settings.GEMINI_BASE_URL` defaults to Gemini's OpenAI-compatible endpoint
- **AND** `Settings.LMSTUDIO_BASE_URL` defaults to `http://localhost:1234/v1`

### Requirement: AscendMemory truncates embeddings to the configured collection dimension

`AscendMemory` SHALL pass `embedding_dims` into the mem0 embedder config so the embedding API request includes a `dimensions` parameter that matches the Qdrant collection's expected dimension. Without this, providers like Gemini (`gemini-embedding-001`) return their native 1536-dim vectors and Qdrant rejects them with `Wrong input: Vector dimension error: expected dim: 768, got 1536` because the collection was created at 768.

#### Scenario: Gemini insert succeeds with 768-dim collection

- **WHEN** the agent calls `POST /api/v1/memory/insert` with `{"user_id":"frosty","text":"...","provider":"gemini"}`
- **THEN** AscendMemory's embedder requests embeddings with `dimensions=768` from `https://generativelanguage.googleapis.com/v1beta/openai/embeddings`
- **AND** the resulting 768-dim vector is accepted by the `ascend_memory_768` Qdrant collection
- **AND** the response is HTTP 200, not HTTP 500 with "Vector dimension error"

#### Scenario: OpenAI insert keeps 1536 dimensions

- **WHEN** the agent calls `POST /api/v1/memory/insert` with `{"user_id":"frosty","text":"...","provider":"openai"}`
- **THEN** AscendMemory's embedder requests embeddings with `dimensions=1536`
- **AND** the resulting vector is accepted by the `ascend_memory_1536` collection (no truncation needed since 1536 is the native size)

### Requirement: docker-compose passes per-provider env vars to AscendMemory

`docker-compose.yaml` SHALL pass `LMSTUDIO_BASE_URL`, `LMSTUDIO_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `GEMINI_BASE_URL`, and `GEMINI_API_KEY` to the `ascend-memory` service so that all three providers route correctly out of the box.

#### Scenario: Container env reflects per-provider routing

- **WHEN** `docker compose up -d --build ascend-memory` is run from a fresh checkout
- **THEN** `docker exec ascend-memory env` shows `LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1`
- **AND** shows `OPENAI_BASE_URL=https://api.openai.com/v1`
- **AND** shows `GEMINI_BASE_URL` set to Gemini's OpenAI-compatible endpoint

