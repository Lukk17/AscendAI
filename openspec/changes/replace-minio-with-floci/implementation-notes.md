# Implementation notes

Evidence gathered while executing this change. Tasks that ask for a measurement record it here.

---

### Task 1.1 and 1.5: Floci S3 contract probe

Run on 2026-09-03 against the live Floci at `http://localhost:9070` (`floci/floci:2.0.1`, edition `community`), S3 path style, no authentication and no request signing on any call. The scratch bucket was `floci-contract-probe`. `local-dev-bucket`, which belongs to another repository's `local-dev` compose project, was never written to and never deleted.

| # | Command | Status | What came back |
| :-- | :-- | :-- | :-- |
| 1 | `curl -sS http://localhost:9070/_floci/health` | 200 | JSON with `"s3":"running"`, `"version":"2.0.1"`, `"edition":"community"` |
| 2 | `curl -sS http://localhost:9070/` | 200 | `ListAllMyBucketsResult` naming one bucket, `local-dev-bucket`, created `2026-09-02T20:19:16Z` |
| 3 | `curl -sS -X PUT http://localhost:9070/floci-contract-probe` | 200 | Empty body, bucket created |
| 4 | `curl -sS -X PUT --data-binary '@probe.txt' http://localhost:9070/floci-contract-probe/probe.txt` | 200 | Empty body, 38-byte object stored |
| 5 | `curl -sS http://localhost:9070/floci-contract-probe/probe.txt` | 200 | Byte-identical to the uploaded file |
| 6 | `curl -sS "http://localhost:9070/floci-contract-probe?list-type=2"` | 200 | `ListBucketResult` with `KeyCount` 1 and `<Contents><Key>probe.txt</Key>` |
| 7 | `curl -sS "http://localhost:9070/floci-contract-probe/does-not-exist.txt"` | 404 | `<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message><RequestId>...</RequestId></Error>` |
| 8 | `curl -sS -X DELETE http://localhost:9070/floci-contract-probe/probe.txt` | 204 | Empty body |
| 9 | `curl -sS -X DELETE http://localhost:9070/floci-contract-probe` | 204 | Empty body, bucket removed |
| 10 | `curl -sS "http://localhost:9070/floci-contract-probe?list-type=2"` | 404 | `<Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist.</Message></Error>` |
| 11 | `curl -sS -X PUT http://localhost:9070/floci-contract-probe` (repeat of an existing bucket) | 200 | Empty body, no `409 BucketAlreadyOwnedByYou` |
| 12 | `curl -sS -X PUT --data-binary '@probe.txt' "http://localhost:9070/floci-contract-probe/documents/probe.txt"` | 200 | Empty body, key stored under a prefix |
| 13 | `curl -sS "http://localhost:9070/floci-contract-probe?list-type=2&prefix=documents/"` | 200 | `ListBucketResult` with `<Prefix>documents/</Prefix>` and `<Contents><Key>documents/probe.txt</Key>` |
| 14 | `curl -sS -X DELETE "http://localhost:9070/floci-contract-probe/documents/probe.txt"` | 204 | Empty body |
| 15 | `curl -sS -X DELETE http://localhost:9070/floci-contract-probe` | 204 | Empty body |
| 16 | `curl -sS http://localhost:9070/` | 200 | `ListAllMyBucketsResult` naming only `local-dev-bucket`, creation date still `2026-09-02T20:19:16Z` |
| 17 | `curl -sS "http://localhost:9070/local-dev-bucket?list-type=2"` | 200 | Still holds `first.txt` and `second.txt`, both `LastModified` `2026-09-02T20:19:22Z`, unchanged ETags |

Conclusions that the rest of the change rests on.

The full unauthenticated verb set the runbook rewrite needs is available: create bucket, put object, get object, list, delete object, delete bucket. Every `mc` to `curl` row in design.md decision 2 therefore stands, including the bucket-level delete that decision 5 keeps. The contingency seeding path recorded in decision 2 is not needed.

One deviation from real S3 is worth knowing before a runbook asserts on it. Repeating a bucket `PUT` returns 200, not `409 BucketAlreadyOwnedByYou`, so a create-if-absent step is idempotent on a plain 200 and treating 409 as success costs nothing but never fires here.

Error responses are proper S3 XML with a matching HTTP status, `NoSuchKey` with 404 for a missing object and `NoSuchBucket` with 404 for a missing bucket. A runbook can distinguish "the object is absent, which is the expected post-cleanup state" from "the endpoint is broken" by the `<Code>` element rather than by status alone.

The listing element path for group 7 assertions is `ListBucketResult` then `Contents` then `Key`, in the namespace `http://s3.amazonaws.com/doc/2006-03-01/`. `?prefix=` filters and the response echoes it back in `<Prefix>`, so a prefix-scoped assertion can check both the filter it asked for and the keys it got.

Cleanup is complete. `floci-contract-probe` and both of its objects no longer exist, and `local-dev-bucket` is present and untouched.

---

### Task 3.10: the before-and-after timing comparison cannot be reconstructed

No wall-clock baseline of `./gradlew integrationTest` was captured against the MinIO Testcontainer before the swap landed, and the MinIO container is gone from the machine, so the comparison the task asks for has no "before" half and cannot be recovered. The task stays unticked rather than being marked done on half the evidence.

What was measured instead is the post-swap cost, from two clean timing runs of the full `integrationTest` task against `floci/floci:2.0.1`:

| Run | Duration |
| :-- | :-- |
| 1 | 175 seconds |
| 2 | 167 seconds |

Those two numbers are the baseline a future Floci upgrade should be compared against.

---

### Integration-suite stability across seven full runs

Seven full `integrationTest` runs were executed while this change was implemented. In five of them one Testcontainers-backed class failed with connection timeouts, but which class it was varied from run to run. In some runs Postgres, Redis, Qdrant and the object store all timed out together, and none of those first three were touched by this change. `IngestionEndToEndIT`, the heaviest object-store user and therefore the class most exposed to a Floci behaviour gap, never failed. Every targeted single-class run passed cleanly in isolation.

