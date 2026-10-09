## Context

See proposal.md for the motivation. This change holds the agent parts that `add-file-download` planned until 2026-10-04, when the owner rule of that day (the personal assistant comes first, nothing personal, web-hunter or base may depend on company work, company work comes last and only plugs in through extension points with safe defaults) and the owner instruction of the same day split them out. Decision numbers D11 and D16 keep the numbers they had in `add-file-download`, so a cross-reference written against them lands here for the agent side.

Facts that shape the approach, read from the active changes:

- `add-file-download` (build group 2) gives ascend-web-hunter the download, keep, list and delete operations, the key layout `tenant/<tenantId>/downloads/<sha256>/` and `tenant/<tenantId>/files/<sha256>/` in the bucket `web-hunter-downloads`, the 24-hour retention as a sweep inside web-hunter, and, for the internal caller, `storage.bucket` and `storage.key` on `GET /api/v2/web/downloads/{id}` and `GET /api/v2/web/downloads/kept/{id}` (its D11). A call that names no tenant runs as tenant `default` (its D8).
- `add-keycloak-login` (build group 3, position 3) gives the authorization matrix that every later change extends with its own rows (its D4), the service token that closes ascend-web-hunter (its section 4), and `TenantContext.currentTenantId()` (its D3).
- `add-agent-skills` (build group 4, position 1) gives `AgentNativeTool`, the tool context keys `tenant_id` and `request_id`, and the shared code `unavailable`.
- `close-agent-test-gaps` (build group 3, position 1) gives the scripted model of the shared e2e harness. It starts only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04).
- `add-mcp-tool-servers` gives the `_meta` forwarding of `tenant_id` and `request_id` to `trust: internal` servers, the per server `request-timeout`, and the per tool module override `tools.overrides.<tool>.module`.
- `add-document-management-api` gives the `documents` registry with an open `source_type` and the indexing run model.
- `add-deployment-modules` gives `@ConditionalOnModule` and the catalog entry `web-download`.

## Goals / Non-Goals

**Goals:**

- One downloaded file becomes searchable only when the owner asks for that file.
- The agent never learns the web-hunter key layout beyond the prefix check, and never downloads the bytes through itself.
- No dependency on a company change.

**Non-Goals:**

- Anything inside ascend-web-hunter. That is `add-file-download`.
- The ledger row for downloads. `add-usage-metering-and-quotas` adds it in its own tasks when company work lands.
- Streaming a download through the agent at `GET /api/v1/downloads/{id}/content`. A later change (owner decision 2 of 2026-10-02 in `add-file-download`).

## Decisions

### D11: Opt-in ingestion through the agent

ascend-web-hunter never calls the agent. Ingestion is an agent operation on an existing download or kept file:

- Agent native tool `knowledge_add_download` with `{download_id}` and REST `POST /api/v1/documents/from-download` with `{download_id, embedding_provider}` (the provider optional, as on upload). The REST role is the role of `POST /api/v1/ingestion/upload` in the matrix of `add-keycloak-login` (`USER` or `ADMIN`), see the matrix row below.
- The tenant is the caller's tenant: `TenantContext.currentTenantId()` of `add-keycloak-login` on the REST path, and the `tenant_id` of the tool context on the tool path, which is filled from the same `TenantContext`. In a personal deployment it is `default`. `add-auth-and-identity` (company, build group 5) changes which tenant a resolved identity carries later, with no edit here.
- The agent reads the record with `GET /api/v2/web/downloads/{id}` and, when that answers 404 because the download was already deleted 24 hours after its last download, with `GET /api/v2/web/downloads/kept/{id}`, through a small `RestClient` (`WebHunterDownloadClient`), sending `X-Ascend-Tenant` with the caller's tenant and the service token of `add-keycloak-login`. The record for this internal caller carries `storage.bucket` and `storage.key`, so the key layout stays known to web-hunter alone.
- The agent refuses a key that does not start with `tenant/<caller tenant>/`, a defence in depth of the kind `add-tenant-isolation` later puts on presigning. ascend-web-hunter keeps every object under that prefix for every tenant, `default` included, so the check holds from the first day.
- Families `pdf`, `office`, `text` and `image` are accepted, because the agent's `DocumentRouter` handles them (an image through ascend-ocr). `archive` is refused with 422 `download_not_ingestible`.
- An unknown id, an id of another tenant, and a record whose key does not start with `tenant/<caller tenant>/` are answered with 404 `download_not_found`. A missing or unreadable request body is answered with the existing `bad_request` of `upgrade-spring-boot-4`. When web-hunter cannot be reached, times out or answers 5xx, the agent answers 503 with the shared code `unavailable` of `add-agent-skills`, and nothing is copied.
- The agent copies the object server side (`CopyObject`) into `knowledge-base`, into the `documents` folder under the tenant prefix of the agent's ingestion path, at `documents/<first 16 hex of the id>-<file name>`. Before `add-tenant-isolation` that prefix is empty, the layout an upload uses today, and after it the prefix is `tenant/<tenantId>/`. The agent registers a `documents` row with `source_type` `web-download` and `origin_uri` the record's `source_url`, and starts an indexing run with the run model of `add-document-management-api`. The answer is 202 with `document_id` and `run_id`. When a `documents` row with that object key exists already, the answer is 200 with its ids and nothing is copied again. A row that a racing call on another agent instance inserted first counts the same: the unique `object_key` of the registry turns the second insert into a conflict, which is read back and answered 200 (answer 87).

