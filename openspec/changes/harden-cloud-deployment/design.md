# Design - Harden Cloud Deployment

## Context

The stack was built for one developer's Windows workstation. The target is one VM per external customer, running the same compose stack, reachable from outside only through TLS on ports 80 and 443.

Hard constraint from the owner: `compose.yaml` is the single compose entry point. It pulls in `compose.ascend-web-hunter.yaml` through `include:`, and every compose command runs against the main file with no `-f` flag. Local `docker compose up` from the repo root must keep working.

Build order: this change runs before group C, so before `add-auth-and-identity`. It owns the network, TLS, secrets transport and container hardening. It does not touch authentication. Keycloak, its host address and port, its rate limits and the `SECURITY_ENABLED` production guard belong to `add-auth-and-identity`. Keycloak is a separate service on its own host address and port and is never routed under a path of this gateway.

The four data stores (Postgres, Redis, Qdrant, the S3-compatible object store, which is Floci on host port 9070 locally) are external prerequisites. `compose.yaml` does not define them. Locally they come from the owner's separate local-dev stack. In the cloud they are either containers of a separate stack on the same VM or managed services.

## Goals / Non-Goals

Goals:

- Only ports 80 and 443 reachable from outside a cloud VM.
- TLS at one gateway, ACME in the cloud, internal certificate locally.
- No credential in the tree that a production deployment accepts. Startup fails under the `production` profile when a development default is still in use.
- The object store is never public.
- Personal-machine artifacts are opt-in.
- SSRF allowlists without a loopback default.
- `docker compose up` from a fresh clone still gives a working local stack.
- An operator guide in `docs/DEPLOYMENT.md`.

Non-Goals:

- Authentication, Keycloak, tenant isolation, metering, audit (group C).
- Kubernetes, Terraform, orchestration beyond compose on a VM.
- Running the four data stores as services of `compose.yaml`.
- Several tenants on one VM.

## Decisions

### D1 - One file, bind address from the environment, profiles for optional services

Every published port except the gateway's becomes `"${EXPOSE_BIND:-127.0.0.1}:<host>:<container>"`. That covers, in `compose.yaml`: docling-serve `5001`, unstructured-api `9080`, ascend-ocr `7022`, ascend-agent `9917`, ascend-memory `7020`, ascend-weather-mcp `9998`, ascend-audio-scribe `7017`, prometheus `7077`, grafana `7078`. In `compose.ascend-web-hunter.yaml`: searxng `9020`, flaresolverr `8191` (today a literal `127.0.0.1:` prefix), ascend-web-hunter `7021`. The bundled `redis` service publishes nothing and stays that way. loki, vector, otel-collector, tempo and container-metrics-exporter publish nothing and stay that way. They talk only over the compose network.

`ngrok-ascend-web-hunter` gets `profiles: ["captcha-intervention"]`. Enabling it means adding that name to `COMPOSE_PROFILES` in `.env`, next to the existing `redis` profile.

Rejected: a second production compose file used with `-f` (breaks the single entry point and creates container name conflicts), an auto-loaded override file (a fresh clone would get the hardened stack and local dev would need a copy step), profiles for exposure (profiles gate whole services, not ports).

### D2 - Gateway: Caddy, one upstream

Caddy 2, image pinned by version and digest like every other pulled image. Only service publishing `80:80` and `443:443` on all interfaces.

- Site address `{$ASCEND_DOMAIN:localhost}`. A real domain gets ACME certificates. `localhost` gets Caddy's internal CA.
- One site, one upstream: `reverse_proxy ascend-agent:9917`. No Grafana route, no object store route, and no Keycloak path under this site. When `add-auth-and-identity` adds Keycloak it may add a second site block in `gateway/Caddyfile` for Keycloak's own host name (for example `auth.<customer-domain>`), never a path such as `/auth/` under the agent's site.
- Caddy sets `X-Forwarded-For` and `X-Forwarded-Proto` by default.
- `POST /api/v1/ai/prompt/stream` (from `add-chat-streaming-and-conversations`, built before this change) is proxied with `flush_interval -1` and without a read timeout that could cut a stream.
- No rate limiting at the gateway in this change. Abuse limits for unauthenticated endpoints belong to `add-auth-and-identity`, which owns the only unauthenticated login surface.