The conclusion drawn is pre-existing Docker Desktop network pressure on a host running more than ten other containers concurrently, not a defect in the Floci swap. Ryuk cleaned up after every run and no orphaned container was left behind.

---

### `McpStartupToleranceIT` was a pre-existing failure, now fixed in the test layer

`McpStartupToleranceIT.registry_WhenMcpServerUnreachable_RecordsFailedStatus` used to fail deterministically at line 61, in every full-suite run and in isolation. It had no connection to object storage and sat in a file this change never touched, but the root cause has since been found and corrected.

Two stacked test defects were responsible. The first was a `@DynamicPropertySource` key collision on `spring.ai.mcp.client.enabled` between `TestcontainersBase` and the test's own override, which meant the test's intended override never took effect. The second was a connections map that merges rather than replaces, so the three real MCP connections stayed live instead of being swapped out for the unreachable one the test needed. Both defects were fixed in the test layer, with no production code change. The class has since passed four consecutive isolated runs.

Task 10.2 stays unticked regardless. The fix was verified through isolated runs of `McpStartupToleranceIT` itself, not through a full re-run of `./gradlew integrationTest`, so the suite-wide green result the task asks for has not been re-confirmed since the fix landed.

---

### Task 10: final verification results

Run on 2026-09-03 as the closing pass, after every implementer had finished.

| Task | Command | Result |
| :-- | :-- | :-- |
| 10.1 | `rg -il minio . --glob '!**/runs/**'` | 62 files, every one on the expected-remainder list. Breakdown below. |
| 10.2 | `./gradlew build` | BUILD SUCCESSFUL. The `integrationTest` half was not re-run, see the note above. |
| 10.2 | `./gradlew cleanTest test` | BUILD SUCCESSFUL, 93 classes, 700 tests, 0 skipped, 0 failures, 0 errors. |
| 10.3 | `pytest` in `AudioScribe/` | 267 passed, 100.00% coverage against a 100% gate. |
| 10.3 | `pytest` in `PaddleOCR/` | 171 passed, 4 skipped, 100.00% coverage against a 100% gate. |

Supporting checks run alongside them:

| Check | Command | Result |
| :-- | :-- | :-- |
| Compile from scratch | `./gradlew compileJava compileTestJava --rerun-tasks` | BUILD SUCCESSFUL in 23 seconds. Two pre-existing notes only, a deprecated API in `FilteredToolCallbackProvider.java` and an unchecked operation in `SemanticMemoryClientTest.java`. |
| Dependency removal, task 3.3 | `./gradlew dependencies --configuration testRuntimeClasspath` | Zero lines matching `minio`. The remaining Testcontainers modules are `testcontainers`, `junit-jupiter`, `postgresql` and `qdrant`. |
| Spec validation | `openspec validate replace-minio-with-floci --strict` | Valid. |
| Spec validation | `openspec validate harden-cloud-deployment --strict` | Valid. |
| Spec validation | `openspec validate add-observability --strict` | Valid. |
| Spec validation | `openspec validate ai-driven-e2e-runner --strict` | Valid. |
| Spec validation | `openspec validate update-docs-and-architecture --strict` | Valid. |
| Removed tooling | repository sweep for `docker exec` followed by `minio` | Nothing outside this change's own artifacts. |
| Removed tooling | repository sweep for the `mc` client | Nothing outside this change's own artifacts and the not-yet-archived requirement in `openspec/specs/ai-driven-e2e-runner/spec.md` that this change removes by delta. |
| Removed tooling | repository sweep for `aws s3` | One hit, the rejected-alternative sentence in this change's own design.md. |
| Stale ports | repository sweep for `:9000` and `:9001` | Nothing outside this change's own artifacts and the excluded pending changes. |
| Prometheus, static half of 5.5 | parsed `observability/prometheus/prometheus.yaml` | Jobs are `ascend-agent`, `weather-mcp`, `ascend-memory`, `audio-scribe`, `ascend-web-search`, `ascend-paddle-ocr`, `qdrant`. No `minio` job. |
| Grafana, static half of 5.5 | parsed `observability/grafana/dashboards/infrastructure.json` | Valid JSON. The panels are one `Qdrant` row and two Qdrant timeseries. No `minio` substring anywhere in the file, so no panel queries a `minio_*` metric. |
| Compose, tasks 6.1 and 6.3 | parsed `docker-compose.yaml` and `ascend-scrapper.docker-compose.yaml` | Both parse. Neither defines a `minio` or a `floci` service. `MCP_ALLOWED_HOSTS` is `host.docker.internal,localhost,127.0.0.1` at both `:67` and `:236`. |

`docker compose config` was not used for the compose and Prometheus checks. This pass was scoped read-only against a live stack it must not disturb, so both files were parsed directly instead, which answers the same question without touching a container.

Task 10.1 remainder breakdown, 62 files:

| Group | Count | Status |
| :-- | :-- | :-- |
| `openspec/changes/archive/**` | 12 | Expected, historical record. |
| The pending changes settled decision 2 leaves alone | 33 | Expected, spread across eight changes. The ninth, `update-docs-and-architecture`, no longer appears at all, because task 9.2 cleared it. |
| `openspec/changes/replace-minio-with-floci/**` | 7 | Expected. This change's own artifacts name the product they are removing. |
| `openspec/changes/add-observability/tasks.md` | 1 | Expected. One line naming this change's directory, which is a real identifier. |
| `openspec/specs/**` | 4 | Expected. Every requirement-level hit is covered by a delta in this change and is rewritten at archive time. The one line no delta can reach, the `## Purpose` at `ai-driven-e2e-runner/spec.md:5`, was edited directly by task 9.1 and now names Floci. |
| `README.md`, `AscendAgent/README.md` | 2 | Expected, the deliberate aside that the port 9071 user interface used to be the MinIO console. |
| `AscendWebSearch/src/assets/fanboy-annoyance.txt` | 1 | Expected, a third-party ad blocklist whose matches are coincidental substrings inside domain names. |
| `.agents/skills/e2e-runbooks/SKILL.md`, `openspec/schemas/e2e-runbooks/**` | 3 | Expected, generated agent-standards artifacts that settled decision 3 forbids editing. Only the two under `openspec/schemas/` appear in the default sweep, since `.agents/` is gitignored and needs an explicit no-ignore flag to surface. |

