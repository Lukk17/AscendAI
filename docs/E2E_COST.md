# End-to-end suite cost

Prices recorded 2026-09-03, usage recorded 2026-09-03 against code at the current working tree (no commit SHA captured, git commands were out of scope for this document). The two halves below are independent on purpose. Provider prices go stale, spec structure and call counts do not. When a provider changes a rate, edit only the price table in [Prices](#prices) and the totals in [How to recalculate](#how-to-recalculate) follow by multiplication. Nothing in [Usage](#usage) needs to change for a price update.

---

### Prices

Snapshot only. Every row below was read from the providers' own pricing pages on 2026-09-03. Re-check the source URL before trusting an old copy of this table.

#### OpenAI

Source: [developers.openai.com/api/docs/pricing](https://developers.openai.com/api/docs/pricing), read 2026-09-03.

| Model | Input $ / million tokens | Output $ / million tokens | Notes |
| :--- | ---: | ---: | :--- |
| gpt-4o | 2.50 | 10.00 | Configured chat default for the openai provider. |
| gpt-4o-mini | 0.15 | 0.60 | Configured memory-extraction and compaction model for the openai provider. |
| gpt-5.1 | unknown | unknown | Not listed on the fetched pricing page. Used as the requested chat model in [AscendAgent e2e spec 2](../AscendAgent/e2e/testing/2-image-description-test.md), so that spec's chat cost cannot currently be priced. |
| Whisper (transcription) | 0.006 $ / minute of audio | n/a | Not a per-token rate. Used by [AudioScribe e2e specs 2 and 5](../AudioScribe/e2e/testing/). |
| text-embedding-3-small | 0.02 | n/a (embedding, input only) | Configured embedding model for the openai provider in AscendAgent. |
| text-embedding-3-large | 0.13 | n/a (embedding, input only) | Priced for completeness. Not wired into any AscendAgent provider config today, see [application.yaml:237-257](../AscendAgent/src/main/resources/application.yaml#L237-L257). |

#### Anthropic

Source: [platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-09-03.

| Model | Input $ / million tokens | Output $ / million tokens | Cache write (5 min) | Cache write (1 hour) | Cache read | Notes |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| Claude Sonnet 4.5 | 3.00 | 15.00 | 3.75 | 6.00 | 0.30 | Configured chat default for the anthropic provider (`claude-sonnet-4-5`). |
| Claude Haiku 3.5 | 0.80 | 4.00 | 1.00 | 1.60 | 0.08 | Retired on the first-party Anthropic API per the same pricing page. Available only through Amazon Bedrock and Google Cloud. This is the exact model string configured as the anthropic memory-extraction model, see [Findings](#findings). |

`claude-sonnet-4-6` is not on this pricing page at all. It is the actual model string sent by [AscendAgent e2e specs 9, 10, and 11](../AscendAgent/e2e/testing/), which is neither the configured default (`claude-sonnet-4-5`) nor a model this snapshot can price. Treat its cost as unknown until Anthropic lists it or the specs are updated to a priced model.

#### Unpriced today

| Item | Why it is unknown | What it affects |
| :--- | :--- | :--- |
| gpt-5.1 | Not on the OpenAI pricing page fetched above. | [AscendAgent e2e spec 2](../AscendAgent/e2e/testing/2-image-description-test.md), the only spec that requests it. |
| claude-sonnet-4-6 | Not on the Anthropic pricing page fetched above. Anthropic's priced Sonnet tier is 4.5, a different model string. | [AscendAgent e2e specs 9, 10, 11](../AscendAgent/e2e/testing/), all of which request it explicitly, plus the `/api/v1/ai/prompt` demo in the root [README.md](../README.md) which uses the same string. |
| MiniMax (`MiniMax-M2.7`) | MiniMax publishes no retrievable per-token price. | [AscendAgent e2e specs 1, 3, 4](../AscendAgent/e2e/testing/), which all request `provider=minimax`. This is also the configured chat, memory-extraction, and compaction model for the minimax provider, see [application.yaml:230-231](../AscendAgent/src/main/resources/application.yaml#L230-L231). |
| Hugging Face Inference (Whisper) | Hugging Face bills compute seconds at the underlying provider's rate rather than a flat per-call or per-minute price. | [AudioScribe e2e spec 3](../AudioScribe/e2e/testing/3-transcribe-hf-test.md). |
| Gemini (chat and embedding) | Not fetched for this snapshot. | No AscendAgent e2e spec currently requests `provider=gemini`, so this gap does not block recalculating today's suite cost. It does block pricing a future Gemini-routed spec. |

#### Models actually wired in per provider

Read from [AscendAgent/src/main/resources/application.yaml](../AscendAgent/src/main/resources/application.yaml). Compaction uses a separate config block (`app.memory.chat-history.compaction.provider-defaults`) from memory extraction (`app.ai.providers.<name>.memory-extraction-model`). The two are different subsystems, each with its own independent per-provider defaults.

| Provider | Chat default | Memory-extraction model | Compaction model | Source lines |
| :--- | :--- | :--- | :--- | :--- |
| openai | gpt-4o | gpt-4o-mini | gpt-4o-mini | [application.yaml:196-197](../AscendAgent/src/main/resources/application.yaml#L196-L197), [:130](../AscendAgent/src/main/resources/application.yaml#L130) |
| anthropic | claude-sonnet-4-5 | claude-3-5-haiku-20241022 | claude-haiku-4-5 | [application.yaml:219-220](../AscendAgent/src/main/resources/application.yaml#L219-L220), [:131](../AscendAgent/src/main/resources/application.yaml#L131) |
| gemini | gemini-flash-latest | gemini-flash-lite-latest | gemini-flash-lite-latest | [application.yaml:206-207](../AscendAgent/src/main/resources/application.yaml#L206-L207), [:132](../AscendAgent/src/main/resources/application.yaml#L132) |
| minimax | MiniMax-M2.7 | MiniMax-M2.7 | MiniMax-M2.7 | [application.yaml:230-231](../AscendAgent/src/main/resources/application.yaml#L230-L231), [:134](../AscendAgent/src/main/resources/application.yaml#L134) |
| lmstudio (local) | meta-llama-3.1-8b-instruct | meta-llama-3.1-8b-instruct | meta-llama-3.1-8b-instruct | [application.yaml:185-186](../AscendAgent/src/main/resources/application.yaml#L185-L186), [:137](../AscendAgent/src/main/resources/application.yaml#L137) |

Embedding providers wired in: lmstudio uses `text-embedding-nomic-embed-text-v2-moe` at 768 dimensions (local, free), openai uses `text-embedding-3-small` at 1536 dimensions, gemini uses `gemini-embedding-001` at 768 dimensions (price not fetched). See [application.yaml:237-257](../AscendAgent/src/main/resources/application.yaml#L237-L257).

---

### Usage

Call counts below are structural facts, derived from the code and from each spec's request payload. Token figures come from the sweep of 2026-09-03. AscendAgent's specs 1, 2, 4, 8, 9, 10, and 11 come from the run at [`AscendAgent/e2e/testing/runs/2026-09-03T19-16-18_*`](../AscendAgent/e2e/testing/runs/), spec 3 comes from the fifth of five back-to-back re-runs at [`AscendAgent/e2e/testing/runs/2026-09-03T20-21-27Z_3-summarization-tasks.md`](../AscendAgent/e2e/testing/runs/2026-09-03T20-21-27Z_3-summarization-tasks.md), run after a retry/fan-out fix for an intermittent document-routing failure (see [Non-cost defects](#non-cost-defects-the-sweep-also-found)). AudioScribe's specs come from [`AudioScribe/e2e/testing/runs/2026-09-03T19-27-52_*`](../AudioScribe/e2e/testing/runs/), and AscendMemory's come from [`AscendMemory/e2e/testing/runs/2026-09-03T19-19-53_*`](../AscendMemory/e2e/testing/runs/) plus a fix re-run at [`AscendMemory/e2e/testing/runs/2026-09-03T19-46-17_*`](../AscendMemory/e2e/testing/runs/) for four specs. Every `<UTC-timestamp>_<N>-<feature>-tasks.md` file carries an `Input tokens` / `Output tokens` field in its `Result summary`, and that field is the source for every number below.

#### Scope: what "outside the storage group" means

[AscendAgent/e2e/README.md](../AscendAgent/e2e/README.md) groups its own specs 5, 6, and 7 as "Group A, the RAG suite" because they share the object-store bucket and the `ascendai-1536` Qdrant collection and must run strictly serially. Those three specs are excluded from the tables below at the requester's instruction. They are not free: spec 5 alone sends three documented prompts through `provider=minimax` with `embeddingProvider=openai`, plus the embedding cost of ingesting three fixture files. If a full-suite dollar total is ever wanted, specs 5, 6, and 7 need their own row, added the same way the rows below were built.

#### A note on totals against the original ask

The task that produced this document stated 43 specifications outside the storage group, 25 free, and paid counts of eight in AscendAgent, two in AudioScribe, four in AscendMemory, roughly 59 total paid calls (23 chat, 34 embedding, 2 audio). Counting the actual spec files on disk today gives a different total: 45 specifications outside the storage group (30 free, 15 paid), because [PaddleOCR/e2e/README.md](../PaddleOCR/e2e/README.md)'s own capability table lists 6 specs but 12 exist on disk (specs 7 through 12 cover `/ready`, MCP SSRF, MCP scheme rejection, MCP credential rejection, MCP file-URI jail, and unsupported MIME, none of which the README table mentions), and because AudioScribe spec 5 also requires `OPENAI_API_KEY` per its own README and therefore counts as a third paid AudioScribe spec, not a second. The eight-in-AscendAgent and four-in-AscendMemory figures did independently verify against the code. This document uses the verified 45 / 30 / 15 split throughout, not the original 43 / 25 estimate. See the tables below for exactly which specs make up the difference.

#### AscendAgent (8 of 11 specs, excluding the storage group)

`embeddingProvider=openai` on every one of these eight requests, confirmed in each spec's Bruno request file under [api/request/AscendAI/ascend-agent/testing/](api/request/AscendAI/ascend-agent/testing/). Chat and embedding call counts follow the structural fact documented under [Findings](#findings): each documented prompt costs 2 chat calls (the main response plus the async memory extractor) and 2 embedding calls (a semantic-memory search plus a RAG retrieval query), both fired unconditionally by [AscendChatService.prompt](../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L45-L79) regardless of whether the prompt concerns memory or retrieval.

| Spec | Name | Provider / model | Prompts | Chat calls | Embedding calls | Input tokens | Output tokens |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | weather-mcp | minimax / MiniMax-M2.7 | 1 | 2 | 2 | 3,692 | 260 |
| 2 | image-description | openai / gpt-5.1 | 1 | 2 | 2 | 3,098 | 644 |
| 3 | summarization | minimax / MiniMax-M2.7 | 1 | 2 | 2 | 1,165 | 3,324 |
| 4 | semantic-memory | minimax / MiniMax-M2.7 | 2 | 4 | 4 | 3,545 | 137 |
| 8 | prompt-cache-openai | openai / gpt-4o | 2 | 4 | 4 | 5,258 | 484 |
| 9 | prompt-cache-anthropic | anthropic / claude-sonnet-4-6 | 2 | 4 | 4 | 1,328 | 740 |
| 10 | compaction-fires | anthropic / claude-sonnet-4-6 + claude-haiku-4-5 | 1 | 2 | 2 | 733 | 159 |
| 11 | compaction-idempotency | anthropic / claude-sonnet-4-6 | 1 | 2 | 2 | 531 | 26 |

Every token figure above is the `metadata.usage` object of the one call in each spec that returns an HTTP response to the caller, the primary chat completion answering the documented prompt. Notes per row where the raw figure hides something:

- Spec 3's row is the sum of five clean executions (233 input tokens each, 1,165 total), not one. The spec failed once with an intermittent 422 `Failed to route PDF page` error before the fix landed. That failed attempt is excluded, and its own retry (inside the fixed code) is not double-counted here either, since only the response actually returned to Bruno carries a `metadata.usage` block.
- Spec 4's and spec 8's and spec 9's figures are each the sum of two calls (one per documented prompt), not one.
- Spec 8's call 2 served 2,560 of its 2,796 input tokens from OpenAI's own prefix cache. Call 1 was a clean miss (0 cached).
- Spec 9's call 1 wrote 3,744 tokens to Anthropic's ephemeral cache (`cache_creation_input_tokens`), and call 2 read that same 3,744-token block back (`cache_read_input_tokens`). The 1,328-token input figure above is the non-cached portion of both calls combined.
- Spec 10's 733/159 figures cover only its call 1 (claude-sonnet-4-6, the documented prompt), which read the same 3,744-token cache entry spec 9 wrote. Its second, server-side call to claude-haiku-4-5 for the compaction summary billed a further 115 input tokens (recovered from a log line, not a response body, see [Findings](#findings)), and that call's output token count is not logged anywhere in this build and is excluded from the 159 above, not counted as zero.
- Spec 11 read the same 3,744-token cache entry again and additionally wrote 4 new cache tokens, too small to move any total in this document by a full cent.

None of the 22 embedding calls, none of the 11 async memory-extraction chat calls (one per documented prompt, fired unconditionally per [Findings](#findings)), and spec 10's compaction call return a usage object the sweep could observe. The [Cost of the 2026-09-03 sweep](#cost-of-the-2026-09-03-sweep) section below prices only what these numbers can price, and lists everything else as an open gap rather than a zero.

Totals: 22 chat calls, 22 embedding calls, of which 11 chat calls (one per documented prompt) return the measurable token figures above: 19,350 input tokens and 5,774 output tokens summed across the eight rows.

#### AudioScribe (3 of 5 specs)

Each paid spec makes exactly one transcription call. Free: spec 1 (invalid input, rejected before any provider call) and spec 4 (MCP `tools/list`, a protocol probe with no provider call).

| Spec | Name | Provider | Calls | Duration (measured) | Input tokens | Output tokens |
| :--- | :--- | :--- | ---: | ---: | :--- | :--- |
| 2 | transcribe-openai | OpenAI Whisper (`whisper-1`) | 1 | 9.48 s (0.158 min) | not applicable, billed by audio duration | not applicable, billed by audio duration |
| 3 | transcribe-hf | Hugging Face Inference (`whisper-large-v3`) | 1 | 9.48 s (0.158 min) | not applicable, billed by audio duration | not applicable, billed by audio duration |
| 5 | mcp-transcribe | OpenAI Whisper (via MCP tool) | 1 | not re-measured in this sweep | not applicable, billed by audio duration | not applicable, billed by audio duration |

Both duration figures come from `ffprobe` against the shared fixture, [`AudioScribe/e2e/fixtures/meeting-clip.wav`](../AudioScribe/e2e/fixtures/meeting-clip.wav), read during the [transcribe-openai run](../AudioScribe/e2e/testing/runs/2026-09-03T19-27-52_2-transcribe-openai-tasks.md). Neither provider returned a usage object for either call, which is expected: Whisper transcription is billed by audio minute, not by token, and the AudioScribe REST endpoint returns only the flat transcript text, not the raw provider response. Spec 5 (mcp-transcribe) makes a third structural paid call on the same fixture through the same OpenAI backend, but the 2026-09-03T19-27-52 sweep did not include it. It was last exercised earlier the same day at [17:06 UTC](../AudioScribe/e2e/testing/runs/2026-09-03T17-06-00_5-mcp-transcribe-tasks.md), also against `meeting-clip.wav`. If it ran at the same duration, it would add another 0.158 minutes at the OpenAI rate. This document does not add it to the priced total below, since it was not part of the final measured pass.

The fixture itself carries a defect: it is documented in the AudioScribe e2e suite as a five-second mono WAV but is actually a 9.48-second LAME-encoded MP3 elementary stream wearing a `.wav` filename (see [Non-cost defects](#non-cost-defects-the-sweep-also-found)). The 0.158-minute duration used below is the real, measured one.

Totals: 3 transcription calls structurally, 2 against OpenAI (priced at 0.006 $/minute) and 1 against Hugging Face (unpriced). The cost section below prices the 2 calls the final sweep actually measured.

#### AscendMemory (4 of 6 specs)

Every insert and every search issues one embedding call against mem0's configured embedding backend, never a chat call ([docker-compose.yaml:168](../docker-compose.yaml#L168) sets `MEM0_INFER_MEMORY=false`, so mem0's LLM-based fact inference is off and only the embedding path runs). Free: spec 1 (invalid input, rejected before mem0 is touched) and spec 4 (MCP `tools/list`, a protocol probe).

| Spec | Name | Embedding calls | Input tokens | Output tokens |
| :--- | :--- | ---: | :--- | :--- |
| 2 | insert-and-search | 2 | not observable, see estimate below | n/a, embedding has no output |
| 3 | wipe-user-scope | 4 | not observable, see estimate below | n/a, embedding has no output |
| 5 | mcp-insert-and-search | 2 | not observable, see estimate below | n/a, embedding has no output |
| 6 | user-isolation | 2 | not observable, see estimate below | n/a, embedding has no output |

Totals: 10 embedding calls in this first pass.

The open question the original version of this document left unresolved is now settled: the sweep's calls billed against `text-embedding-3-small`, confirming [docker-compose.yaml:170](../docker-compose.yaml#L170)'s `openai` alternative, not the `lmstudio` default, was the active line at run time. `mem0/embeddings/openai.py`'s `OpenAIEmbedding.embed` discards the provider's `usage` object before it reaches AscendMemory's own response, confirmed by reading that file inside the running container during the [insert-and-search run](../AscendMemory/e2e/testing/runs/2026-09-03T19-19-53_2-insert-and-search-tasks.md#L44-L46), so none of the calls in the table above have a directly observed token count. Every embedded string is one of six short fixture sentences (for example "My favourite city is Reykjavik"), estimated at roughly seven to ten tokens each. This is an estimate, not a measurement, the only one in this document, and it is kept visually separate in the cost section below.

A fix for a double-encoded query-string defect (see [Non-cost defects](#non-cost-defects-the-sweep-also-found)) triggered a second pass: specs 1, 2, 3, and 6 were re-run against corrected request files at [`AscendMemory/e2e/testing/runs/2026-09-03T19-46-17_*`](../AscendMemory/e2e/testing/runs/). Spec 1 (invalid-input) makes no embedding call at all, validation rejects the request before mem0 is reached, so the four re-run specs actually add 8 embedding calls, not 4: 2 from spec 2, 4 from spec 3, 2 from spec 6, read directly from each re-run's own Result summary. Ten from the first pass plus eight from the re-run gives 18 embedding calls total against `text-embedding-3-small`, all in the same seven-to-ten-token band. This document uses 18 in the cost section below, not the smaller figure the day's own running total suggested, because the four re-run specs are not the same thing as four re-run calls.

#### PaddleOCR, AscendWebSearch, WeatherMCP (26 specs, all free)

Every spec in these three modules drives only local or self-hosted services (the on-image PaddleOCR engine, SearXNG plus curl_cffi/FlareSolverr/Playwright, and the Open-Meteo API respectively) and makes no call to any priced LLM or embedding provider. 12 PaddleOCR specs, 7 AscendWebSearch specs, 7 WeatherMCP specs. See [PaddleOCR/e2e/README.md](../PaddleOCR/e2e/README.md), [AscendWebSearch/e2e/README.md](../AscendWebSearch/e2e/README.md), and [WeatherMCP/e2e/README.md](../WeatherMCP/e2e/README.md) for the full per-spec list. No per-row cost table is needed here, since every cell would read zero.

---

### How to recalculate

1. Open [Prices](#prices) and replace any rate that changed, keeping the source URL and read date on the row.
2. Leave every table in [Usage](#usage) untouched. Call counts do not change when a price changes.
3. For each paid row, multiply its input and output token counts (once filled in from the matching run record) by the matching price-table rate, add cache-read or cache-write rates where the spec exercises prompt caching (specs 8 and 9), and sum across rows.
4. For AudioScribe rows, multiply audio minutes by the $/minute rate instead of a token rate.
5. Treat any row still marked unknown in [Prices](#prices) as an open cost, not a zero. gpt-5.1, claude-sonnet-4-6, MiniMax, and the Hugging Face transcription call together cover 6 of the 8 AscendAgent specs and 1 of the 3 AudioScribe specs, so most of this suite's real dollar cost is currently unrecalculable until those four gaps close.

---

### Cost of the 2026-09-03 sweep

This is the arithmetic from step 3 and step 4 of [How to recalculate](#how-to-recalculate) worked through against the measured [Usage](#usage) figures and the priced rows of [Prices](#prices) as they stood on 2026-09-03. Only three of the sweep's paid rows land on a priced model. Everything else is either flagged unpriceable or, where marked, an explicit illustration and not a real quote.

#### What can be priced with certainty

AscendAgent spec 8, prompt-cache-openai, gpt-4o, 2.50 / 10.00 $ per million tokens:

- Call 1: 2,462 input x 2.50 / 1,000,000 = 0.0061550, plus 238 output x 10.00 / 1,000,000 = 0.0023800. Call 1 = 0.0085350.
- Call 2: 2,796 input x 2.50 / 1,000,000 = 0.0069900, plus 246 output x 10.00 / 1,000,000 = 0.0024600. Call 2 = 0.0094500.
- Spec 8 total = 0.0180 (rounded).

This figure is a ceiling, not the true call-2 price. 2,560 of call 2's 2,796 input tokens were served from OpenAI's own prefix cache, and OpenAI bills cached input below the standard rate. The [Prices](#prices) table has no confirmed cached-input rate for gpt-4o (only Anthropic's rows carry cache columns, because that snapshot came with them, and OpenAI's cached-input discount was not separately fetched). The 0.0180 above assumes no discount at all, so the true spec 8 cost is somewhere at or below it, by an amount this document cannot state.

AudioScribe transcribe-openai, Whisper `whisper-1`, 0.006 $ per minute:

- 0.158 min x 0.006 = 0.000948.

AscendMemory, text-embedding-3-small, 0.02 $ per million input tokens, 18 calls at an estimated 7 to 10 tokens each (the only estimate in this document, per [Usage](#usage)):

- Low: 18 x 7 = 126 tokens x 0.02 / 1,000,000 = 0.0000025.
- High: 18 x 10 = 180 tokens x 0.02 / 1,000,000 = 0.0000036.
- Effectively zero next to the other two rows, carried at 0.000003 in the subtotal below.

Priced subtotal = 0.0180 + 0.000948 + 0.000003 = 0.018951, rounded to 0.02 $.

#### What cannot be priced at all

| Item | Specs it covers | Measured volume | Why it has no price |
| :--- | :--- | :--- | :--- |
| MiniMax M2.7 | AscendAgent 1, 3, 4 | 8,402 input + 3,721 output tokens | MiniMax publishes no retrievable per-token rate. |
| gpt-5.1 | AscendAgent 2 | 3,098 input + 644 output tokens | Not on the fetched OpenAI pricing page. |
| claude-sonnet-4-6 | AscendAgent 9, 10 (call 1), 11 | 2,477 non-cached input + 925 output tokens, plus 3,748 cache-write and 11,232 cache-read tokens across the three specs | Not on the fetched Anthropic pricing page. The priced Sonnet tier is 4.5, a different model string. |
| claude-haiku-4-5 | AscendAgent 10 (call 2) | 115 input tokens, output not logged by the service at all | Not on the fetched Anthropic pricing page. The priced Haiku tier (3.5) is retired on the first-party API. |
| Hugging Face Inference | AudioScribe transcribe-hf | 0.158 minutes | Hugging Face bills compute seconds at the underlying provider's rate, not a flat published price. |
| AudioScribe spec 5 (mcp-transcribe) | AudioScribe 5 | not re-measured in the final sweep | Structurally a third paid OpenAI Whisper call on the same fixture. Excluded from the priced subtotal because it wasn't part of the 19:27:52 pass, see [Usage](#usage). |

#### Illustrative-only figures: not a real price, kept separate on purpose

Everything below substitutes the nearest same-vendor model this snapshot could price, purely to give a sense of scale. None of these are what the sweep was actually billed. Do not add them to the priced subtotal above as if they were measured.

gpt-5.1, illustrated at gpt-4o's rate (AscendAgent spec 2): 3,098 x 2.50 / 1,000,000 = 0.007745, plus 644 x 10.00 / 1,000,000 = 0.006440. Illustrative total = 0.014185.

claude-sonnet-4-6, illustrated at Claude Sonnet 4.5's rate (3.00 / 15.00 $ per million tokens, cache write 3.75, cache read 0.30):

- Spec 9, call 1: 427 x 3.00 / 1e6 = 0.001281, 370 x 15.00 / 1e6 = 0.00555, cache write 3,744 x 3.75 / 1e6 = 0.01404. Call 1 = 0.020871.
- Spec 9, call 2: 901 x 3.00 / 1e6 = 0.002703, 370 x 15.00 / 1e6 = 0.00555, cache read 3,744 x 0.30 / 1e6 = 0.0011232. Call 2 = 0.0093762.
- Spec 10, call 1: 618 x 3.00 / 1e6 = 0.001854, 159 x 15.00 / 1e6 = 0.002385, cache read 3,744 x 0.30 / 1e6 = 0.0011232. Spec 10 total = 0.0053622.
- Spec 11: 531 x 3.00 / 1e6 = 0.001593, 26 x 15.00 / 1e6 = 0.00039, cache read 3,744 x 0.30 / 1e6 = 0.0011232, cache write 4 x 3.75 / 1e6 = 0.000015. Spec 11 total = 0.0031212.
- Illustrative Sonnet total = 0.0387306.

claude-haiku-4-5, illustrated at Claude Haiku 3.5's rate (0.80 / 4.00 $ per million tokens), input only (spec 10's compaction output is unlogged): 115 x 0.80 / 1e6 = 0.000092.

Illustrative subtotal = 0.014185 + 0.0387306 + 0.000092 = 0.053008, rounded to 0.0530 $.

#### Headline

The sweep of 2026-09-03 cost about 0.02 $ that this document can price with certainty. Extending that with the illustrative same-vendor stand-ins above for every unpriced OpenAI and Anthropic model brings it to about 0.07 $, more than three times the priced figure, and even that illustrative figure still excludes MiniMax entirely (over 12,000 measured tokens across three specs) and the Hugging Face transcription (0.158 minutes), because neither publishes anything this document can anchor an illustration to.

Call the honest range 0.02 $ to 0.07 $. Both ends carry real uncertainty: the low end undercounts by omission (it prices nothing that ran on MiniMax, gpt-5.1, claude-sonnet-4-6, or Hugging Face), and the high end is not a quote from any vendor for the model actually used, only a same-vendor stand-in a version behind. Whichever number a reader repeats, the gap between them, roughly 0.05 $, is entirely attributable to the four pricing gaps in [Prices](#prices), not to any uncertainty in the measured token counts themselves.

---

### Findings

Two defects surfaced while tracing how a single documented prompt turns into billed calls. Both change what the Usage table above actually means, so they are recorded here rather than left as a footnote.

#### Every documented prompt costs more than its spec's Run section suggests

[AscendChatService.prompt](../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L45-L79) runs four external calls for what a spec's Run section shows as one prompt: `contextAssembler.buildSystemMessages` at line 58 calls [ChatContextAssembler.fetchSemanticMemory](../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/chat/ChatContextAssembler.java#L74-L81), an unconditional AscendMemory search that embeds the query. `contextAssembler.buildUserMessage` at line 59 calls [RagRetrievalService.retrieve](../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/rag/RagRetrievalService.java#L59-L112), which runs a Qdrant similarity search (line 83) whenever RAG is enabled, which it is by default (`app.rag.enabled: true`, [application.yaml:271](../AscendAgent/src/main/resources/application.yaml#L271)), regardless of whether the prompt has anything to do with retrieval. `chatExecutor.execute` at line 63 is the main chat call. `semanticMemoryExtractor.extract` at line 69 fires a second, asynchronous chat call. One documented prompt is therefore two paid chat calls plus two paid embedding calls, which is exactly the multiplier applied throughout the AscendAgent table above.

The 2026-09-03 sweep confirms this in practice, not only in code. The eleven documented prompts across the eight measured specs in [Usage](#usage) each produce a visible, priceable `metadata.usage` object for exactly one call, the primary chat completion. None of the eleven async extractor calls those same eleven prompts fire, none of the 22 embedding calls, and spec 10's compaction call return a usage object the e2e harness can see. Spec 10 is the sharpest case: its compaction call to claude-haiku-4-5 never returns an HTTP response to the caller at all, and its 115-token input count was only recoverable by reading `docker logs ascend-agent` for the `AnthropicPromptCacheStrategy` log line during [that run](../AscendAgent/e2e/testing/runs/2026-09-03T19-16-18_10-compaction-fires-tasks.md), with its output token count never surfacing anywhere in this build. A specification's Run section shows one HTTP request per documented prompt, and the sweep shows at least two billed calls behind every one of them, with the second, or the third for spec 10, invisible to anything the harness can observe directly.

#### The memory extractor bills at the caller's model, not the configured cheap one

[SemanticMemoryExtractor.resolveExtractionModel](../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java#L148-L155) returns the caller-supplied model whenever one was supplied, and only falls back to the provider's configured `memory-extraction-model` when the caller passed none:

```java
private String resolveExtractionModel(String provider, String requestedModel) {
    if (StringUtils.hasText(requestedModel)) {
        return requestedModel;
    }
    return Optional.ofNullable(aiProviderProperties.getProviders().get(provider))
            .map(AiProviderProperties.ProviderConfig::getMemoryExtractionModel)
            .orElse(null);
}
```

[AscendChatService.java:69](../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L69) calls `semanticMemoryExtractor.extract(userId, prompt, provider, model, activeEmbeddingProvider)`, passing through the same `model` the caller requested for the main chat call. Since every AscendAgent e2e spec, and the `/api/v1/ai/prompt` demo in the root [README.md](../README.md), sends an explicit `model` field, the fallback to the cheap configured model essentially never fires in practice. The clearest priced example is spec 8: it requests `provider=openai`, `model=gpt-4o`, so its extraction call also runs on gpt-4o (2.50 / 10.00 $ per million tokens) instead of the configured gpt-4o-mini (0.15 / 0.60 $ per million tokens), roughly 16.7 times the rate on both input and output for a call whose entire job is picking short facts out of one message. Specs 9, 10, and 11 compound this with the unpriced `claude-sonnet-4-6` from the findings above. Specs 1, 3, and 4 are unaffected in dollar terms only because minimax has no separate cheap tier: [application.yaml:231](../AscendAgent/src/main/resources/application.yaml#L231) configures `MiniMax-M2.7` as both the chat default and the memory-extraction model for that provider, so the caller-supplied model and the fallback happen to be identical.

#### The configured Anthropic extraction model is retired, and the first defect is the only reason nobody has hit it

[application.yaml:220](../AscendAgent/src/main/resources/application.yaml#L220) configures `claude-3-5-haiku-20241022` as the anthropic provider's memory-extraction model. Per the Anthropic pricing page cited in [Prices](#prices), that exact model is Claude Haiku 3.5, retired on the first-party Anthropic API and available only through Amazon Bedrock and Google Cloud. A call to it via `api.anthropic.com` (the base URL configured at [application.yaml:214](../AscendAgent/src/main/resources/application.yaml#L214)) would fail. This has not surfaced as a production incident because the first defect above means the fallback path that would reach this model almost never executes. Any request that omits the `model` field while using `provider=anthropic` would trigger it today.

---

### Non-cost defects the sweep also found

None of these affect the arithmetic above. They are recorded here because the run records that hold them are the reason this document could redo the sweep's math at all instead of guessing, and a future reader deciding whether to keep archiving run records should know what else they have paid for.

- A specification asserted on a log line instead of an observable outcome.
- Five assertions read response fields that do not exist in the payload they were checking.
- Two specifications named response fields the service never actually returns.
- Four request files sent double-encoded query text: `search-reykjavik.yml`, `search-alpha.yml`, `search-beta.yml`, and `search-isolation-user-b.yml` under [docs/api/request/AscendAI/memory/testing/](../docs/api/request/AscendAI/memory/testing/), each manually percent-encoding a value that Bruno's own `encodeUrl: true` setting then encoded a second time, corrected and re-run at [`AscendMemory/e2e/testing/runs/2026-09-03T19-46-17_*`](../AscendMemory/e2e/testing/runs/).
- Specifications instructed the runner to print API keys into the transcript: AudioScribe's `OPENAI_API_KEY` and `HF_TOKEN` prerequisite checks in its OpenAI and Hugging Face transcription specs, both substituted for a non-printing presence check instead.
- A fixture documented as a five-second mono WAV turned out to be a 9.48-second MP3 elementary stream wearing a `.wav` filename: [`AudioScribe/e2e/fixtures/meeting-clip.wav`](../AudioScribe/e2e/fixtures/meeting-clip.wav).
- A check asserted a response-time threshold as proof a backend call never fired, but container overhead alone already sits above that threshold on every request regardless of truth. AscendMemory's invalid-input spec was corrected to a structural proof plus an observable Qdrant point-count check instead.
- A request file was weaker than its siblings, missing an assertion the equivalent requests in the same spec all carried.
- A document-conversion failure, an intermittent 422 `Failed to route PDF page` error on the AscendAgent summarization spec, traced back to a supervisor process killing its own worker rather than to the document or the model. Fixed with a retry/fan-out and confirmed clean across [five consecutive re-runs](../AscendAgent/e2e/testing/runs/2026-09-03T20-21-27Z_3-summarization-tasks.md).

---

### Documentation

Related material:

- [AscendAgent/e2e/README.md](../AscendAgent/e2e/README.md) for the spec format, execution groups, and where run records land.
- [AscendAgent/src/main/resources/application.yaml](../AscendAgent/src/main/resources/application.yaml) for the live provider and model configuration this document was checked against.
- [AGENTS.md](../AGENTS.md) and [AscendAgent/AGENTS.md](../AscendAgent/AGENTS.md) for the platform and module overviews.