Why a separate tool and not an `ingest` flag on `web_download_file`: the download tool lives in web-hunter, which must not depend on the agent, and a flag would need the agent to read the arguments of another server's tool call. A separate tool keeps ingestion opt-in per file, as the owner asked, and gives the app a REST call for an "add to knowledge base" button.

`knowledge_add_download`, `POST /api/v1/documents/from-download` and `WebHunterDownloadClient` carry `@ConditionalOnModule("web-download")`. The knowledge base belongs to `rag`, which is always on (owner decision of 2026-10-03), so no second module is named.

Role rules. `add-keycloak-login` lands before this change and says that a later change adds its own rows to its authorization matrix (its D4), and its coverage test fails the build for an endpoint with no row. This change adds one row to that matrix in `SecurityConfig`, written the same way:

| Path | Rule |
|---|---|
| `POST /api/v1/documents/from-download` (`add-download-ingestion`) | `USER` or `ADMIN` |

The agent has no other download endpoint. The web-hunter routes of `add-file-download` are not agent endpoints: they sit behind the service token of `add-keycloak-login`, which only the agent holds. A later agent endpoint that streams a file, such as `GET /api/v1/downloads/{id}/content`, adds its own row the same way when it is built.

Errors: two new values in `ApiErrorCode`, `download_not_found` (404) and `download_not_ingestible` (422). The change reuses `bad_request` (400) of `upgrade-spring-boot-4` and the shared `unavailable` (503) of `add-agent-skills`, and adds no second code for either case. Checked against the twenty codes of `upgrade-spring-boot-4` D19 and the shared codes of `add-agent-skills` D10 on 2026-10-02.

### D16: The module switch on the agent side

The agent's entry `app.mcp.servers.ascend-web-hunter` sets `tools.overrides.<tool>.module` to `web-download` for each of the eight `web_download_*` tools, the per tool module override that `add-mcp-tool-servers` adds (required edit there), so a tenant without the module grant does not get them:

```yaml
      ascend-web-hunter:
        module: web-search
        tools:
          overrides:
            web_download_file: { module: web-download }
            web_download_get: { module: web-download }
            web_download_list: { module: web-download }
            web_download_delete: { module: web-download }
            web_download_keep: { module: web-download }
            web_download_kept_get: { module: web-download }
            web_download_kept_list: { module: web-download }
            web_download_kept_delete: { module: web-download }
```

ascend-web-hunter registers those tools only when its own `ASCEND_MODULES` holds `web-download` (`add-file-download` D16), so the two sides read the same switch.

### D17: Tests

- Unit tests for the tool and the endpoint with a fake web-hunter client, a `@WebMvcTest` per status, and a security slice test for the matrix row.
- An integration test with Testcontainers Floci and Postgres for the server side copy and the `documents` row.
- A Pact consumer test for `GET /api/v2/web/downloads/{id}` and `GET /api/v2/web/downloads/kept/{id}`, writing `contracts/pacts/ascend-agent-ascend-web-hunter.json`, verified by the provider verification of `add-file-download` task 8.10, the pattern the agent and ascend-ocr pair already follow, because the agent relies on `storage.key` and the family names.
- End-to-end: a deterministic agent ingestion spec, a deterministic chat spec in which the scripted model of the shared harness of `close-agent-test-gaps` calls the download and knowledge tools (owner answer 67.1 of 2026-10-04), and one AI-run spec only for the retrieval answer. Every spec runs as an e2e user of tenant `default` of `add-keycloak-login` (owner answer 67.4 of 2026-10-04).