No unaccounted file remained, so this pass needed no gap-closing edit.

---

### Findings recorded rather than fixed

Four things surfaced during the final verification that are real but sit outside this change.

The local Claude Code permission allowlist at `.claude/settings.local.json` still carries three entries shaped `Bash(docker exec minio mc *)`, `Bash(docker exec minio sh -c *)` and `Bash(docker exec -i minio *)`. The file is gitignored, so it is not repository content and it does not appear in the task 10.1 sweep, but it is stale on the owner's machine and those entries now permit a command no spec issues. The documented shapes in `AscendAgent/e2e/README.md` are already correct and already Floci-shaped, and they match what the rewritten specs actually run, which is `curl -fsS http://localhost:9070/...` and `curl -fsS -X DELETE http://localhost:9070/...`. Pruning the local file is the owner's call, because it is permission configuration.

Task 6.3 asks for a grep of both compose files for `minio` or `floci` to return nothing, which task 6.2 makes impossible by requiring comments that name Floci. The substantive requirement, the `ascend-agent-containerization` scenario "No compose file defines the object store", is satisfied and was verified by parsing both files. The task's literal grep is the thing that is wrong, not the compose files.

Two other pending changes carry delta requirements that collide with this one at archive time. `add-tenant-isolation/specs/rag-source-attachments/spec.md` modifies "Presigned URLs for source documents", the same requirement this change modifies, and still pins `app.s3.endpoint=http://minio:9000`. `add-document-management-api/specs/rag-source-attachments/spec.md` modifies "`SourceFile` DTO shape", which this change also modifies. Whichever archives second overwrites the first. Settled decision 2 deliberately leaves both alone, so this is a note for whoever implements them rather than a defect here.

The link sweep across every markdown file in the repository found no broken link introduced by this change. It did find pre-existing broken links in files this change happened to touch, none of them object-store related. `AscendAgent/README.md:84` and `:87` point at `service/ChatResponseContentResolver.java` and `service/ChatExecutor.java`, which moved to `service/provider/` and `service/chat/` in an earlier package refactor. `AudioScribe/docs/architecture/decisions/ADR-001-uri-only-mcp-transport.md:64` cites a `docs/CONFIGURATION.md` that AudioScribe does not have. All eleven files under `AscendAgent/e2e/testing/templates/` link their sibling spec as `<N>-<name>-test.md` when the spec sits one directory up, which is uniform across templates this change never touched and is therefore pre-existing.

---

### What still needs the stack running

Ten tasks were unticked when this table was first written. Six of them, 1.2, 1.4, 4.3 (live half), 5.5, 6.4 and 10.6, have since been closed and their rows say so. The remaining five need something started that is currently stopped, or evidence that no longer exists.

| Task | What it needs | Why it is not done |
| :-- | :-- | :-- |
| 1.2 | The agent started with `./gradlew bootRun` against a Floci with no `knowledge-base` bucket | Closed on 2026-09-03. See "Tasks 1.2, 1.4, 5.5 and 10.6" below. |
| 1.3 | A running agent plus a full upload, ingest and prompt round trip | Closed on 2026-09-03, proven during the RAG e2e sweep. See "Task 1.3 and tasks 10.4-10.5" below. |
| 1.4 | The objects from 1.3 present in `knowledge-base` | Closed on 2026-09-03 against task 1.1's scratch-bucket record rather than against 1.3's objects, since 1.3 had not run yet at that point. Independently reconfirmed by the 1.3 sweep itself, see "Task 1.3 and tasks 10.4-10.5" below. See also "Tasks 1.2, 1.4, 5.5 and 10.6" below. |
| 3.10 | A pre-swap MinIO baseline | Unrecoverable. See the task 3.10 section above for the post-swap numbers recorded in its place. |
| 4.3, live half | The `public-audio` bucket seeded in Floci | Closed on 2026-09-03. See the section below. The rewritten URL resolves and the MCP tool returns HTTP 200, with one caveat about the key the file names. |
| 5.5 | The `prometheus` container running | Closed on 2026-09-03. See "Tasks 1.2, 1.4, 5.5 and 10.6" below. |
| 6.4 | The `ascend-paddle-ocr` container running | Closed on 2026-09-03. See the section below. `ocr_process` fetched the fixture from Floci and returned extracted text. |
| 10.2 | `McpStartupToleranceIT` fixed, or excluded | Closed. The class fix is verified both in isolation and across full-suite runs, see "Task 10.2" below. |
| 10.4 | The full stack running | Closed on 2026-09-03. See "Task 1.3 and tasks 10.4-10.5" below. |
| 10.5 | The full stack running | Closed on 2026-09-03. See "Task 1.3 and tasks 10.4-10.5" below. |
| 10.6 | The agent restarted against a Floci with no `knowledge-base` bucket | Closed on 2026-09-03. See "Tasks 1.2, 1.4, 5.5 and 10.6" below. |

---

### Tasks 6.4 and 4.3: the MCP tools fetch from Floci over the wire

Run on 2026-09-03 against the live seventeen-container `ascend-ai` stack and the Floci at `http://localhost:9070` (`floci/floci:2.0.1`, edition `community`). Both scratch buckets were created for this run and deleted afterwards.

Preconditions checked first.

