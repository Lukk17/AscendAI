## Why

A crawl job from `enhance-web-search-crawl-at-scale` writes pages to object storage, but nothing turns them into a
tenant knowledge base that stays fresh. The connector framework from `add-connector-framework` already defines how a
source lands bytes under a tenant prefix and triggers ingestion. A `WEB_CRAWL` connector type plugs a site into that
framework. The owner moved this part out of the crawl change on 2026-10-01. Not started.

## What Changes

- A `WEB_CRAWL` connector type in apps/ascend-agent under the `service/connector/` framework from
  `add-connector-framework`: its source scope holds seeds, include and exclude patterns, depth and page budget. The
  schedule is the framework's own five-field cron and time zone, run by the connector's `connector-sync` execution on
  the shared scheduler of `add-shared-scheduler`. The type needs no credential, and it carries
  `@ConditionalOnModule("web-search")` of `add-deployment-modules`. It depends only on the switchable module
  `web-search`, because `rag` is core and always on (owner decision of 2026-10-03).
- Each scheduled run submits an ascend-web-hunter crawl with `POST /api/v1/crawl/jobs`, polls
  `GET /api/v1/crawl/jobs/{job_id}`, copies changed pages from the crawl result prefix into the prefix that the framework's `TenantPrefixResolver` gives
  the connector's tenant in object storage (Floci locally, host port 9070), and triggers the existing ingestion pipeline. No parallel parse path.
- Each landed page is registered in the document registry of `add-document-management-api` with `source_type`
  `connector:web-crawl`, the page URL as `origin_uri` and the connector id, which the framework writes and the
  ingestion run copies onto every chunk.
- A page that disappeared since the last run is deleted through the single-document deletion path of
  `add-document-management-api`.

## Capabilities

### New Capabilities

- `web-search-rag-connector`: the `web` connector, its landing contract, deletion propagation and landing under the framework's tenant prefix.

### Modified Capabilities

None.

## Dependencies and Build Order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 16. It needs `add-connector-framework` (build group 4, position 7: the framework, split out of `add-document-connectors` on 2026-10-04, and its `TenantPrefixResolver`), and the earlier changes it really uses: `enhance-web-search-crawl-at-scale` (build group 2, position 9: the crawl API), `upgrade-spring-boot-4` (the RFC 7807 problem detail of a refused configuration), `add-keycloak-login` (`TenantContext.currentTenantId()`, which answers `default` in the personal deployment, and the `ADMIN` role of the connector endpoints), `add-deployment-modules` (the switchable module `web-search`, its marking and `module_denied`), `add-shared-scheduler` (the shared scheduler that runs every connector sync) and `add-document-management-api` (the deletion path and the document registry). All of them land earlier. It does not depend on `add-document-connectors`, `add-tenant-isolation` or any other company change (owner rule of 2026-10-04): the tenant of a connector comes from `TenantContext` of `add-keycloak-login` and the object key prefix from the framework's `TenantPrefixResolver`, whose default answers the empty prefix, so today's key layout holds. `add-tenant-isolation` (company, build group 5) registers the `tenant/{tenantId}/` prefix implementation later. This change does not wait for it.

## Impact

- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/connector/web/`: new connector, crawl client and
  configuration, each carrying `@ConditionalOnModule("web-search")`.
- The Flyway migration of this change admits `WEB_CRAWL` in the connector type check constraint of
  `add-connector-framework` (`V<n>__web_crawl_connector.sql`, `<n>` the next free version at implementation time).
- `apps/ascend-agent/src/main/resources/application.yaml`, `application-docker.yaml` and the `ascend-agent` service of
  `compose.yaml`: the settings of the connector (design D5: the ascend-web-hunter base URL, the crawl client timeouts,
  the crawl result bucket and the configuration bounds), each read from its environment variable (owner rule 98), and
  their rows in `apps/ascend-agent/docs/CONFIGURATION.md`.
- `docs/CONNECTORS.md` (from `add-connector-framework`): the web connector section.
- e2e: a deterministic agent spec `<N>-web-crawl-connector` (refused configuration, manual runs,
  landing, registry rows, Qdrant points and deletion propagation against the shared e2e fake site) and an AI-run
  agent spec `<N>-web-crawl-rag-ai` (a retrieval answer from a crawled page), their Bruno folder
  `docs/api/request/AscendAI/ascend-agent/testing/web-crawl-connector/`, and their places in
  `docs/E2E_RUN_SCENARIOS.md`.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/tdd-workflow`
- `/api-design`
- `/security-review`
