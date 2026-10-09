# Proposal

## Why

The owner deploys ascend-web-hunter on its own, through the standalone bundle `apps/ascend-web-hunter/deploy-standalone/`,
right after build group 2, and wants it to run as several containers at once (owner answer 96 of 2026-10-08). Nothing
ascend-web-hunter needs may wait for build group 3.

The group 2 changes before this one already keep every piece of shared state outside a single container: stateless MCP
of the shared Python library (`add-ascend-python-common`, owner answer 94.2), rate limit windows in Redis (answer 94.3),
NoVNC flow records in Redis (`open-several-novnc-windows-at-once`), crawl page claims in Redis
(`enhance-web-search-crawl-at-scale`), the read cache purge channel `read_cache_purge`
(`enhance-web-search-extraction-and-tiers`) and the retention lock `download_retention_lock` (`add-file-download`).
What is still missing is the deployment itself. Both compose files fix `container_name: ascend-web-hunter`,
`hostname: ascend-web-hunter` and the host port `7021:7021` on the service, so a second container of it cannot start.
Nothing spreads requests over several containers, nothing routes a human to the NoVNC window of the container that owns
it (`open-several-novnc-windows-at-once` Decision 11 assumes a router that does not exist before build group 3), and no
end to end check has ever run two containers together.

## What Changes

- The `ascend-web-hunter` service of `compose.ascend-web-hunter.yaml` and of `deploy-standalone/compose.yaml` loses its
  fixed `container_name`, its fixed `hostname` and its published host port. The number of copies is one setting,
  `WEB_HUNTER_REPLICAS`, read as `deploy.replicas: ${WEB_HUNTER_REPLICAS:-1}`, named like `OPENCLAW_HOST_APPS_REPLICAS`
  of `add-openclaw-plugin-host`. Default 1, so a stack with the setting unset runs exactly as many containers as today.
  Each copy gets its short container ID as host name.
- A new small edge proxy, the compose service `ascend-web-hunter-edge` (Caddy, pinned by version and digest at
  implementation time), sits in front of the copies in both files. It is the only service that publishes port 7021
  (`127.0.0.1:7021` in development, `7021` in the bundle, as the bundle README requires). It spreads every request over
  the copies it finds under the compose service name `ascend-web-hunter`, and routes `/novnc/{hostname}/*` to port 7900
  of that copy, only for `ascend-web-hunter` or a 12 character lower case hexadecimal short container ID, 404 otherwise.
  A second listener on port 7900, never published, carries only NoVNC and is what the Ngrok tunnel points at, so the
  public tunnel never exposes the API.
- `NOVNC_PUBLIC_URL` of `open-several-novnc-windows-at-once` points at this proxy. With one copy and `NOVNC_PUBLIC_URL`
  unset, today's path keeps working: `PUBLIC_VNC_URL` resolves the Ngrok address and the tunnel reaches the one copy
  through the proxy. The VNC password of each display stays.
- An optional setting `NGROK_DOMAIN` (owner answer 97 of 2026-10-08) starts the Ngrok tunnel of both files on that fixed
  domain with the agent flag `--url`, passed only when the setting is set. The owner then sets
  `NOVNC_PUBLIC_URL=https://<that domain>`, so several copies are reachable from the internet. Empty keeps today's
  random address, which works with one copy.
- Each copy reads the caller's address from the `X-Forwarded-For` header the proxy writes (`FORWARDED_ALLOW_IPS`, `*` by default, safe
  because no copy publishes a port), so the per caller rate limit still keys on the caller and not on the proxy.
- Every value of this change that has a default is a setting (owner rule 98 of 2026-10-08, design D13):
  `WEB_HUNTER_REPLICAS`, `FORWARDED_ALLOW_IPS` and the two edge proxy waits `WEB_HUNTER_EDGE_DNS_REFRESH_SECONDS` and
  `WEB_HUNTER_EDGE_TRY_DURATION_SECONDS`, each passed as `${VAR:-default}` in both compose files and listed in
  `apps/ascend-web-hunter/docs/configuration.md`.
- No host port per copy and no host port range (owner answer 98.6 of 2026-10-08). A scaled company deployment with an
  autoscaler: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it.
- Prometheus scrapes every copy through DNS service discovery instead of the one static target `ascend-web-hunter:7021`.
- Every document, Bruno environment, e2e spec, IDE run configuration and script that addresses the container by the
  fixed name `ascend-web-hunter` moves to the compose service form (`docker compose exec`, `cp`, `logs` and `ps`), and the
  root `AGENTS.md` and `apps/ascend-web-hunter/AGENTS.md` text about the fixed container names and the one project at
  a time rule is rewritten for the names that are left.
- One e2e check runs two copies and exercises every multi container mechanism of build group 2 together. It is a new
  Part B of the existing automated spec `<N>-concurrent-interventions-test.md` of `open-several-novnc-windows-at-once`
  task 11.3, updated in place. No new spec.
- The deploy-standalone README (containers, configuration table, resource footprint, NoVNC section, sync section and the
  list of intended differences) and both `.env.example` files are updated in the same task, by the sync rule of
  `apps/ascend-web-hunter/AGENTS.md`. The edge configuration in the bundle is a byte identical copy of the development
  one.