## Required edits to other changes

Each edit below must be made in the named change. They were made for `add-file-download` before the split, checked on 2026-10-03, and they now serve this change. The named changes still name `add-file-download` in places, and the reference fix of 2026-10-04 points those places here where they name an agent part.

### `add-mcp-tool-servers` (made there, checked on 2026-10-03)

Edits 1 to 4 are made in that change, its D1, D3, D4 and D5 and its section "Applied here from other changes".

1. Design D3: for every connection whose entry has `trust: internal`, one `ToolContextToMcpMetaConverter` copies the tool context keys `tenant_id` and `request_id` into the MCP `_meta` object as `ascend.ai/tenant_id` and `ascend.ai/request_id`. Nothing is copied for `trust: external`. The `mcp-tool-servers` spec gains a requirement with scenarios for both.
2. Design D1 example: the `ascend-web-hunter` entry sets `request-timeout` to at least `DOWNLOAD_TIMEOUT_SECONDS` plus 30 seconds (330 seconds at the defaults).
3. Design "Name changes the model sees": the eight `web_download_*` tools keep their names because they already carry the `web_` prefix.
4. Design D1 and the `mcp-tool-servers` spec: a server entry accepts the per tool module override `tools.overrides.<tool>.module`, and the `ascend-web-hunter` entry sets it to `web-download` for the eight `web_download_*` tools (D16). This change uses exactly that key and no other marking.

### `add-action-approvals` (made there on 2026-10-02)

1. Design D2: file download is listed among the own MCP tools that stay `allowed`, because the `web_download_*` tools read from the web or change only data inside the system. `knowledge_add_download` is `allowed` for the same reason.

### `add-agent-skills` (made there, checked 2026-10-03)

1. Design D3: `knowledge_add_download` is one more `AgentNativeTool`, offered through `ChatToolset` like the others. The tenant tool allow-list of `add-tenant-policy` (company, build group 5) governs it later like every other tool, with no edit here.

### `add-usage-metering-and-quotas` (company, made there, checked 2026-10-03)

1. Design D12 and `specs/usage-metering/spec.md`: a request type `web-download`, one row per `web_download_file` call that stored or deduplicated a file, with `provider` `ascend-web-hunter`, `bytes` the size and `tier` the `fetch_path`. A refused or failed call writes no row. That change writes the row in its own task when company work lands, and this change carries no task for it, so nothing personal waits for company work.
2. Design D6: `web_download_file` calls consume the same `web-search` bucket as the other web-hunter tools.

### Checked, no edit needed

- `add-document-management-api`: `source_type` is an open string, so `web-download` needs no schema change.
- `add-deployment-modules`: its catalog entry `web-download` exists, and `rag` is always on, so the agent parts carry `@ConditionalOnModule("web-download")` alone (owner decisions of 2026-10-03).
- `add-keycloak-login`: its D4 table of later changes names this change's row.

## Risks / Trade-offs

- [A downloaded file is harmful, for example a PDF with an exploit] → Ingestion is opt-in per file, and docling-serve and ascend-ocr are the only readers. The optional scan of `add-file-download` D9 is available to an operator.
- [web-hunter changes its record shape] → The Pact contract fails the provider verification before release.
- [A download was deleted 24 hours after its last download before the owner asked to ingest it] → The agent reads the kept copy when there is one, and otherwise answers 404 `download_not_found`, so the owner downloads it again.

## Migration Plan

1. Land at build group 4, position 8 of the owner build order of 2026-10-04, after `add-file-download`, `close-agent-test-gaps`, `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-document-management-api`, `add-agent-skills` and `add-mcp-tool-servers`. There is no data to move.
2. Rollback: deploy the previous image. Documents already ingested stay in the knowledge base and can be deleted through document management.

## Owner decisions

