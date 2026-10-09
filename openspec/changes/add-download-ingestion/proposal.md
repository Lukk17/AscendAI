## Why

The owner wants the assistant to find files on the web and hand them to him: electronics schematics, datasheets, PDFs, images and archives (owner request of 2026-10-02). `add-file-download` gives ascend-web-hunter the download, the keep and the 24-hour retention. Some of those files the owner wants to search later, for example a datasheet he asks questions about, so the agent needs a way to copy one download into the knowledge base on request, and only on request.

That agent part was planned inside `add-file-download` until 2026-10-04. The owner rule of that day says the personal assistant comes first, nothing personal, web-hunter or base may depend on company work, and company work comes last and only plugs in through extension points with safe defaults. `add-file-download` became web-hunter only (build group 2), and its agent parts moved here: task group 9, the agent end-to-end specs, `knowledge_add_download`, `POST /api/v1/documents/from-download` and the agent's download client.

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 8. It needs `add-file-download` (build group 2: the web-hunter routes it reads), `close-agent-test-gaps` (the shared scripted e2e harness), `upgrade-spring-boot-4` (the problem detail and Flyway), `add-keycloak-login` (the role matrix it adds its row to, the service token, and `TenantContext.currentTenantId()`), `add-deployment-modules` (the module `web-download`), `add-document-management-api` (the document registry and the indexing run), `add-agent-skills` (`AgentNativeTool` and the shared code `unavailable`) and `add-mcp-tool-servers` (the `_meta` forwarding, the request timeout and the per tool module override), which all land earlier. It depends on no company change.

## What Changes

- A new agent native tool `knowledge_add_download` and REST endpoint `POST /api/v1/documents/from-download` in ascend-agent copy one download or kept file into the tenant's knowledge base and index it. Nothing is indexed unless asked for that one file. The id is looked up as a temporary download first and as a kept file when the download was already deleted.
- The tenant is the caller's tenant from `TenantContext.currentTenantId()` of `add-keycloak-login`, which is `default` in a personal deployment, sent to ascend-web-hunter as `X-Ascend-Tenant`. `add-auth-and-identity` (company, build group 5) changes which tenant a resolved identity carries later, with no edit here.
- The endpoint needs `USER` or `ADMIN`, this change's own row in the authorization matrix of `add-keycloak-login` (its D4).
- A small agent REST client, `WebHunterDownloadClient`, reads the download record from ascend-web-hunter with the service token of `add-keycloak-login`, and a Pact consumer test holds the contract with web-hunter.
- The agent's `ascend-web-hunter` server entry marks the eight `web_download_*` tools with the module `web-download` through the per tool module override of `add-mcp-tool-servers`, and the agent parts carry `@ConditionalOnModule("web-download")`. The knowledge base belongs to `rag`, which is always on (owner decision of 2026-10-03), so no second module is named.
- Errors are RFC 7807 problem details with two new `ApiErrorCode` values, `download_not_found` (404) and `download_not_ingestible` (422).
- End-to-end (owner request of 2026-10-04): a deterministic agent ingestion spec, a deterministic agent chat spec driven by the scripted model of the shared harness of `close-agent-test-gaps`, and an AI-run agent spec for the retrieval answer, each listed in `docs/E2E_RUN_SCENARIOS.md`. The scripted model and the fake MCP server start only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04).
- The `web-download` ledger row of `add-usage-metering-and-quotas` (company, build group 5) is company work that plugs in later in that change's own tasks. This change writes no ledger row and does not wait for it.

## Capabilities

### New Capabilities

- `download-ingestion`: the agent side that copies one download into the tenant's knowledge base on request and indexes it, and the agent side of the `web-download` module switch.

### Modified Capabilities

(none)

## Impact

- ascend-agent: `knowledge_add_download` (an `AgentNativeTool`), `POST /api/v1/documents/from-download`, `WebHunterDownloadClient` on `RestClient`, `app.downloads.*` configuration (web-hunter base URL and timeouts), two `ApiErrorCode` values, one matrix row in `SecurityConfig`, and the per tool module override in the `ascend-web-hunter` entry of `application.yaml`.
- Contracts: the Pact file `contracts/pacts/ascend-agent-ascend-web-hunter.json`, written by the consumer test here and verified by the provider verification of `add-file-download` task 8.10.
- Docs: `apps/ascend-agent/AGENTS.md`, the agent's API docs, and a Bruno request for the endpoint under `docs/api/request/AscendAI/`.
- e2e: three agent specs in `apps/ascend-agent/e2e/testing/`, the scripted model rules in the shared Mockoon environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` and reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/file-download/`, and their Bruno requests.

## Relevant Skills

Load these before implementing this change:

- `/springboot-patterns` and `/java-coding-standards` for the agent tool, endpoint and client
- `/api-design` for the REST resource, status codes and RFC 7807 bodies
- `/security-review` for the tenant prefix check and the role row
- `/tdd-workflow` for writing each test before its code
- `/e2e-runbooks` for the new end-to-end specs
- `/markdown-writer` for the docs updates

Every agent command runs from `apps/ascend-agent/` with `./gradlew` (or `.\gradlew.bat`).