Rejected: Traefik (label sprawl for one upstream), nginx (needs a certbot sidecar).

### D3 - Secrets: `.env` interpolation, production startup guard

- `GRAFANA_ADMIN_PASSWORD` uses `${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set in .env}`. `SEARXNG_SECRET` already uses this form.
- Development defaults stay legitimate locally: Postgres user and password, Redis password (empty), Qdrant API key (empty), object store access and secret key, ascend-ocr result store keys, `SECURITY_USERNAME` and `SECURITY_PASSWORD` (`admin`/`admin`, already read from the environment at `application.yaml:73-74`). In `application.yaml` these use `${VAR:devdefault}`. In compose they are passed through as `${VAR:-devdefault}` or `${VAR:-}`.
- The agent gets `ProductionCredentialGuard`, a `@Configuration` class active only with `@Profile("production")`. On startup it fails when any of these resolved values equals its development default: `app.s3.access-key`, `app.s3.secret-key`, `spring.datasource.username` paired with `spring.datasource.password` (`local`), `spring.data.redis.password` (empty), `spring.ai.vectorstore.qdrant.api-key` (empty), `app.security.user.password` (`admin`, read from `SECURITY_PASSWORD` at `application.yaml:74`). The message names the property and never prints its value. A unit test reads `application.yaml` and asserts that the guard's default constants equal the defaults written there, so the two cannot drift.
- Whether `SECURITY_ENABLED` must be true in production is not checked here. `add-auth-and-identity` adds that.
- Rejected: Docker secrets (needs file plumbing in every service, the Python services read environment variables), Vault or SOPS (not needed for one VM per customer).

### D4 - Personal mounts

- ascend-audio-scribe volumes become `"${HF_CACHE_ROOT:-hf-cache}:/hf-cache"` and `"${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio"`, with both named volumes declared. A value with no path is a named volume, a path is a bind mount, so the owner restores today's behavior with two `.env` lines.
- `MCP_FILE_URI_ROOT` becomes `${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}`. Empty means `file://` is disabled, which is the existing contract of ascend-audio-scribe.

### D5 - Drop `SYS_ADMIN` from ascend-web-hunter

Chromium's sandbox needs `clone`, `unshare` and `setns` with namespace flags that the default Docker seccomp profile blocks. `SYS_ADMIN` allows far more. Replace it with `security_opt: ["seccomp=./security/chromium-seccomp.json", "no-new-privileges:true"]` and `init: true`. `shm_size: 2gb` stays. The profile is the Docker default profile plus the namespace calls, checked in at `security/chromium-seccomp.json`. The path is relative to `compose.ascend-web-hunter.yaml`, which sits at the repo root next to `security/`.

Rejected: `--no-sandbox` (removes the layer that matters for untrusted content), AppArmor (not on every host).

### D6 - SearXNG limiter stays off

`infra/searxng/settings.yml:37-41` turns the limiter off on purpose: every caller reaches SearXNG from the ascend-web-hunter container, so all requests share one Docker network address and the per-address limiter blocks them together. The earlier plan of this change was to turn the limiter on and forward the client's `X-Forwarded-For`. That does not answer the reason: ascend-web-hunter is called by the agent over MCP, not by end users, so the forwarded address would still be the same for every request. The change therefore keeps `limiter: false` and keeps the `SEARXNG_X_REAL_IP` and `SEARXNG_X_FORWARDED_FOR` values ascend-web-hunter sends (`compose.ascend-web-hunter.yaml:190-191`). Protection comes from the network: SearXNG is reachable only on the compose network and on host loopback, and ascend-web-hunter rate-limits upstream. `infra/searxng/settings.yml` and its byte-identical copy `apps/ascend-web-hunter/deploy-standalone/searxng/settings.yml` are not changed.

### D7 - SSRF allowlists and object store privacy

