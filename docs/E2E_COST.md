# End-to-end suite cost

Usage recorded 2026-09-03 against code at the current working tree (no commit SHA captured, git commands were out of scope for this document); the ascend-web-hunter spec count was corrected 2026-09-06, see [A note on totals against the original ask](#a-note-on-totals-against-the-original-ask). Prices first recorded 2026-09-03 and revised 2026-09-04, when the four gaps the first pass left open were closed. The two halves below are independent on purpose. Provider prices go stale on their own; spec structure and call counts only change when a spec is added, removed, or found to have been miscounted, which is a correction rather than drift. When a provider changes a rate, edit only the price table in [Prices](#prices) and the totals in [How to recalculate](#how-to-recalculate) follow by multiplication. Nothing in [Usage](#usage) needs to change for a price update.

MiniMax is deliberately absent from every dollar figure below. The account it runs on is a flat subscription rather than metered per-token billing, so the three specs routed through `MiniMax-M2.7` add nothing to the marginal cost of running the sweep again. Their token counts stay in [Usage](#usage), because those are structural facts about the suite, and they are simply never multiplied by a rate.

---

### Prices

Snapshot only. Every row below was read from the providers' own pricing pages, on the date the row's source line names. Re-check the source URL before trusting an old copy of this table.

#### OpenAI

Source: [developers.openai.com/api/docs/pricing](https://developers.openai.com/api/docs/pricing), re-read 2026-09-04. The page carries no publication date of its own. The only dates it prints anywhere are 2026-03-05, against a data-residency eligibility note, and 2026-07-30, against a Fast-mode renaming announcement, neither of which stamps the price table.

| Model | Input $ / million tokens | Cached input $ / million tokens | Output $ / million tokens | Notes |
| :--- | ---: | ---: | ---: | :--- |
| gpt-5.1 | 1.25 | 0.125 | 10.00 | Confirmed 2026-09-04. The 2026-09-03 pass recorded this as unknown, which was wrong: the model is on the page. Requested chat model in [ascend-ai-agent e2e spec 2](../apps/ascend-agent/e2e/testing/2-image-description-test.md). |
| gpt-4o | 2.50 | 1.25 | 10.00 | Configured chat default for the openai provider. The cached-input rate is confirmed at exactly half the standard input rate, closing the gap the 2026-09-03 pass left open on [spec 8](../apps/ascend-agent/e2e/testing/8-prompt-cache-openai-test.md)'s 2,560 cached tokens. |
| gpt-4o-mini | 0.15 | n/a (not separately checked) | 0.60 | Configured memory-extraction and compaction model for the openai provider. Never actually billed in this sweep, see [Findings](#findings). |
| Whisper (transcription) | 0.006 $ / minute of audio | n/a | n/a | Not a per-token rate. Used by [ascend-audio-scribe e2e specs 2 and 5](../apps/ascend-audio-scribe/e2e/testing/). The page prices "Whisper" without the `whisper-1` suffix the service actually sends. |
| text-embedding-3-small | 0.02 | n/a | n/a (embedding, input only) | Configured embedding model for the openai provider in ascend-ai-agent, and the model AscendMemory's own specs billed against. |
| text-embedding-3-large | 0.13 | n/a | n/a (embedding, input only) | Priced for completeness. Not wired into any ascend-ai-agent provider config today, see [application.yaml:237-257](../apps/ascend-agent/src/main/resources/application.yaml#L237-L257). |

#### Anthropic

Source: Anthropic's own model pricing table, cached 2026-06-24. Cache-read and cache-write rates for Sonnet 4.6 follow Anthropic's standard multipliers on the input rate, roughly one tenth for a read and 1.25 times for a five-minute write.

| Model | Input $ / million tokens | Output $ / million tokens | Cache write (5 min) | Cache read | Source and date | Notes |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| Claude Sonnet 4.6 | 3.00 | 15.00 | 3.75 | 0.30 | Anthropic model pricing table, cached 2026-06-24 | The model string actually sent by [ascend-ai-agent e2e specs 9, 10, and 11](../apps/ascend-agent/e2e/testing/). The 2026-09-03 pass could not price it. |
| Claude Haiku 4.5 | 1.00 | 5.00 | 1.25 | 0.10 | Anthropic model pricing table, cached 2026-06-24 | Configured compaction model for the anthropic provider. Billed once in this sweep, by [spec 10](../apps/ascend-agent/e2e/testing/10-compaction-fires-test.md)'s server-side compaction call. |
| Claude Sonnet 4.5 | 3.00 | 15.00 | 3.75 | 0.30 | [platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-09-03 | Configured chat default for the anthropic provider (`claude-sonnet-4-5`). No spec actually requests it, because every spec sends an explicit `model` field. |
| Claude Haiku 3.5 | 0.80 | 4.00 | 1.00 | 0.08 | [platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-09-03 | Retired on the first-party Anthropic API per that page. Available only through Amazon Bedrock and Google Cloud. This is the exact model string configured as the anthropic memory-extraction model, see [Findings](#findings). Never billed in this sweep. |

#### Hugging Face Inference

Source: [huggingface.co/docs/inference-providers/pricing](https://huggingface.co/docs/inference-providers/pricing), read 2026-09-04. The page prints no publication date. Its only internal date marker is "As of July 2025", against a note that `hf-inference` focuses mostly on CPU inference.

There is no flat rate for a speech-recognition call, and none for Whisper specifically. The page states the rule directly: past the free-tier credits "you get charged for every inference request based on the compute time x price of the underlying hardware", and Hugging Face "charges you the same rates as the provider, with no additional fees". The single concrete hardware rate the page publishes is inside its own worked example: a request that takes 10 seconds on a GPU machine costing 0.00012 $ per second bills 0.0012 $.

That 0.00012 $ per GPU second is therefore the only anchor available, and every Hugging Face figure in this document is an approximation built on it. See [Cost of the 2026-09-03 sweep](#cost-of-the-2026-09-03-sweep) for how the 9.48-second clip is converted.

#### Excluded from money on purpose

| Item | Why | What it affects |
| :--- | :--- | :--- |
| MiniMax (`MiniMax-M2.7`) | The account is on a flat subscription, not metered per-token billing. Running these specs again costs nothing marginal, so multiplying their tokens by any rate would overstate the sweep. | [ascend-ai-agent e2e specs 1, 3, 4](../apps/ascend-agent/e2e/testing/), which all request `provider=minimax`. Their token counts stay in [Usage](#usage) and are simply never priced. This is also the configured chat, memory-extraction, and compaction model for the minimax provider, see [application.yaml:230-231](../apps/ascend-agent/src/main/resources/application.yaml#L230-L231). |

#### Still unpriced

| Item | Why it is unknown | What it affects |
| :--- | :--- | :--- |
| Gemini (chat and embedding) | Not fetched for this snapshot. | No ascend-ai-agent e2e spec currently requests `provider=gemini`, so this gap does not block recalculating today's suite cost. It does block pricing a future Gemini-routed spec. |

#### Models actually wired in per provider

Read from [apps/ascend-agent/src/main/resources/application.yaml](../apps/ascend-agent/src/main/resources/application.yaml). Compaction uses a separate config block (`app.memory.chat-history.compaction.provider-defaults`) from memory extraction (`app.ai.providers.<name>.memory-extraction-model`). The two are different subsystems, each with its own independent per-provider defaults.

| Provider | Chat default | Memory-extraction model | Compaction model | Source lines |
| :--- | :--- | :--- | :--- | :--- |
| openai | gpt-4o | gpt-4o-mini | gpt-4o-mini | [application.yaml:196-197](../apps/ascend-agent/src/main/resources/application.yaml#L196-L197), [:130](../apps/ascend-agent/src/main/resources/application.yaml#L130) |
| anthropic | claude-sonnet-4-5 | claude-3-5-haiku-20241022 | claude-haiku-4-5 | [application.yaml:219-220](../apps/ascend-agent/src/main/resources/application.yaml#L219-L220), [:131](../apps/ascend-agent/src/main/resources/application.yaml#L131) |
| gemini | gemini-flash-latest | gemini-flash-lite-latest | gemini-flash-lite-latest | [application.yaml:206-207](../apps/ascend-agent/src/main/resources/application.yaml#L206-L207), [:132](../apps/ascend-agent/src/main/resources/application.yaml#L132) |
| minimax | MiniMax-M2.7 | MiniMax-M2.7 | MiniMax-M2.7 | [application.yaml:230-231](../apps/ascend-agent/src/main/resources/application.yaml#L230-L231), [:134](../apps/ascend-agent/src/main/resources/application.yaml#L134) |
| lmstudio (local) | meta-llama-3.1-8b-instruct | meta-llama-3.1-8b-instruct | meta-llama-3.1-8b-instruct | [application.yaml:185-186](../apps/ascend-agent/src/main/resources/application.yaml#L185-L186), [:137](../apps/ascend-agent/src/main/resources/application.yaml#L137) |

Embedding providers wired in: lmstudio uses `text-embedding-nomic-embed-text-v2-moe` at 768 dimensions (local, free), openai uses `text-embedding-3-small` at 1536 dimensions, gemini uses `gemini-embedding-001` at 768 dimensions (price not fetched). See [application.yaml:237-257](../apps/ascend-agent/src/main/resources/application.yaml#L237-L257).

---

### Usage

Call counts below are structural facts, derived from the code and from each spec's request payload. Token figures come from the sweep of 2026-09-03. ascend-ai-agent's specs 1, 2, 4, 8, 9, 10, and 11 come from the run at [`apps/ascend-agent/e2e/testing/runs/2026-09-03T19-16-18_*`](../apps/ascend-agent/e2e/testing/runs/), spec 3 comes from the fifth of five back-to-back re-runs at [`apps/ascend-agent/e2e/testing/runs/2026-09-03T20-21-27Z_3-summarization-tasks.md`](../apps/ascend-agent/e2e/testing/runs/2026-09-03T20-21-27Z_3-summarization-tasks.md), run after a retry/fan-out fix for an intermittent document-routing failure (see [Non-cost defects](#non-cost-defects-the-sweep-also-found)). ascend-audio-scribe's specs come from [`apps/ascend-audio-scribe/e2e/testing/runs/2026-09-03T19-27-52_*`](../apps/ascend-audio-scribe/e2e/testing/runs/), and AscendMemory's come from [`apps/ascend-memory/e2e/testing/runs/2026-09-03T19-19-53_*`](../apps/ascend-memory/e2e/testing/runs/) plus a fix re-run at [`apps/ascend-memory/e2e/testing/runs/2026-09-03T19-46-17_*`](../apps/ascend-memory/e2e/testing/runs/) for four specs. Every `<UTC-timestamp>_<N>-<feature>-tasks.md` file carries an `Input tokens` / `Output tokens` field in its `Result summary`, and that field is the source for every number below.

#### Scope: what "outside the storage group" means

[apps/ascend-agent/e2e/README.md](../apps/ascend-agent/e2e/README.md) groups its own specs 5, 6, and 7 as "Group A, the RAG suite" because they share the object-store bucket and the `ascendai-1536` Qdrant collection and must run strictly serially. Those three specs are excluded from the tables below at the requester's instruction. They are not free: spec 5 alone sends three documented prompts through `provider=minimax` with `embeddingProvider=openai`, plus the embedding cost of ingesting three fixture files. If a full-suite dollar total is ever wanted, specs 5, 6, and 7 need their own row, added the same way the rows below were built.

#### A note on totals against the original ask

The task that produced this document stated 43 specifications outside the storage group, 25 free, and paid counts of eight in ascend-ai-agent, two in ascend-audio-scribe, four in AscendMemory, roughly 59 total paid calls (23 chat, 34 embedding, 2 audio). Counting the actual spec files on disk as of 2026-09-03 gave a different total: 45 specifications outside the storage group (30 free, 15 paid), because [apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md)'s own capability table lists 6 specs but 12 exist on disk (specs 7 through 12 cover `/ready`, MCP SSRF, MCP scheme rejection, MCP credential rejection, MCP file-URI jail, and unsupported MIME, none of which the README table mentions), and because ascend-audio-scribe spec 5 also requires `OPENAI_API_KEY` per its own README and therefore counts as a third paid ascend-audio-scribe spec, not a second. The eight-in-ascend-ai-agent and four-in-AscendMemory figures did independently verify against the code.

Re-counting the spec files on disk on 2026-09-06 moves the total again, to 48 specifications outside the storage group (33 free, 15 paid). The paid side is unchanged; the free side moved because [apps/ascend-web-hunter/e2e/README.md](../apps/ascend-web-hunter/e2e/README.md) undercounted its own module the same way the ascend-ocr README did: its capability table listed 7 specs while 8 already existed on disk (spec 8, `session/clear`, had a Bruno request, an e2e spec, and a task template but was never added to the table), and two more specs (9, `session/status`, and 10, `session/establish`) were added on 2026-09-06 to close a matching gap — both endpoints existed in the router and were already unit-tested, just never carried through to the e2e suite or the Bruno collection. ascend-web-hunter's real count is therefore 10, not 7. This document uses the verified 48 / 33 / 15 split throughout, not the 45 / 30 / 15 figure the 2026-09-03 pass settled on. See the tables below for exactly which specs make up the difference.

#### ascend-ai-agent (8 of 11 specs, excluding the storage group)

`embeddingProvider=openai` on every one of these eight requests, confirmed in each spec's Bruno request file under [api/request/AscendAI/ascend-agent/testing/](api/request/AscendAI/ascend-agent/testing/). Chat and embedding call counts follow the structural fact documented under [Findings](#findings): each documented prompt costs 2 chat calls (the main response plus the async memory extractor) and 2 embedding calls (a semantic-memory search plus a RAG retrieval query), both fired unconditionally by [AscendChatService.prompt](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L45-L79) regardless of whether the prompt concerns memory or retrieval.

| Spec | Name | Provider / model | Prompts | Chat calls | Embedding calls | Input tokens | Output tokens |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | ascend-weather-mcp | minimax / MiniMax-M2.7 | 1 | 2 | 2 | 3,692 | 260 |
| 2 | image-description | openai / gpt-5.1 | 1 | 2 | 2 | 3,098 | 644 |
| 3 | summarization | minimax / MiniMax-M2.7 | 5 | 10 | 10 | 1,165 | 3,324 |
| 4 | semantic-memory | minimax / MiniMax-M2.7 | 2 | 4 | 4 | 3,545 | 137 |
| 8 | prompt-cache-openai | openai / gpt-4o | 2 | 4 | 4 | 5,258 | 484 |
| 9 | prompt-cache-anthropic | anthropic / claude-sonnet-4-6 | 2 | 4 | 4 | 1,328 | 740 |
| 10 | compaction-fires | anthropic / claude-sonnet-4-6 + claude-haiku-4-5 | 1 | 3 | 2 | 733 | 159 |
| 11 | compaction-idempotency | anthropic / claude-sonnet-4-6 | 1 | 2 | 2 | 531 | 26 |

Every token figure above is the `metadata.usage` object of the one call in each spec that returns an HTTP response to the caller, the primary chat completion answering the documented prompt. Notes per row where the raw figure hides something:

- Spec 3 ran five times back to back, so its row carries 5 prompts, not 1. Its token figure is the sum of those five clean executions (233 input tokens each, 1,165 total). The 2026-09-03 pass recorded 1 prompt / 2 chat calls / 2 embedding calls on this row while summing five runs' tokens into it, which was internally inconsistent and understated the suite's call counts by eight chat calls and eight embedding calls. The spec also failed once with an intermittent 422 `Failed to route PDF page` error before the fix landed. That failed attempt is excluded from the token figure, and its own retry (inside the fixed code) is not double-counted either, since only the response actually returned to Bruno carries a `metadata.usage` block. It did still fire one embedding call before it failed, counted separately under [Embedding calls the run records never captured](#embedding-calls-the-run-records-never-captured).
- Spec 3's 233 reported input tokens per run do not include the parsed PDF. The document travels inside the user message (see the embedding subsection below), and five pages of it measure roughly 3,000 tokens on their own, so MiniMax's reported `promptTokens` is clearly not counting the `<document_context>` block. Since MiniMax is excluded from money, this does not move any figure in this document, but it means the 1,165 is a report of what the provider chose to count, not a measurement of what was sent.
- Spec 4's and spec 8's and spec 9's figures are each the sum of two calls (one per documented prompt), not one.
- Spec 8's call 2 served 2,560 of its 2,796 input tokens from OpenAI's own prefix cache. Call 1 was a clean miss (0 cached).
- Spec 9's call 1 wrote 3,744 tokens to Anthropic's ephemeral cache (`cache_creation_input_tokens`), and call 2 read that same 3,744-token block back (`cache_read_input_tokens`). The 1,328-token input figure above is the non-cached portion of both calls combined.
- Spec 10's 733 input figure is a sum across two different models, not one call. Its [run record](../apps/ascend-agent/e2e/testing/runs/2026-09-03T19-16-18_10-compaction-fires-tasks.md) splits it as 618 for call 1 (claude-sonnet-4-6, the documented prompt, which also read the same 3,744-token cache entry spec 9 wrote) plus 115 for call 2 (claude-haiku-4-5, the server-side compaction summary, recovered from a log line rather than a response body, see [Findings](#findings)). The 2026-09-03 pass claimed the 733 covered call 1 alone, which contradicted both the run record and its own arithmetic further down the page. The 159 output figure is call 1 only. Call 2's output token count is not logged anywhere in this build and is not counted as zero, it is approximated in the cost section below.
- Spec 11 read the same 3,744-token cache entry again and additionally wrote 4 new cache tokens, too small to move any total in this document by a full cent.

None of the embedding calls, none of the 15 async memory-extraction chat calls (one per documented prompt, fired unconditionally per [Findings](#findings)), and spec 10's compaction call return a usage object the sweep could observe.

Totals: 15 documented prompts, 31 chat calls (15 primary plus 15 async extractors plus spec 10's compaction call), 31 embedding calls. Of those, 15 primary chat calls plus the one compaction call return the measurable token figures above: 19,350 input tokens and 5,774 output tokens summed across the eight rows, with the caveat that the spec 10 row mixes two models and the spec 3 row reports less than it sent.

#### Embedding calls the run records never captured

The 2026-09-03 pass counted only AscendMemory's own 18 embedding calls and treated the agent's embeddings as unobservable and therefore uncounted. They are unobservable, but they are not few, and the arithmetic below is derived from the code path rather than from a usage object. Every figure in this subsection is an estimate.

[AscendChatService.prompt](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L45-L79) fires two embeddings per documented prompt, unconditionally. The first is the semantic-memory search inside [ChatContextAssembler.fetchSemanticMemory](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/ChatContextAssembler.java#L74-L81), whose query is the raw user prompt. The second is the Qdrant similarity search inside [RagRetrievalService.retrieve](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/rag/RagRetrievalService.java#L59-L112), and that one is the expensive case: [ChatContextAssembler.buildUserMessage](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/ChatContextAssembler.java#L55-L71) appends the parsed document to `userPrompt` before passing it as the retrieval query, so a prompt carrying an attached document embeds the prompt plus the entire parsed document, not the prompt alone.

| Source | Calls | Query content | Estimated tokens per call | Estimated tokens |
| :--- | ---: | :--- | ---: | ---: |
| Semantic-memory search, 15 documented prompts | 15 | Raw user prompt, 7 to 20 words in every Bruno request file | ~15 | ~225 |
| RAG retrieval, 10 prompts with no attached document | 10 | Same raw user prompt | ~15 | ~150 |
| RAG retrieval, spec 3's 5 summarization prompts | 5 | Prompt plus the whole parsed `argent-saga-chronicle.pdf` | ~3,000 | ~15,000 |
| Semantic-memory search, spec 3's one failed attempt | 1 | Raw user prompt. The 422 fired inside `processDocument`, which runs after the memory search and before RAG retrieval, so this attempt made one embedding call and not two | ~15 | ~15 |
| AscendMemory's own specs | 18 | Six short fixture sentences, see the AscendMemory table below | 7 to 10 | 126 to 180 |

The ~3,000-token figure for the parsed PDF is measured, not guessed: decompressing the file's five content streams and counting glyphs gives 11,513 characters of body text across 5 pages, which at four characters per token is roughly 2,880 tokens, rounded up to allow for the markdown structure Docling adds. The fixture is [`apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf`](../apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf).

Estimated total: 49 embedding calls carrying roughly 15,600 tokens, of which one spec, run five times, accounts for about 96 percent of the volume.

#### ascend-audio-scribe (3 of 5 specs)

Each paid spec makes exactly one transcription call. Free: spec 1 (invalid input, rejected before any provider call) and spec 4 (MCP `tools/list`, a protocol probe with no provider call).

| Spec | Name | Provider | Calls | Duration (measured) | Input tokens | Output tokens |
| :--- | :--- | :--- | ---: | ---: | :--- | :--- |
| 2 | transcribe-openai | OpenAI Whisper (`whisper-1`) | 1 | 9.48 s (0.158 min) | not applicable, billed by audio duration | not applicable, billed by audio duration |
| 3 | transcribe-hf | Hugging Face Inference (`whisper-large-v3`) | 1 | 9.48 s (0.158 min) | not applicable, billed by audio duration | not applicable, billed by audio duration |
| 5 | mcp-transcribe | OpenAI Whisper (via MCP tool) | 1 | not re-measured in this sweep | not applicable, billed by audio duration | not applicable, billed by audio duration |

Both duration figures come from `ffprobe` against the shared fixture, [`apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav`](../apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav), read during the [transcribe-openai run](../apps/ascend-audio-scribe/e2e/testing/runs/2026-09-03T19-27-52_2-transcribe-openai-tasks.md). Neither provider returned a usage object for either call, which is expected: Whisper transcription is billed by audio minute, not by token, and the ascend-audio-scribe REST endpoint returns only the flat transcript text, not the raw provider response. Spec 5 (mcp-transcribe) makes a third structural paid call on the same fixture through the same OpenAI backend, but the 2026-09-03T19-27-52 sweep did not include it. It was last exercised earlier the same day at [17:06 UTC](../apps/ascend-audio-scribe/e2e/testing/runs/2026-09-03T17-06-00_5-mcp-transcribe-tasks.md), also against `meeting-clip.wav`. If it ran at the same duration, it would add another 0.158 minutes at the OpenAI rate. This document does not add it to the priced total below, since it was not part of the final measured pass.

The fixture itself carries a defect: it is documented in the ascend-audio-scribe e2e suite as a five-second mono WAV but is actually a 9.48-second LAME-encoded MP3 elementary stream wearing a `.wav` filename (see [Non-cost defects](#non-cost-defects-the-sweep-also-found)). The 0.158-minute duration used below is the real, measured one.

Totals: 3 transcription calls structurally, 2 against OpenAI (priced at 0.006 $/minute) and 1 against Hugging Face (priced by compute time, approximated in the cost section below). The cost section prices the 2 calls the final sweep actually measured, spec 2 against OpenAI and spec 3 against Hugging Face, and leaves spec 5 out because it was not part of that pass.

#### AscendMemory (4 of 6 specs)

Every insert and every search issues one embedding call against mem0's configured embedding backend, never a chat call ([compose.yaml:168](../compose.yaml#L168) sets `MEM0_INFER_MEMORY=false`, so mem0's LLM-based fact inference is off and only the embedding path runs). Free: spec 1 (invalid input, rejected before mem0 is touched) and spec 4 (MCP `tools/list`, a protocol probe).

| Spec | Name | Embedding calls | Input tokens | Output tokens |
| :--- | :--- | ---: | :--- | :--- |
| 2 | insert-and-search | 2 | not observable, see estimate below | n/a, embedding has no output |
| 3 | wipe-user-scope | 4 | not observable, see estimate below | n/a, embedding has no output |
| 5 | mcp-insert-and-search | 2 | not observable, see estimate below | n/a, embedding has no output |
| 6 | user-isolation | 2 | not observable, see estimate below | n/a, embedding has no output |

Totals: 10 embedding calls in this first pass.

The open question the original version of this document left unresolved is now settled: the sweep's calls billed against `text-embedding-3-small`, confirming [compose.yaml:170](../compose.yaml#L170)'s `openai` alternative, not the `lmstudio` default, was the active line at run time. `mem0/embeddings/openai.py`'s `OpenAIEmbedding.embed` discards the provider's `usage` object before it reaches AscendMemory's own response, confirmed by reading that file inside the running container during the [insert-and-search run](../apps/ascend-memory/e2e/testing/runs/2026-09-03T19-19-53_2-insert-and-search-tasks.md#L44-L46), so none of the calls in the table above have a directly observed token count. Every embedded string is one of six short fixture sentences (for example "My favourite city is Reykjavik"), estimated at roughly seven to ten tokens each. This is an estimate, not a measurement, one of the three the cost section below isolates so the verifiable total stays recoverable.

A fix for a double-encoded query-string defect (see [Non-cost defects](#non-cost-defects-the-sweep-also-found)) triggered a second pass: specs 1, 2, 3, and 6 were re-run against corrected request files at [`apps/ascend-memory/e2e/testing/runs/2026-09-03T19-46-17_*`](../apps/ascend-memory/e2e/testing/runs/). Spec 1 (invalid-input) makes no embedding call at all, validation rejects the request before mem0 is reached, so the four re-run specs actually add 8 embedding calls, not 4: 2 from spec 2, 4 from spec 3, 2 from spec 6, read directly from each re-run's own Result summary. Ten from the first pass plus eight from the re-run gives 18 embedding calls total against `text-embedding-3-small`, all in the same seven-to-ten-token band. This document uses 18 in the cost section below, not the smaller figure the day's own running total suggested, because the four re-run specs are not the same thing as four re-run calls.

#### ascend-ocr, ascend-web-hunter, ascend-weather-mcp (29 specs, all free)

Every spec in these three modules drives only local or self-hosted services (the on-image PaddleOCR engine, SearXNG plus curl_cffi/FlareSolverr/Playwright, and the Open-Meteo API respectively) and makes no call to any priced LLM or embedding provider. 12 ascend-ocr specs, 10 ascend-web-hunter specs, 7 ascend-weather-mcp specs. See [apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md), [apps/ascend-web-hunter/e2e/README.md](../apps/ascend-web-hunter/e2e/README.md), and [apps/ascend-weather-mcp/e2e/README.md](../apps/ascend-weather-mcp/e2e/README.md) for the full per-spec list. No per-row cost table is needed here, since every cell would read zero. "All free" describes dollar cost only: ascend-web-hunter's own spec 10 (`session/establish`) makes no priced call either, but launches a real headful browser held by a background monitor for up to 10 minutes, a wall-clock and resource cost the zero in this heading does not capture — see [apps/ascend-web-hunter/e2e/testing/10-session-establish-test.md](../apps/ascend-web-hunter/e2e/testing/10-session-establish-test.md).

---

### How to recalculate

1. Open [Prices](#prices) and replace any rate that changed, keeping the source URL and read date on the row.
2. Leave every table in [Usage](#usage) untouched. Call counts do not change when a price changes.
3. For each paid row, multiply its input and output token counts by the matching price-table rate, splitting cached from uncached input where the spec exercises prompt caching (specs 8, 9, 10, and 11), and sum across rows.
4. For ascend-audio-scribe rows, multiply audio minutes by the $/minute rate instead of a token rate. The Hugging Face row is not a per-minute rate at all, see step 6.
5. Skip every MiniMax row. The subscription makes them free at the margin, see the top of this document.
6. Carry the three approximations separately so the verifiable figure stays recoverable: spec 10's unlogged compaction output, the Hugging Face compute-time conversion, and the embedding token estimate. The cost section below keeps them in their own subsection for exactly this reason.
7. Treat Gemini as an open cost rather than a zero if a future spec routes to it. Nothing in today's suite does.

---


### Cost of the 2026-09-03 sweep

This is [How to recalculate](#how-to-recalculate) worked all the way through against the measured [Usage](#usage) figures and the rates in [Prices](#prices) as they stood on 2026-09-04. Unlike the 2026-09-03 version of this section, nothing is left as an open gap and nothing is presented as an illustration standing in for a model it is not. Three figures rest on an approximation, and all three are isolated in their own subsection so the verifiable total stays recoverable by subtraction.

Every product below is written out in full so it can be redone by hand after a price change. Rates are dollars per million tokens unless the line says otherwise.

#### OpenAI

gpt-5.1, ascend-ai-agent spec 2, image-description. Rates 1.25 input, 10.00 output. No cached tokens were reported for this call.

- Input: 3,098 x 1.25 / 1,000,000 = 0.0038725
- Output: 644 x 10.00 / 1,000,000 = 0.0064400
- Spec 2 total = 0.0103125

gpt-4o, ascend-ai-agent spec 8, prompt-cache-openai, two calls. Rates 2.50 uncached input, 1.25 cached input, 10.00 output. Of the 5,258 input tokens across both calls, 2,560 were served from OpenAI's prefix cache on call 2, leaving 2,698 billed at the standard rate.

- Uncached input: 2,698 x 2.50 / 1,000,000 = 0.0067450
- Cached input: 2,560 x 1.25 / 1,000,000 = 0.0032000
- Output: 484 x 10.00 / 1,000,000 = 0.0048400
- Spec 8 total = 0.0147850

The 2026-09-03 pass carried this row at 0.0180 because it could not confirm a cached-input rate and so assumed no discount at all. The confirmed 1.25 rate takes 0.0032 off, and 0.0147850 is the real figure, not a ceiling.

Whisper `whisper-1`, ascend-audio-scribe spec 2, transcribe-openai. Rate 0.006 $ per minute of audio, against the measured 9.48-second fixture.

- 0.158 min x 0.006 = 0.000948

ascend-audio-scribe spec 5, mcp-transcribe, is a structurally identical third Whisper call on the same fixture but was not part of the 19:27:52 pass, so it stays out of this total. Adding it would cost another 0.000948.

text-embedding-3-small. Rate 0.02 input. Volume from [Embedding calls the run records never captured](#embedding-calls-the-run-records-never-captured), roughly 15,600 tokens across 49 calls. This is an estimate.

- 15,600 x 0.02 / 1,000,000 = 0.000312

OpenAI subtotal = 0.0103125 + 0.0147850 + 0.000948 + 0.000312 = 0.0263575

#### Anthropic

Claude Sonnet 4.6. Rates 3.00 input, 15.00 output, 3.75 cache write, 0.30 cache read.

Spec 9, prompt-cache-anthropic, call 1:

- Input: 427 x 3.00 / 1,000,000 = 0.001281
- Output: 370 x 15.00 / 1,000,000 = 0.005550
- Cache write: 3,744 x 3.75 / 1,000,000 = 0.014040
- Call 1 = 0.020871

Spec 9, call 2:

- Input: 901 x 3.00 / 1,000,000 = 0.002703
- Output: 370 x 15.00 / 1,000,000 = 0.005550
- Cache read: 3,744 x 0.30 / 1,000,000 = 0.0011232
- Call 2 = 0.0093762

Spec 10, compaction-fires, call 1 (the documented prompt, 618 of the row's 733 input tokens, the other 115 belonging to the Haiku call below):

- Input: 618 x 3.00 / 1,000,000 = 0.001854
- Output: 159 x 15.00 / 1,000,000 = 0.002385
- Cache read: 3,744 x 0.30 / 1,000,000 = 0.0011232
- Spec 10 call 1 = 0.0053622

Spec 11, compaction-idempotency:

- Input: 531 x 3.00 / 1,000,000 = 0.001593
- Output: 26 x 15.00 / 1,000,000 = 0.000390
- Cache read: 3,744 x 0.30 / 1,000,000 = 0.0011232
- Cache write: 4 x 3.75 / 1,000,000 = 0.000015
- Spec 11 = 0.0031212

Sonnet 4.6 total = 0.020871 + 0.0093762 + 0.0053622 + 0.0031212 = 0.0387306

Claude Haiku 4.5, spec 10's server-side compaction call. Rates 1.00 input, 5.00 output.

- Input: 115 x 1.00 / 1,000,000 = 0.000115
- Output: not reported by the service at any point. `AnthropicPromptCacheStrategy` logs `prompt_tokens`, `cache_read_tokens` and `cache_creation_tokens` and nothing else, and the call never returns an HTTP response to the caller, so no run record in the sweep carries it. Approximated at the configured ceiling instead: [application.yaml:127](../apps/ascend-agent/src/main/resources/application.yaml#L127) sets `max-summary-tokens: 800`, and the service rejects any summary above it, so 800 is the largest output this call could legally have produced. 800 x 5.00 / 1,000,000 = 0.004000
- Haiku 4.5 total = 0.004115, of which 0.004000 is an approximated ceiling and only 0.000115 is measured

Anthropic subtotal = 0.0387306 + 0.004115 = 0.0428456

#### Hugging Face

whisper-large-v3 via the `hf-inference` provider, ascend-audio-scribe spec 3, transcribe-hf. There is no per-minute rate and no flat rate, so the audio duration is not the billing unit. Compute time is, at the underlying hardware's per-second price.

The only compute-time figure the sweep captured is the client-observed 3,078 ms round trip recorded in the [spec 3 run record](../apps/ascend-audio-scribe/e2e/testing/runs/2026-09-03T19-27-52_3-transcribe-hf-tasks.md). That is wall clock through ascend-audio-scribe and the network, so the compute seconds Hugging Face actually billed are a subset of it. The only hardware rate the pricing page publishes is the 0.00012 $ per GPU second in its own worked example.

- 3.078 s x 0.00012 = 0.000369

Treat that as an upper bound rather than a quote. Two things push the real figure lower: billed compute excludes the network and ascend-audio-scribe's own overhead inside the 3,078 ms, and the pricing page notes `hf-inference` runs mostly on CPU, which is cheaper per second than the GPU rate the example uses. A 9.48-second clip decoded by a large ASR model in roughly three seconds of wall clock is not a workload that can plausibly cost more than a twentieth of a cent at any published rate.

Hugging Face subtotal = 0.000369, entirely approximated.

#### MiniMax

Zero, on purpose. Specs 1, 3, and 4 measured 8,402 input and 3,721 output tokens across 8 documented prompts, and none of it is multiplied by anything. The account behind `MiniMax-M2.7` is a flat subscription rather than metered per-token billing, so re-running those three specs changes the bill by nothing. The tokens stay recorded in [Usage](#usage) because they are a fact about the suite, not because they are a cost.

#### The two totals

| Provider | Verifiable | Approximated | Total |
| :--- | ---: | ---: | ---: |
| OpenAI | 0.0260455 | 0.000312 | 0.0263575 |
| Anthropic | 0.0388456 | 0.004000 | 0.0428456 |
| Hugging Face | 0.000000 | 0.000369 | 0.000369 |
| MiniMax | 0.000000 | 0.000000 | 0.000000 |
| Sweep | 0.0648911 | 0.0046810 | 0.0695721 |

Full total, approximations included: 0.0696 $, call it seven cents.

Verifiable-only total: 0.0649 $, call it six and a half cents.

The three approximations and what they are worth:

| Approximation | Value | Why it cannot be measured | Direction of the error |
| :--- | ---: | :--- | :--- |
| Spec 10's Haiku 4.5 compaction output, priced at the 800-token configured cap | 0.004000 | The call never returns to the caller and this build logs no completion-token count for it | Ceiling. A real compaction summary of 20 turns will land well under 800 tokens, so the true figure is lower, plausibly by half or more |
| Embedding tokens across 49 calls | 0.000312 | `OpenAIEmbedding.embed` inside mem0 discards the provider's usage object, and the agent's own two-per-prompt embeddings never surface one either | Two-sided, and dominated by the ~3,000-token estimate for the parsed PDF, which was measured from the file rather than guessed |
| Hugging Face compute seconds | 0.000369 | No flat rate exists, and the billed compute time is not observable from outside | Ceiling. Wall clock overstates billed compute, and the GPU rate overstates a CPU-served call |

So 93 percent of the sweep's cost is anchored to a published rate against a measured token count, and the whole approximated remainder is 0.0047 $, under half a cent. The single largest piece of that remainder is one unlogged output-token count on one compaction call, which a one-line logging change would convert into a measurement.

#### Where the money actually went

Anthropic is 62 percent of the total on 4 of the 15 documented prompts, and the largest single line item in the entire sweep is spec 9 call 1's 3,744-token cache write at 0.014040, which by itself is 20 percent of the sweep. That is the expected shape: a cache write costs 1.25 times the input rate and only pays for itself if enough later calls read it. Here three later calls did read it back (spec 9 call 2, spec 10, spec 11) at 0.0011232 each. Counting the write and the three reads together, the cached path cost 0.014040 + 0.0033696 = 0.0174096. Sending that same 3,744-token prefix as ordinary input on all four calls would have cost 4 x 3,744 x 3.00 / 1,000,000 = 0.044928. Caching paid for itself roughly two and a half times over, which is worth knowing before anyone reads the 0.014040 line as waste.

The embedding line is worth noting for a different reason. At 0.000312 it is financially irrelevant, but it is roughly a hundred times what the 2026-09-03 pass recorded, because that pass counted only AscendMemory's own 18 calls and missed the 31 the agent fires on its own account. The reason the figure is still tiny is the rate, not the volume: 15,600 tokens is more than the entire sweep's measured Anthropic input, and it costs a third of a thousandth of a dollar.

---

### Findings

Three defects surfaced while tracing how a single documented prompt turns into billed calls. All three change what the Usage table above actually means, so they are recorded here rather than left as a footnote.

#### Every documented prompt costs more than its spec's Run section suggests

[AscendChatService.prompt](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L45-L79) runs four external calls for what a spec's Run section shows as one prompt: `contextAssembler.buildSystemMessages` at line 58 calls [ChatContextAssembler.fetchSemanticMemory](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/ChatContextAssembler.java#L74-L81), an unconditional AscendMemory search that embeds the query. `contextAssembler.buildUserMessage` at line 59 calls [RagRetrievalService.retrieve](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/rag/RagRetrievalService.java#L59-L112), which runs a Qdrant similarity search (line 83) whenever RAG is enabled, which it is by default (`app.rag.enabled: true`, [application.yaml:271](../apps/ascend-agent/src/main/resources/application.yaml#L271)), regardless of whether the prompt has anything to do with retrieval. `chatExecutor.execute` at line 63 is the main chat call. `semanticMemoryExtractor.extract` at line 69 fires a second, asynchronous chat call. One documented prompt is therefore two paid chat calls plus two paid embedding calls, which is exactly the multiplier applied throughout the ascend-ai-agent table above.

The second embedding is larger than it looks. `buildUserMessage` appends the parsed document to `userPrompt` before handing it to `RagRetrievalService.retrieve`, so when a prompt carries an attached file, the retrieval query embedded against Qdrant is the prompt plus the entire parsed document, not the prompt alone. On the summarization spec that turns a fifteen-token query into a roughly three-thousand-token one, and that spec ran five times in this sweep. It is cheap at today's embedding rate, see [Embedding calls the run records never captured](#embedding-calls-the-run-records-never-captured), but it is worth knowing that the retrieval query scales with document size, since a similarity search against the full text of the document is also unlikely to retrieve anything useful.

The 2026-09-03 sweep confirms this in practice, not only in code. The fifteen documented prompts across the eight measured specs in [Usage](#usage) each produce a visible, priceable `metadata.usage` object for exactly one call, the primary chat completion. None of the fifteen async extractor calls those same fifteen prompts fire, none of the 31 embedding calls, and spec 10's compaction call return a usage object the e2e harness can see. Spec 10 is the sharpest case: its compaction call to claude-haiku-4-5 never returns an HTTP response to the caller at all, and its 115-token input count was only recoverable by reading `docker logs ascend-ai-agent` for the `AnthropicPromptCacheStrategy` log line during [that run](../apps/ascend-agent/e2e/testing/runs/2026-09-03T19-16-18_10-compaction-fires-tasks.md), with its output token count never surfacing anywhere in this build. A specification's Run section shows one HTTP request per documented prompt, and the sweep shows at least two billed calls behind every one of them, with the second, or the third for spec 10, invisible to anything the harness can observe directly.

#### The memory extractor bills at the caller's model, not the configured cheap one

[SemanticMemoryExtractor.resolveExtractionModel](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java#L148-L155) returns the caller-supplied model whenever one was supplied, and only falls back to the provider's configured `memory-extraction-model` when the caller passed none:

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

[AscendChatService.java:69](../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/AscendChatService.java#L69) calls `semanticMemoryExtractor.extract(userId, prompt, provider, model, activeEmbeddingProvider)`, passing through the same `model` the caller requested for the main chat call. Since every ascend-ai-agent e2e spec, and the `/api/v1/ai/prompt` demo in the root [README.md](../README.md), sends an explicit `model` field, the fallback to the cheap configured model essentially never fires in practice. The clearest priced example is spec 8: it requests `provider=openai`, `model=gpt-4o`, so its extraction call also runs on gpt-4o (2.50 / 10.00 $ per million tokens) instead of the configured gpt-4o-mini (0.15 / 0.60 $ per million tokens), roughly 16.7 times the rate on both input and output for a call whose entire job is picking short facts out of one message. Specs 9, 10, and 11 compound this with `claude-sonnet-4-6` at 3.00 / 15.00 $ per million tokens, five times the rate of the `claude-haiku-4-5` the same provider is configured to compact with. Specs 1, 3, and 4 are unaffected in dollar terms only because minimax has no separate cheap tier: [application.yaml:231](../apps/ascend-agent/src/main/resources/application.yaml#L231) configures `MiniMax-M2.7` as both the chat default and the memory-extraction model for that provider, so the caller-supplied model and the fallback happen to be identical.

#### The configured Anthropic extraction model is retired, and the first defect is the only reason nobody has hit it

[application.yaml:220](../apps/ascend-agent/src/main/resources/application.yaml#L220) configures `claude-3-5-haiku-20241022` as the anthropic provider's memory-extraction model. Per the Anthropic pricing page cited in [Prices](#prices), that exact model is Claude Haiku 3.5, retired on the first-party Anthropic API and available only through Amazon Bedrock and Google Cloud. A call to it via `api.anthropic.com` (the base URL configured at [application.yaml:214](../apps/ascend-agent/src/main/resources/application.yaml#L214)) would fail. This has not surfaced as a production incident because the first defect above means the fallback path that would reach this model almost never executes. Any request that omits the `model` field while using `provider=anthropic` would trigger it today.

---

### Non-cost defects the sweep also found

None of these affect the arithmetic above. They are recorded here because the run records that hold them are the reason this document could redo the sweep's math at all instead of guessing, and a future reader deciding whether to keep archiving run records should know what else they have paid for.

- A specification asserted on a log line instead of an observable outcome.
- Five assertions read response fields that do not exist in the payload they were checking.
- Two specifications named response fields the service never actually returns.
- Four request files sent double-encoded query text: `search-reykjavik.yml`, `search-alpha.yml`, `search-beta.yml`, and `search-isolation-user-b.yml` under [docs/api/request/AscendAI/memory/testing/](../docs/api/request/AscendAI/memory/testing/), each manually percent-encoding a value that Bruno's own `encodeUrl: true` setting then encoded a second time, corrected and re-run at [`apps/ascend-memory/e2e/testing/runs/2026-09-03T19-46-17_*`](../apps/ascend-memory/e2e/testing/runs/).
- Specifications instructed the runner to print API keys into the transcript: ascend-audio-scribe's `OPENAI_API_KEY` and `HF_TOKEN` prerequisite checks in its OpenAI and Hugging Face transcription specs, both substituted for a non-printing presence check instead.
- A fixture documented as a five-second mono WAV turned out to be a 9.48-second MP3 elementary stream wearing a `.wav` filename: [`apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav`](../apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav).
- A check asserted a response-time threshold as proof a backend call never fired, but container overhead alone already sits above that threshold on every request regardless of truth. AscendMemory's invalid-input spec was corrected to a structural proof plus an observable Qdrant point-count check instead.
- A request file was weaker than its siblings, missing an assertion the equivalent requests in the same spec all carried.
- A document-conversion failure, an intermittent 422 `Failed to route PDF page` error on the ascend-ai-agent summarization spec, traced back to a supervisor process killing its own worker rather than to the document or the model. Fixed with a retry/fan-out and confirmed clean across [five consecutive re-runs](../apps/ascend-agent/e2e/testing/runs/2026-09-03T20-21-27Z_3-summarization-tasks.md).

---

### Documentation

Related material:

- [apps/ascend-agent/e2e/README.md](../apps/ascend-agent/e2e/README.md) for the spec format, execution groups, and where run records land.
- [apps/ascend-agent/src/main/resources/application.yaml](../apps/ascend-agent/src/main/resources/application.yaml) for the live provider and model configuration this document was checked against.
- [AGENTS.md](../AGENTS.md) and [apps/ascend-agent/AGENTS.md](../apps/ascend-agent/AGENTS.md) for the platform and module overviews.