| Command | Status | What came back |
| :-- | :-- | :-- |
| `curl -sS http://localhost:9070/_floci/health` | 200 | `"s3":"running"`, `"version":"2.0.1"` |
| `curl -sS http://localhost:9070/` | 200 | `local-dev-bucket` and `knowledge-base` only, no `e2e-fixtures` and no `public-audio` |
| `docker exec ascend-paddle-ocr printenv MCP_ALLOWED_HOSTS` | 0 | `host.docker.internal,localhost,127.0.0.1`, the literal `minio` entry gone |
| `docker exec audio-scribe printenv MCP_ALLOWED_HOSTS` | 0 | `host.docker.internal,localhost,127.0.0.1` |
| `curl -sS http://localhost:7022/health` | 200 | `{"status":"ok","version":"0.1.0"}` |

#### Task 6.4, PaddleOCR

| # | Command | Status | What came back |
| :-- | :-- | :-- | :-- |
| 1 | `curl -sS -X PUT http://localhost:9070/e2e-fixtures` | 200 | Bucket created |
| 2 | `curl -sS -X PUT -H "Content-Type: image/png" --data-binary "@PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png" http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png` | 200 | Object stored |
| 3 | `curl -sS "http://localhost:9070/e2e-fixtures?list-type=2&prefix=argent-saga"` | 200 | `<Key>argent-saga-chronicles-page1.png</Key>` with `<Size>212563</Size>`, matching the size the spec asserts |
| 4 | `curl -sS -i -X POST http://localhost:7022/mcp` with the `initialize` body | 200 | `mcp-session-id: 018b3a8d81ef4130b1fb328f6a3f3746` |
| 5 | `curl -sS -X POST http://localhost:7022/mcp` with the `notifications/initialized` body and the session header | 202 | Empty body |
| 6 | `curl -sS -X POST http://localhost:7022/mcp` with `tools/call` for `ocr_process`, arguments `file_uri` `http://host.docker.internal:9070/e2e-fixtures/argent-saga-chronicles-page1.png` and `lang` `en` | 200 | JSON-RPC `result` with `isError` false and a serialised `OcrJsonResponse` |

A note on the endpoint path. `POST http://localhost:7022/mcp/` with the trailing slash answers `307 Temporary Redirect` to `http://localhost:7022/mcp`, and curl does not replay a POST body across a redirect without `-L --post307`. The spec at `PaddleOCR/e2e/testing/6-mcp-ocr-test.md:108` writes the trailing-slash form. It works from Bruno, which follows the redirect, and fails from a bare curl. Recorded here as an observation, not fixed, because editing that spec is outside this verification.

The payload is a genuine OCR result, not an error envelope: `language` is `"en"`, `filename` is `"argent-saga-chronicles-page1.png"`, `pages` has one entry, `processing_time_seconds` is `93.544`, and `isError` is false. No `UNSAFE_URI` anywhere in the response, which is the proof that dropping the literal `minio` entry from `MCP_ALLOWED_HOSTS` in task 6.1 was correct: the SSRF guard still had to allow `host.docker.internal`, and it did.

The extracted text opens with the following lines, and carries all three canary substrings the spec names, `Argent Saga`, `Aenaria` and `Halen Veyr`. The block below is verbatim tool output, punctuation included.

```text
The Argent Saga — Chronicle of the Vell and the Korraxin
Part One —The Old Bright
Long before the Eclipse, when the Five Spiral Suns still held the rim worlds in their slow
cradle, a child was born on the cliff-shelf of Halen Veyr to a stonecutter named Devyn
Solveh. The child was Aenaria, and from her seventh year she could see the threads of
starlight that bound everything to the galactic core.
```

It continues through the founding of the Vell, the forging of the Argent Blades, the Heron's Tooth, and into "Part Two, The Eclipse and the Sundering", ending mid-sentence at "Among the survivors was a teacher of" where the page image ends. Line-level confidences on the sampled lines sit above 0.98.

#### Task 4.3, AudioScribe

The fixture the rewritten file names does not exist in this repository. `AudioScribe/mcp_requests.http:1` and `:4` point at `public-audio/test/15minRecording.flac`, and a repository-wide search for audio files finds only `AudioScribe/e2e/fixtures/meeting-clip.wav` and its copy at `AscendAgent/e2e/fixtures/meeting-clip.wav`. There is no fifteen-minute FLAC anywhere in the tree, and none was invented for this run. Uploading WAV bytes under a `.flac` key would have tested nothing except how the downloader guesses a suffix.

What was proven instead is the thing the task actually rewrote, which is the URL shape: bucket `public-audio` on the Floci endpoint at port 9070, fetched by the AudioScribe container through its `download_service`. The key was substituted for one that exists.

| # | Command | Status | What came back |
| :-- | :-- | :-- | :-- |
| 1 | `curl -sS -X PUT http://localhost:9070/public-audio` | 200 | Bucket created |
| 2 | `curl -sS -X PUT -H "Content-Type: audio/wav" --data-binary "@AudioScribe/e2e/fixtures/meeting-clip.wav" http://localhost:9070/public-audio/test/meeting-clip.wav` | 200 | Object stored |
| 3 | `curl -sS "http://localhost:9070/public-audio?list-type=2&prefix=test/"` | 200 | `<Key>test/meeting-clip.wav</Key>` with `<Size>56880</Size>` |
| 4 | `curl -sS http://localhost:9070/public-audio/test/meeting-clip.wav` | 200 | 56880 bytes, which is the line 1 host-side variant of the URL resolving from the host |
| 5 | `curl -sS -i -X POST http://localhost:7017/mcp` with the `initialize` body | 200 | `mcp-session-id: b09aec2f0f0944f299e745bc11166720` |
| 6 | `curl -sS -X POST http://localhost:7017/mcp` with the `notifications/initialized` body and the session header | 202 | Empty body |
| 7 | `curl -sS -X POST http://localhost:7017/mcp` with `tools/call` for `transcribe_openai`, arguments `audio_uri` `http://host.docker.internal:9070/public-audio/test/meeting-clip.wav`, `model` `whisper-1`, `language` `en` | 200 | `status` `success`, `isError` false |

The transcription came back as:

```text
I think we should defer the migration to Q3 because the contract with Acme renews then. Adam, can you confirm the renewal date by Friday?
```