- `harden-cloud-deployment` task 2.7 no longer builds a second NoVNC router: its NoVNC site forwards to the NoVNC
  listener of this edge proxy. Its task 1.2 moves the `EXPOSE_BIND` form of port 7021 to the edge proxy.
- Version: ascend-web-hunter `0.0.17`, the one named version of this change after the `0.0.16` of `add-file-download`,
  and the bundle's image tag moves to it.

## Capabilities

### New Capabilities

- `web-search-multi-container-deployment`: ascend-web-hunter runs as several copies of one compose service behind one
  edge proxy, in the development stack and in the standalone bundle, and every copy shares the service's state. No
  existing capability describes how ascend-web-hunter is deployed, so the deployment requirements need their own.

### Modified Capabilities

- `web-search-concurrent-human-intervention`: a NoVNC window is reached through the edge proxy by the host name of the
  copy that owns it, and the public tunnel reaches only NoVNC.
- `web-search-antibot-evasion`: the inbound per caller limit keys on the caller in front of the edge proxy.
- `observability-stack`: Prometheus scrapes every ascend-web-hunter copy.
- `ai-driven-e2e-runner`: a command inside a service that runs several copies names the compose service, never a
  container name.

## Impact

- Compose: `compose.ascend-web-hunter.yaml` and `apps/ascend-web-hunter/deploy-standalone/compose.yaml` (the
  `ascend-web-hunter` service, the new `ascend-web-hunter-edge` service, the Ngrok target, the `OTEL_RESOURCE_ATTRIBUTES`
  version in the development file and the image tag in the bundle). `compose.yaml` is not edited, it reaches the new
  service through its `include:`.
- New files: `infra/web-hunter-edge/Caddyfile` and its byte identical copy
  `apps/ascend-web-hunter/deploy-standalone/edge/Caddyfile`.
- Observability: `infra/observability/prometheus/prometheus.yaml`, `infra/observability/README.md`,
  `docs/architecture/memory-budget.md`.
- Code: no ascend-web-hunter source change is planned. Task 1.3 checks that nothing in `apps/ascend-web-hunter/src`
  reads the fixed host name and that the installed uvicorn reads `FORWARDED_ALLOW_IPS`, and a finding there is a task
  of this change.
- Docs and tests: root `AGENTS.md`, `apps/ascend-web-hunter/AGENTS.md`, `README.md`, `CHANGELOG.md`,
  `docs/configuration.md`, `docs/running.md`, `docs/troubleshooting.md`, `docs/architecture/arc42/` pages 02 and 07, the
  deploy-standalone README, both `.env.example` files, `docs/DEPLOYMENT.md`, `docs/E2E_RUN_SCENARIOS.md`,
  `apps/ascend-web-hunter/e2e/` (README, testing README, specs 7 and 10 and the concurrent interventions spec with their
  templates), `apps/ascend-agent/e2e/README.md` (the permission allowlist), the `ascend-web-hunter` job of
  `.github/workflows/e2e.yaml` (edited only, never run or pushed), the Bruno folder
  `docs/api/request/AscendAI/web-hunter/testing/interventions/`.
- Plans: `open-several-novnc-windows-at-once` (Decision 11, its configuration row and task 10.1 name this proxy instead
  of the group 3 gateway), `add-file-download` (no longer the last change of the group), `harden-cloud-deployment`
  (tasks 1.2, 2.7, 5.2 and 11.4, design D2), `openspec/BUILD_ORDER.md`.
- Build order (owner build order of 2026-10-04, which supersedes the earlier orders, and owner answer 96 of 2026-10-08):
  build group 2 (web-hunter), position 11, the last change of the group, directly after `add-file-download`
  (position 10). It needs every earlier change of group 2: `add-ascend-python-common` (position 1: stateless MCP, the
  Redis rate limit storage, `REDIS_URL`, the version `0.0.7` line of `OTEL_RESOURCE_ATTRIBUTES`),
  `add-python-runtime-upgrades` (position 2: FastMCP in stateless HTTP mode and `MCP_ALLOWED_HOST_HEADERS`),
  `open-several-novnc-windows-at-once` (position 3: `NOVNC_PUBLIC_URL`, the flow records in Redis and the spec this
  change updates), `remove-flaresolverr-tier` (position 7: the FlareSolverr container is gone),
  `enhance-web-search-extraction-and-tiers` (position 6: the channel `read_cache_purge`),
  `enhance-web-search-crawl-at-scale` (position 9: the crawl claims) and `add-file-download` (position 10: the retention
  lock and the version `0.0.16`). It also uses the fake site of `add-web-search-scraping-e2e` (build group 1, position
  3) and the Linux host rules of `fix-linux-docker-host-access` (build group 1, position 4). `harden-cloud-deployment`
  (build group 3, position 4) reuses its edge proxy later and is not waited for. It depends on no company change.

## Relevant Skills

- `docker-patterns` for the compose services, the pinned edge image and the hardening of the new container
- `deployment-patterns` for the replica setting, the health checks and the standalone bundle
- `observability-and-logging` for the Prometheus discovery of every copy
- `python-patterns` and `coding-standards` for the checks of task 1.3 and any finding they turn up
- `e2e-runbooks` for the updated spec and its Bruno requests
- `markdown-writer` for the deploy-standalone README and the AGENTS.md files
- `security-review` for the NoVNC route, the forwarded caller address and the public tunnel