- `MCP_ALLOWED_HOSTS` on ascend-ocr and ascend-audio-scribe becomes `${MCP_ALLOWED_HOSTS:-}`. Empty is the strict block that both services already implement. There is no object store host on the compose network, so no in-network name can be a useful default.
- Local development sets `MCP_ALLOWED_HOSTS=host.docker.internal` in `.env`, because Floci listens on host port 9070. `.env.example` shows this line.
- In the cloud the operator sets the object store's private host name, and nothing else.
- Object store addresses come from the environment:
  - agent: `app.s3.endpoint` from `S3_ENDPOINT`, `app.s3.public-endpoint` from `S3_PUBLIC_ENDPOINT` (defaults keep today's values: `http://localhost:9070` in `application.yaml`, `http://host.docker.internal:9070` and `http://localhost:9070` in `application-docker.yaml`).
  - ascend-ocr: `OCR_RESULT_S3_ENDPOINT=${OCR_RESULT_S3_ENDPOINT:-http://host.docker.internal:9070}` and `OCR_RESULT_S3_PUBLIC_ENDPOINT=${OCR_RESULT_S3_PUBLIC_ENDPOINT:-http://localhost:9070}`.
- The object store is never public. In production both public endpoint variables are set to the same private address as the endpoint, because only containers on the private network follow those presigned links: the agent reads ascend-ocr results in-network, and public clients get RAG sources through the agent's `GET /api/v1/documents/{id}/content` (`add-document-management-api`). The gateway has no route to the object store. A presigned link handed to a public client would not resolve, which is the intended result.

### D8 - Observability exposure and hardening

- Grafana: `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_AUTH_ANONYMOUS_ORG_ROLE` removed, `GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:-admin}`, `GF_SECURITY_ADMIN_PASSWORD` required. Loopback-bound, reached on a VM through an SSH tunnel.
- Prometheus: loopback-bound, `--web.enable-lifecycle` removed.
- loki, vector, otel-collector, tempo, container-metrics-exporter: no published port. vector and container-metrics-exporter keep the read-only Docker socket mount they need, and every observability service gets `security_opt: ["no-new-privileges:true"]`, the logging anchor and a healthcheck.

### D9 - Runtime posture

- `compose.yaml` gets its own `x-logging: &default-logging` anchor (json-file, `max-size: "10m"`, `max-file: "3"`), the same values as `compose.ascend-web-hunter.yaml:6-10`, and every service in `compose.yaml` uses it. Anchors do not cross `include:`, so the two files each keep one.
- Healthchecks added to docling-serve, unstructured-api, ascend-weather-mcp, prometheus, grafana, loki, vector, otel-collector, tempo and gateway. Each check uses a tool that exists in that image. The implementer confirms with `docker run --rm --entrypoint sh <image> -c "command -v wget curl"` and falls back to the service's own binary or a Python one-liner when neither exists.
- ascend-agent `depends_on` becomes long form with `condition: service_healthy` on ascend-memory, docling-serve and unstructured-api.
- `security_opt: ["no-new-privileges:true"]` on every service that lacks it.
- Every pulled image is already pinned by version and digest (ngrok uses tag `3` plus a digest, which pins it). The gateway image follows the same form.

## Risks / Trade-offs

- Loopback ports still exist on the VM, so any process on the VM can reach them. Acceptable with one customer per VM. Documented in the guide.
- Chromium updates may need new system calls. The ascend-web-hunter Playwright tests are the check, and the profile is one file in the repo.
- The required Grafana password adds one `.env` line for local development. `.env.example` shows it.
- Caddy's internal CA causes a browser warning locally. Local work can keep using `http://localhost:<port>`.
- The guard repeats the development defaults. A test ties them to `application.yaml`.
- The SearXNG limiter stays off. If SearXNG is ever exposed beyond loopback this decision must be revisited.

## Migration Plan

1. Land the compose and configuration changes. Developers add `GRAFANA_ADMIN_PASSWORD`, `MCP_ALLOWED_HOSTS=host.docker.internal` and, for the owner, the two media lines to `.env`, then run `docker compose up -d`.
2. A cloud deployment follows the new `docs/DEPLOYMENT.md` section: DNS record, `.env` with real values, `docker compose up -d`, external port scan shows only 80 and 443.
3. Rollback is `git revert`. No data migration exists in this change.

## Open Questions

None for this change. Whether customer VMs use managed data stores or containers is a deployment choice. The guide documents both.