That carries every canary substring `AudioScribe/e2e/testing/5-mcp-transcribe-test.md` asserts on, `Q3`, `Acme`, `Adam`, `Friday` and `migration`, so the OpenAI path resolved real audio bytes pulled out of Floci.

Row 4 covers the file's line 1 and row 7 covers its line 4. Line 1 is the host-side variant, meant for an AudioScribe run natively with uvicorn, and `localhost:9070` cannot resolve from inside a container, so it was verified as a plain host-side fetch rather than through the containerised service. Line 4 is the container variant and was verified through the running container end to end.

`transcribe_local` was not exercised. The file pins `Systran/faster-whisper-large-v3`, which would pull several gigabytes of weights into the container's `/hf-cache` on first use, and the OpenAI path already proves the object-store fetch that task 4.3 rewrote.

#### Cleanup

Every delete named its bucket literally. No wildcard, no bucket enumeration, nothing that touches `local-dev-bucket` or `knowledge-base`.

| Command | Status |
| :-- | :-- |
| `curl -sS -X DELETE http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png` | 204 |
| `curl -sS -X DELETE http://localhost:9070/e2e-fixtures` | 204 |
| `curl -sS -X DELETE http://localhost:9070/public-audio/test/meeting-clip.wav` | 204 |
| `curl -sS -X DELETE http://localhost:9070/public-audio` | 204 |

After cleanup, `curl -sS http://localhost:9070/` returns 200 and lists exactly two buckets, `local-dev-bucket` created `2026-09-02T20:19:16Z` and `knowledge-base` created `2026-09-03T09:35:31Z`. `knowledge-base?list-type=2` returns `KeyCount` 0, so the agent's startup bucket is still empty. `local-dev-bucket?list-type=2` still holds `first.txt` and `second.txt`, both `LastModified` `2026-09-02T20:19:22Z` with unchanged ETags, so the other repository's data was never touched.

---

### Tasks 1.2, 1.4, 5.5 and 10.6: closed against a fully rebuilt stack

Run on 2026-09-03. The stack was torn down and rebuilt from scratch, so Floci came up holding only `local-dev-bucket`, and Prometheus was recreated from the edited `observability/prometheus/prometheus.yaml` rather than reloaded in place.

#### Tasks 1.2 and 10.6, `BucketInitConfig` against an empty Floci

The agent was started with `./gradlew bootRun`. Within 26 seconds it logged, at 2026-09-03 09:35:31, from `c.l.a.a.a.config.BucketInitConfig`:

```text
Bucket 'knowledge-base' not found. Creating...
Bucket 'knowledge-base' created successfully.
```

`curl -sS http://localhost:9070/` then returned `ListAllMyBucketsResult` naming both `local-dev-bucket` and `knowledge-base`, the latter with the matching creation timestamp `2026-09-03T09:35:31Z` (also visible in the task 6.4/4.3 cleanup check above, since that run reused this same boot). `curl -fsS "http://localhost:9070/knowledge-base?list-type=2"` returned `ListBucketResult` with `KeyCount` 0 rather than a `NoSuchBucket` error, confirmed as part of that same cleanup check. The startup banner printed:

```text
      S3 (Floci):   http://host.docker.internal:9070/knowledge-base [Connected] (objects: 0)
```

and `docker compose ps` reported `ascend-agent` as healthy. This closes 1.2 directly, and closes 10.6 as the same boot repeated on the final state of the code, per the note in tasks.md that the two can be satisfied by one boot.

#### Task 1.4, the object-listing shape

The element-path record this task asks for already existed in the "Task 1.1 and 1.5" table above, rows 6 and 13: `ListBucketResult` then `Contents` then `Key`, namespace `http://s3.amazonaws.com/doc/2006-03-01/`, `?prefix=` honoured and echoed back in `<Prefix>`, `KeyCount` present. That record was captured against the scratch bucket `floci-contract-probe` in task 1.1, not against objects uploaded through task 1.3's upload-and-ingest flow, because task 1.3 has not run. The same shape was independently reconfirmed today against a different bucket and prefix in the task 6.4 table above, row 3 (`e2e-fixtures?list-type=2&prefix=argent-saga` returning a `<Key>` and `<Size>` under a `<Prefix>`), and in the task 4.3 table, row 3. Group 7's runbook assertions can cite the element path with three independent confirmations behind it; the one thing not proven is that path against `knowledge-base` populated by the real 1.3 flow specifically.

#### Task 5.5, Prometheus after a full recreate

Prometheus was published on host port 7077. `GET http://localhost:7077/api/v1/targets?state=active` returned exactly seven active targets: `ascend-agent`, `ascend-memory`, `ascend-paddle-ocr`, `ascend-web-search`, `audio-scribe`, `qdrant` and `weather-mcp`, every one with health `up` and an empty `lastError`, and zero targets whose job name contains `minio`. This is the live half; the static half, that the infrastructure dashboard has no panel querying a `minio_*` metric, was already confirmed by parsing `observability/grafana/dashboards/infrastructure.json` in the task 10 verification above.

---

### Facts worth carrying forward

Floci returns 200 rather than 409 on a repeated bucket `PUT`, recorded as row 11 of the task 1.1 table. It is repeated here because it constrains code as well as runbooks: any create-if-absent logic written against this endpoint must treat a plain 200 as success and must not depend on a 409 branch ever firing, which is what real S3 would send.

The AscendAgent unit suite is fully green at 700 tests with zero failures, so every failure discussed above belongs to the Testcontainers-backed integration suite and none of it to the unit suite.

---

### Resolving the `rag-source-attachments` archive collision

The "Findings recorded rather than fixed" section above left the three-way delta collision on `rag-source-attachments` for whoever implemented the pending changes. It has now been resolved, because the failure mode turned out to be worse than a silent overwrite.

Three pending changes carry a delta against this capability, and only three. `find` over `openspec/changes` returns delta directories under `replace-minio-with-floci`, `add-tenant-isolation` and `add-document-management-api` only. `add-chat-streaming-and-conversations` names the capability in its `proposal.md:37` and `design.md:61` but ships no delta for it, so it is not part of the collision.