- Owner request of 2026-10-02: the assistant finds files on the web and hands them to the owner, and a file is added to the knowledge base only on request.
- Owner decisions of 2026-10-03: `rag` is always on, so the agent parts name only `web-download`.
- Owner rule of 2026-10-04: the personal assistant comes first, nothing personal, web-hunter or base may depend on company work, and company work comes last and only plugs in through extension points with safe defaults.
- Owner instruction of 2026-10-04: the agent parts of `add-file-download` (task group 9, the agent specs of its tasks 10.5 and 10.6, `knowledge_add_download`, `POST /api/v1/documents/from-download`, the agent download client) form this change, build group 4, after `add-document-management-api` (superseded by the owner build order of 2026-10-04, which places it at build group 4, position 8).
- Owner answers 67.1 and 67.4 of 2026-10-04: a check that needs no real model uses the scripted model of the shared harness (now owned by `close-agent-test-gaps`, owner answer 70.4 of 2026-10-04), and every end-to-end run uses the Keycloak e2e users.
- Owner answer 76.2 of 2026-10-08: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/file-download/` (task 2.2).

## Owner decisions of 2026-10-08

- Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (the deterministic spec of task 2.2). Superseded by answer 91.1 below.

Answer 91.1: in the deterministic phase AscendMemory is faked in the one Mockoon container `e2e-scripted-model` under the route prefix `/ascend-memory/` (insert and search), the agent's `app.memory.semantic.base-url` points there in the deterministic overlay, and AscendMemory is never restarted. The deterministic chat spec of task 2.2 therefore wipes no memory in its Reset state and Post-run cleanup, and needs no dummy key. The AI-run spec of task 2.2 runs against the real AscendMemory.

Answer 91.3: step 7 of the agent ingestion spec of task 2.1 is dropped. It stopped the shared `ascend-web-hunter` container only to prove the 503 `unavailable` that the `@WebMvcTest` of task 1.3 and the client unit tests of task 1.2 already prove. The spec now runs alone in the quarantine lane only because step 1 is bound to docling. The scripted chat spec and the AI-run spec stay: the first proves the download tool through the live web-hunter MCP server, which no lower test reaches, and the second runs with a real model.

Answer 93: the platform has one tenant header name, `X-Ascend-Tenant`. This change already sends it to ascend-web-hunter (D11, task 1.2), so nothing changes here. The sandbox runner, which read `X-Tenant-Id`, moves to the same name in `add-agent-sandbox`. The review item that the agent does two lookups (the download, then the kept file, D11) is not applied: one lookup would need a new combined route in `add-file-download` or would drop the fallback to the kept copy, which is a behaviour the owner has.

Answer 87 (rule R1): checked for several agent instances. The change keeps no lock, cache, queue or timer of its own. Two instances that ingest the same download at once both find or insert the same `documents` row, whose `object_key` is unique in the registry of `add-document-management-api`, so one row and one indexing run result, and the second call answers 200 with the same ids. The server side copy writes the same bytes to the same key, so a repeated copy is harmless.

Answer 86.1: no Testcontainers test of this change needs an HTTP fake (the client is unit tested against a mocked server, and the contract by Pact), so no Mockoon container is added.

Answer 85.1: no plan text of this change exports a key or a secret in a shell. The e2e token comes from the helper of `add-keycloak-login` and every service token from the repository `.env`.

Answer 98 (owner rule 98, every value with a default is a setting): made external in task 1.2, each as `${ENV:default}` in `application.yaml`, the same default in the `app.downloads` record, and `- ENV=${ENV:-default}` on the `ascend-agent` service of `compose.yaml`: `app.downloads.web-hunter-base-url` (`APP_DOWNLOADS_WEBHUNTERBASEURL`, `http://localhost:7021` for a host run and `http://ascend-web-hunter:7021` in the docker profile and on the compose line, the two addresses the existing `ascend-web-hunter` MCP entry has in `application.yaml` and `application-docker.yaml`, read on 2026-10-08), `app.downloads.connect-timeout` (`APP_DOWNLOADS_CONNECTTIMEOUT`, default not decided) and `app.downloads.read-timeout` (`APP_DOWNLOADS_READTIMEOUT`, default not decided). The `request-timeout` of the `ascend-web-hunter` MCP entry belongs to `add-mcp-tool-servers` and is externalised there. Kept as constants, because they are not operational: the route paths `/api/v2/web/downloads/{id}` and `/api/v2/web/downloads/kept/{id}`, the header `X-Ascend-Tenant`, the folder `documents` of today's ingestion path (a key layout), while the bucket `knowledge-base` is the existing setting `app.s3.bucket` that the copy reads and does not name itself, the 16 hex characters of the object name (a key format), the families, the error codes and `source_type` `web-download`. The 24-hour retention is `DOWNLOAD_RETENTION_SECONDS` of `add-file-download`. The rows go into `apps/ascend-agent/docs/CONFIGURATION.md` (task 1.8). No test or measurement of this change uses LM Studio. The AI-run spec of task 2.2 names no provider in this plan.

## Open Questions

None.
