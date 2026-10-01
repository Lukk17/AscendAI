## Why

A crawl job from `enhance-web-search-crawl-at-scale` writes pages to object storage, but nothing turns them into a
tenant knowledge base that stays fresh. The connector framework from `add-document-connectors` already defines how a
source lands bytes under a tenant prefix and triggers ingestion. A `web` connector type plugs a site into that
framework. The owner moved this part out of the crawl change on 2026-10-01. Not started.

## What Changes

- A `web` connector type in apps/ascend-agent under the `service/connector/` framework from `add-document-connectors`:
  configuration holds seeds, include and exclude patterns, depth, page budget and a schedule.
- Each scheduled run submits an ascend-web-hunter crawl with `POST /api/v1/crawl/jobs`, polls
  `GET /api/v1/crawl/jobs/{job_id}`, copies changed pages from the crawl result prefix into the tenant's prefix in
  object storage (Floci locally, host port 9070), and triggers the existing ingestion pipeline. No parallel parse path.
- A page that disappeared since the last run is deleted through the single-document deletion path of
  `add-document-management-api`.

## Capabilities

### New Capabilities

- `web-search-rag-connector`: the `web` connector, its landing contract, deletion propagation and tenant isolation.

### Modified Capabilities

None.

## Dependencies and Build Order

Depends on `enhance-web-search-crawl-at-scale` (the crawl API), `add-document-connectors` (the framework),
`add-document-management-api` (deletion path) and, through the framework, `add-tenant-isolation`. Starts only after
all four are archived.

## Impact

- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/connector/web/`: new connector, crawl client and
  configuration.
- `apps/ascend-agent/src/main/resources/application.yaml`: the ascend-web-hunter base URL for the connector.
- `docs/CONNECTORS.md` (from `add-document-connectors`): the web connector section.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/tdd-workflow`
- `/api-design`
- `/security-review`