The overlap, by requirement header:

| Requirement in `openspec/specs/rag-source-attachments/spec.md` | Floci | Tenant isolation | Document management |
| :-- | :-- | :-- | :-- |
| Opt-in `attachSources` parameter on prompt endpoint | | | see phantom header below |
| `SourceFile` DTO shape | MODIFIED | | MODIFIED |
| Empty source array when RAG returns nothing | | | |
| De-duplication by source object identity | MODIFIED | | |
| Presigned URLs for source documents | MODIFIED | MODIFIED | |
| Size cap for attached sources | | | |
| Best-effort presigning never fails the request | MODIFIED | | |
| No leakage of presigned URLs through logs or chat history | | | |
| Backward compatibility | | | |

None of the three declares an ADDED or a REMOVED requirement against this capability.

The mechanism matters. `buildUpdatedSpec` in `dist/core/specs-apply.js` of `@fission-ai/openspec@1.11.0` applies a MODIFIED block by replacing the whole requirement, and it guards that replacement with `findMissingCurrentScenarios`, which compares scenario headers by name. A MODIFIED block that does not repeat every scenario the baseline currently carries is a hard abort, not a silent drop. Requirement prose, by contrast, is replaced wholesale with no comparison at all. So the two overlaps behaved differently: the DTO shape overlap silently discarded this change's S3 wording when the document-management delta landed second, while the presigned-URL overlap hard-aborted in both directions once each side had added its own scenarios.

Both pending deltas were rebased onto the post-Floci wording, keeping their own proposals intact.

`add-tenant-isolation/specs/rag-source-attachments/spec.md` was rewritten so its "Presigned URLs for source documents" block sits on top of this change's text. It regained the credential sentence naming `app.s3.access-key` and `app.s3.secret-key`, which its earlier draft had dropped, and the object-store-neutral paragraph. Its "URL fetchable from caller's network" scenario moved off `app.s3.endpoint=http://minio:9000` and onto the `host.docker.internal:9070` external-Floci wording. It now carries seven scenarios: its own two tenant-prefix ones, unchanged in wording, plus all five this change leaves behind, including "URL resolves against an endpoint that does not validate credentials". Its tenant-prefix sentences were copied verbatim rather than reworded, so the proposal's meaning cannot drift.

`add-document-management-api/specs/rag-source-attachments/spec.md` needed only vocabulary. Its `SourceFile` DTO block described `downloadUrl` as "a presigned MinIO/S3 GET URL and its expiry", now "a presigned S3 GET URL". Its second requirement resolved the document id "by the source object's MinIO key", now "by the source object's S3 key". Its scenario set already covered both baseline scenario names, so nothing had to be added. Neither edit touches what the change proposes: `contentPath` remains the canonical download path and presigning remains demoted to an in-network mechanism.

Nothing in either pending change became redundant. Both propose behaviour this change does not implement, so no delta was dropped.

Verified by replaying the real merge engine against a scratch copy of the baseline spec, driving `buildUpdatedSpec` directly so no repository file was touched. With this change archived first, the two pending changes now apply cleanly in either relative order, and the merged spec contains ten requirements, twenty-eight scenarios and zero occurrences of `MinIO` or `minio`.

Archiving this change last still aborts, loudly, with `MODIFIED failed ... current spec contains scenario(s) not present in the modified block`. That is correct and was left alone deliberately. Making it succeed would mean copying the tenant-prefix and public-client scenarios into this change's delta, which would assert behaviour that is not implemented. A loud abort is the honest outcome, and this change is the one archiving first anyway.

### The document-management delta cannot archive at all, and that is not this change's doing

`add-document-management-api/specs/rag-source-attachments/spec.md` declares, under `## MODIFIED Requirements`, a header that does not exist in the baseline spec:

```text
### Requirement: Caller sets `attachSources=true`
```

In `openspec/specs/rag-source-attachments/spec.md` that string is a scenario under "Opt-in `attachSources` parameter on prompt endpoint", not a requirement. Archive therefore aborts with `MODIFIED failed for header "### Requirement: Caller sets attachSources=true" - not found`, in every ordering tested, including against the untouched baseline with this change absent entirely. It is a pre-existing defect in that proposal and is independent of the object-store swap.

`openspec validate --strict` does not catch it. The scenario-loss check in `dist/core/validation/validator.js` reaches `const current = currentBlockFor(key); if (!current) continue;` and skips any MODIFIED block whose target requirement is missing, so all three changes validate clean while one of them cannot archive.

This was left unfixed on purpose, because the mechanical repair is not safe on its own. Promoting the block to `## ADDED Requirements` makes archive succeed and produces a self-contradictory spec. The baseline requirement it overlaps would still assert, in its own scenario:

```text
- **AND** each `SourceFile` contains non-blank `name`, `mimeType`, `downloadUrl`, and `expiresAt` fields
```

while the newly added requirement asserts:

```text
Each `SourceFile` SHALL carry non-blank `documentId`, `name`, `mimeType`, and `contentPath` fields; `downloadUrl` / `expiresAt` MAY be present for in-network deployments.
```

One says `downloadUrl` is always non-blank, the other says it may be absent. Reconciling them means deciding whether `add-document-management-api` also modifies "Opt-in `attachSources` parameter on prompt endpoint" to restate that scenario, which changes what that proposal claims and is the owner's call rather than a rebase.

---

### Task 10.2: the `integrationTest` flakiness had a root cause, not host load

The "Integration-suite stability across seven full runs" note above blamed "pre-existing Docker Desktop network pressure." That conclusion was wrong. The real defect was reproduced on the first attempt, root-caused with direct object-identity evidence, fixed in `TestcontainersBase.java`, and reverified with three clean full-suite runs, all recorded below.

#### Reproduction

Run on 2026-09-03 with the seventeen-container `ascend-ai` stack and a separate `local-dev` stack both live, 28 containers total on the host. `./gradlew integrationTest --info` against the pre-fix code produced exactly the reported shape: 19 tests, 4 failed, every failure in `BackingServicesIT`, none of them an assertion failure. The object-store failure matched the originally reported error text word for word: `software.amazon.awssdk.core.exception.SdkClientException: Unable to execute HTTP request: Connect to localhost:38315 [localhost/127.0.0.1, localhost/0:0:0:0:0:0:0:1] failed: Connection timed out: getsockopt (SDK Attempt Count: 4)`. Postgres failed with `CannotGetJdbcConnectionException`, Redis with `RedisSystemException`, Qdrant with `StatusRuntimeException: UNAVAILABLE`, the same four shapes named in the debugging brief.

#### Root cause

`TestcontainersBase.java` declared its four backing containers as `static final` fields annotated `@Container` inside a `@Testcontainers`-annotated abstract class, with a class Javadoc comment claiming this meant "start before all tests, close after the class," implying the containers were shared for the whole suite. That claim was never true. Testcontainers' JUnit 5 extension stops an `@Container`-annotated field in `afterAll` of whichever concrete test class runs it and restarts it in `beforeAll` of the next, even when the field is `static` and declared in a shared superclass, because the extension's lifecycle scoping is per test class, not per JVM. The `docker ps` sampling captured every 3 seconds during the reproduction run shows this directly: a fresh Postgres, Redis, Qdrant and Floci container, each with a new container ID and a new mapped port, created when `BackingServicesIT` started, while the previous set from `S3PresignedUrlServiceIT` had already been torn down.

Spring's test-context cache does not know that. Its cache key is built from the static shape of a test class's configuration (declaring classes, active profiles, mock beans, property source locations), not from the runtime values a `@DynamicPropertySource` method captures. `BackingServicesIT` and `S3PresignedUrlServiceIT` share an identical shape, so Spring legitimately reused the first class's `ApplicationContext`, beans and all, for the second. Those beans had been wired once, when `S3PresignedUrlServiceIT`'s context was first built, against that class's own container ports. The proof is a literal object identity match in the raw log: at `14:03:19.965`, `HikariPool-1 - Added connection org.postgresql.jdbc.PgConnection@1e90062d` for `S3PresignedUrlServiceIT`'s Postgres on port 37979. At `14:03:49.176`, thirty seconds later and inside `BackingServicesIT`'s own test output, the exact same object surfaces again: `HikariPool-1 - Failed to validate connection org.postgresql.jdbc.PgConnection@1e90062d (This connection has been closed.)`. Same pool name, same connection object hash, in a different test class, which is only possible if Spring handed `BackingServicesIT` the reused context from `S3PresignedUrlServiceIT`. By then Testcontainers had already stopped that Postgres container and started a brand new one, on a different port, for `BackingServicesIT`, one the reused context was never wired to. The reused context's DataSource, RedisConnectionFactory, QdrantClient and S3Client were all still pointed at the dead container's ports, which produced connection-refused or connection-timed-out on every one of them depending on how far Docker Desktop's Windows-side port forwarding had gotten through tearing that port down, and that timing race is why the exact failing service varied from run to run in the seven-run record above.

#### Fix

`AscendAgent/src/test/java/com/lukk/ascend/ai/agent/integration/TestcontainersBase.java` no longer carries `@Testcontainers` on the class or `@Container` on the four fields. The fields are still `static final PostgreSQLContainer<?>`, `GenericContainer<?>` (Redis), `QdrantContainer` and `GenericContainer<?>` (Floci), unchanged in how each is configured, but they are now started once, sequentially, inside a `static { }` initializer block. A static initializer runs at class-load time, before any JUnit or Spring callback fires, so every subclass's `@DynamicPropertySource` call is guaranteed to see all four containers already running on their final ports for the entire JVM. Ryuk still reaps them at JVM exit: Ryuk registration happens inside Testcontainers' own container-start code, independent of the JUnit 5 `@Container` extension, so removing that annotation does not lose cleanup. This is Testcontainers' own documented "singleton container" pattern for a container meant to be shared across every test class in a run, not just the test methods of one class, which is exactly the sharing the removed class Javadoc had assumed was already happening.

#### Why this fix and not an alternative

Widening a client timeout or adding a retry would have hidden the symptom on a slower host without touching the defect: the reused Spring beans would still be wired to a dead container, so a longer timeout only delays the same failure and a retry against the same wrong port never succeeds. Neither was applied. `testcontainers.reuse.enable=true`, already set in the operator's `~/.testcontainers.properties`, was considered and rejected: that feature persists a container across separate `./gradlew integrationTest` invocations, not just within one, so a later change to a pinned image tag would silently keep reusing the stale container until someone remembered to `docker rm` it by hand, trading one race for a different, quieter staleness bug. The static-initializer singleton keeps the fix scoped to exactly one JVM run of the test suite, which is all the sharing this code ever needed, and Ryuk still guarantees cleanup at the end of that run. No wait strategy was touched: every prior wait strategy (Postgres's and Qdrant's built-in defaults, Floci's explicit `/_floci/health` check) had already proven itself correct in the reproduction run, since all four containers reported healthy before any test ran. The defect was never in whether a container was ready, it was in which container a live bean pointed at.

#### Verification

Three consecutive full `./gradlew integrationTest` runs against the same live stack, no container of the `ascend-ai` or `local-dev` projects stopped, started or rebuilt at any point.

| Run | Command | Result | Duration |
| :-- | :-- | :-- | :-- |
| 1 | `./gradlew integrationTest` | BUILD SUCCESSFUL, 19 tests, 0 failed, 0 errors | 1m 50s |
| 2 | `./gradlew integrationTest --rerun-tasks` | BUILD SUCCESSFUL, 19 tests, 0 failed, 0 errors | 2m 1s |
| 3 | `./gradlew integrationTest --rerun-tasks` | BUILD SUCCESSFUL, 19 tests, 0 failed, 0 errors | 2m 8s |

`--rerun-tasks` was required for runs 2 and 3. A plain `./gradlew integrationTest` immediately after run 1 was reported `BUILD SUCCESSFUL` in 12 seconds with `Task :integrationTest UP-TO-DATE`, meaning Gradle's own up-to-date check skipped real execution entirely, since nothing in the task's declared inputs had changed since run 1. The same happened for a third attempt at 4 seconds. Both were discarded and re-run with `--rerun-tasks`, which forces Gradle to genuinely re-execute rather than report a cached result, before either counted as one of the three runs above.

`docker ps --filter label=org.testcontainers=true` was sampled during each run and returned exactly one Postgres, one Redis, one Qdrant, one Floci and one Ryuk container for that run's entire duration, against the six-to-seven sets per run the pre-fix code produced. `docker ps -a --filter label=org.testcontainers=true` returned nothing after each of the three runs, confirming Ryuk reaped every container and left no orphan. `./gradlew build` was run once after the fix and is `BUILD SUCCESSFUL` in 1m 15s, closing the other half of task 10.2. `docker ps --format "{{.Names}}"` against the live stack returned the same 28 container names before and after all of the above, confirming nothing outside Testcontainers' own containers was started, stopped or rebuilt.

#### Is the suite independent of the host stack, or merely more tolerant of it

Independent, for the specific defect measured here. The failure was never host load. It was a genuine, deterministic-in-mechanism race between Testcontainers' per-class container lifecycle and Spring's cross-class context cache, and it reproduced on the very first pre-fix attempt with no other load beyond Docker Desktop's own steady-state background work. The fix removes that race rather than tolerating it: the four backing containers now start exactly once, before any test wiring happens, and nothing touches them again until the JVM exits, so there is no longer any window in which a live Spring bean can be pointed at a container Testcontainers has already torn down.

What the fix does not, and cannot, change is genuine resource pressure from an unrelated cause. The pre-fix reproduction run measured only 1872 MB of free physical memory out of 32685 MB total on the host while the suite was running, with 28 unrelated containers live. If a host is that starved, container startup itself, or the JVM's own compile-and-test step, can still be slow, or in principle fail, for reasons that have nothing to do with this defect. No such failure appeared in any of the three post-fix runs, each executed with the same 28-container stack live throughout, but that residual host-capacity risk is generic to running anything at all on a loaded machine, and it is not what caused the connection timeouts this task set out to fix.

#### Closing confirmation

`./gradlew build` was re-run after all subsequent changes landed and is green. Beyond the three consecutive full `./gradlew integrationTest` runs recorded above, an independent fourth run was executed after the test isolation defect was fixed, and it also passed. This is the suite-wide green result task 10.2 asks for; it was already ticked earlier in this file, and this entry is the record the task requires.

---

### Task 1.3 and tasks 10.4-10.5: the RAG and object-store e2e sweep

Run on 2026-09-03. This closes task 1.3 and tasks 10.4 and 10.5.

#### Task 1.3, a presigned URL resolves against Floci

Proven during the RAG end-to-end sweep rather than as an isolated call. The agent returned a source entry whose `downloadUrl` pointed at `http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx`, carrying an `X-Amz-Signature` query, with the host being `localhost:9070` rather than the docker-internal host. Fetching that exact URL from the host network returned HTTP 200 and a 13563 byte file identified as a Microsoft Word document, matching the original fixture size byte for byte. This also reconfirms task 1.4's listing shape against a real `knowledge-base` object rather than only against the task 1.1 scratch bucket.

#### Task 10.4, the RAG e2e group run serially

Specs 5, 6 and 7 executed in that order against the live stack, sweep timestamp 2026-09-03T12-22-30, run records under `AscendAgent/e2e/testing/runs/`. All three reported PASS.

| Spec | Result | Duration |
| :-- | :-- | :-- |
| 5, RAG ingestion | PASS | 6m 32s |
| 6, attach sources | PASS | 3m 17s |
| 7, RAG de-duplication | PASS | 3m 11s |

#### Task 10.5, the PaddleOCR and AudioScribe object-store e2e tests

First attempt, same sweep timestamp 2026-09-03T12-22-30: PaddleOCR PASS, AudioScribe FAIL. The AudioScribe failure was a real service defect, not a test or fixture problem: the transcription tool double-wrapped its result, so the documented single parse could not reach the expected fields.

The service was fixed and its container rebuilt, then both tests were re-run under sweep timestamp 2026-09-03T17-06-00. Both reported PASS. A single parse now reaches `source`, `model`, `language` and `transcription`. No download failure occurred during OCR in this re-run, which also confirms the separate fix for OCR inference starving the service's event loop, recorded in the dated findings section below. Both fixtures were deleted afterward and the bucket is empty.

---

### 2026-09-03: what the verification sweep found beyond the migration itself

These are real defects the sweep exposed while proving the Floci swap. They are part of this change's story even though none of them is the object-store swap itself, so they are recorded here rather than left to a commit message.

The transcription tool double-wrapped its result. Fixed in the service rather than by teaching the tests to unwrap twice, with the tests strengthened so they can no longer pass under both shapes.

OCR inference ran on a thread that starved the service's own event loop, freezing health checks for the entire duration of every call, which was the real cause of an intermittent download timeout that had looked like a network fault. It now runs in a separate process, with tracing rewired to follow it and thread pools capped to the container's CPU allocation.

The embedding provider default never bound, because the configuration key and the properties field disagreed, so a request that omitted the field was rejected with an error containing the literal word null. One key renamed, plus a test that loads the real configuration file, which is the gap that let it through.

Four PaddleOCR security assertions and one AudioScribe assertion were reading fields that do not exist, so they passed on undefined. All corrected.

Two specs described response field names the services never returned, in the weather forecast and the Anthropic prompt cache. Both corrected against the code.

Every request file in the collection asserted status code only, so 42 of them gained real body assertions taken from their paired specs.

The end-to-end suite leaked state between runs. Every spec now has both a reset and a cleanup covering chat history, both Redis keys, semantic memory and any object it uploads.
