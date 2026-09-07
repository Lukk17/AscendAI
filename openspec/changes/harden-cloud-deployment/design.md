# Design — Harden Cloud Deployment

## Context

The stack was built for a single developer's Windows workstation: every service publishes to all host interfaces, credentials are hardcoded defaults, personal paths (`C:\Users\Lukk\Desktop`, `D:/Development/AI/hf-cache`) are baked into the compose file, and everything speaks plain HTTP. The target now is a single-tenant VM per external customer, running the same compose stack, reachable only through TLS on 80/443.

Hard constraint from the repo owner: `docker-compose.yaml` is the single compose entry point. It `include:`-s `ascend-scrapper.docker-compose.yaml`; every compose command runs against the main file with no `-f` flag. Whatever production mechanism is chosen must keep `docker compose up` from the repo root as the local-dev experience and must not create a second standalone compose project.

Sibling change `add-auth-and-identity` owns application-level identity (JWT resource server, Keycloak compose service, service tokens). This change owns everything below it: network exposure, TLS, secrets transport, and container hardening. The two meet at exactly one point — the gateway must route to Keycloak once it exists.

## Goals / Non-Goals

**Goals:**

- Only ports 80/443 publicly reachable on a cloud VM; every other service loopback-bound or unbound.
- TLS termination at a single gateway with automatic certificates in the cloud and a workable local story.
- No credential in the tree that works in production; fail-fast when a required secret is missing under the production posture.
- Remove or gate every personal-machine artifact (Desktop mount, `hf-cache` path, ngrok, `SYS_ADMIN`).
- SSRF allowlists without loopback in shared deployments.
- `docker compose up` from a fresh clone still brings up a working local stack.
- An operator-facing cloud VM deployment guide in `docs/DEPLOYMENT.md`.

**Non-Goals:**

- Application-level authentication and authorization (`add-auth-and-identity`), tenant isolation, metering, audit — sibling changes.
- Kubernetes, Terraform, or any orchestration beyond docker compose on a VM.
- Managing the four external data stores (Postgres, Redis, Qdrant, the S3-compatible object store) as compose services — they remain external prerequisites; this change wires their credentials and documents their backup, nothing more.
- Multi-tenant deployments on one VM — the model is one VM per customer.

## Decisions

### D1 — Production mechanism: env-driven bind addresses + compose profiles, one file

**Chosen:** a hybrid inside the existing `docker-compose.yaml`:

1. Every host-port publication becomes `"${EXPOSE_BIND:-127.0.0.1}:host:container"`. Default is loopback: local dev keeps `localhost:<port>` access for every service exactly as today, and on a cloud VM those ports are unreachable from outside without any operator action. An operator who genuinely needs LAN exposure of a single service can SSH-tunnel or temporarily set `EXPOSE_BIND=0.0.0.0` — documented as a dev-only escape hatch.
2. Dev-only whole services (`ngrok-ascend-web-hunter`) get `profiles: ["captcha-intervention"]` — absent from `docker compose up` unless the profile is activated via `COMPOSE_PROFILES` in `.env`.
3. Personal mounts become env-interpolated volume sources with named-volume defaults (D4), so no override file is needed for them.

**Alternatives considered:**

- **Separate production compose file via `-f`** — rejected: violates the single-entry-point constraint outright and creates the parallel-project container-name conflicts already flagged in this repo.
- **`docker-compose.override.yaml` auto-loaded for dev conveniences** — viable (no `-f`, auto-merged), rejected because it inverts the default: a fresh clone would produce the hardened stack and local dev would need a copy step before anything works. The chosen default (loopback binding) is simultaneously dev-friendly and production-safe, so the override file buys nothing.
- **Compose profiles for everything (`--profile production`)** — rejected: profiles gate whole services, not port bindings or volume sources, so they cannot express "same service, different exposure"; duplicating each service per profile violates DRY and doubles maintenance.

The change from `"9917:9917"` to `"${EXPOSE_BIND:-127.0.0.1}:9917:9917"` is behavior-preserving for every documented local workflow (browsers, Bruno, `gradlew bootRun` fallback all use `localhost`).

### D2 — Gateway: Caddy

**Chosen:** Caddy 2 (pinned image) as the only service publishing `0.0.0.0:80` and `0.0.0.0:443`.

- Automatic ACME (Let's Encrypt/ZeroSSL) with zero configuration beyond the domain name — the single-tenant-VM-per-customer model means one domain per deployment, Caddy's sweet spot.
- `local_certs`/internal CA mode gives working self-signed TLS locally with the same Caddyfile, switched by the `ASCEND_DOMAIN` env var (a real domain triggers ACME; `localhost` triggers the internal CA).
- Caddyfile routes: `/` → `ascend-ai-agent:9917`; a reserved route (e.g. `/auth/*` or an `auth.` subdomain — finalized when `add-auth-and-identity` lands Keycloak) → `keycloak:8080`; optional operator-gated route to Grafana (default: not routed, loopback + SSH tunnel only).
- Caddy sets real `X-Forwarded-For` / `X-Forwarded-Proto` headers, which D6 relies on.

**Alternatives considered:**

- **Traefik** — label-driven dynamic config is excellent for many-service routing, but this stack routes to exactly one (later two) upstreams; the label sprawl across compose services costs more than it returns. Rejected as overweight (KISS).
- **nginx** — battle-tested but needs certbot sidecar choreography for ACME and manual cert renewal wiring; more moving parts for the same result. Rejected.

### D3 — Secrets: `.env` interpolation with required-variable fail-fast in production

- All credentials become compose env interpolations. Two classes:
  - **Always-required** (no sane default exists): `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`. These use compose's `${VAR:?message}` form — `docker compose up` fails immediately with a clear message if unset. `.env.example` ships them with placeholder guidance so local dev is a one-time copy-and-fill.
  - **Dev-defaulted** (a local default is legitimate because the store runs on the developer's own machine): Postgres user/password, Redis password (empty = passwordless local Redis), S3 access/secret keys, Qdrant API key (empty = unauthenticated local Qdrant). These use `${VAR:-devdefault}` in compose and `${VAR:devdefault}` in `application.yaml`.
- **Production fail-fast for the dev-defaulted class**: ascend-ai-agent gains a startup guard active only when the `production` Spring profile is present — it refuses to start if any datastore credential still equals its known dev default (`password`, `local`, empty Redis password, empty Qdrant key). This keeps local dev friction-free while making "forgot to set the S3 password" a startup error instead of a silent open door. The guard is a small `@Configuration` validator, not Spring Cloud Config or Vault.
- **SearXNG secret**: removed from `infra/searxng/settings.yml`, injected via the `SEARXNG_SECRET` env var (natively supported by SearXNG). The committed value is compromised by definition and the tasks include rotating it.
- **Alternatives considered**: Docker secrets (`secrets:` top-level) — rejected: requires swarm mode or file-based secrets plumbing in every service, and the Python services read config from env vars; env + `.env` is the pattern the stack already uses. Vault/SOPS — rejected as YAGNI for single-VM single-tenant.

### D4 — Personal mounts: env-interpolated volume sources with named-volume defaults

- `ascend-audio-scribe` volumes become `- "${HF_CACHE_ROOT:-hf-cache}:/hf-cache"` and `- "${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio"`, with `hf-cache` and `ascend-audio-scribe-media` declared as named volumes. Compose treats a pathless value as a named volume and a path as a bind mount, so the owner's two `.env` lines (`HF_CACHE_ROOT=D:/Development/AI/hf-cache`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT=C:\Users\Lukk\Desktop`) restore today's behavior; every other deployment gets empty, harmless named volumes.
- `MCP_FILE_URI_ROOT` becomes `${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}` — empty means `file://` URIs disabled (ascend-audio-scribe's existing contract: unset ⇒ rejected). Reading host files through transcription becomes an explicit opt-in, never a default.

### D5 — Dropping `SYS_ADMIN` from `ascend-web-hunter`

`SYS_ADMIN` was added for Chromium's sandbox, which needs `clone(2)` with new-namespace flags that Docker's default seccomp profile blocks. `SYS_ADMIN` grants far more (mount, bpf-adjacent operations, device administration) — an unacceptable capability while rendering untrusted web pages.

**Chosen:** replace `cap_add: SYS_ADMIN` with:

- `security_opt: ["seccomp=./security/chromium-seccomp.json"]` — a checked-in seccomp profile (the widely used Chromium profile derived from Jessie Frazelle's `chrome.json`) that permits the namespace syscalls (`clone`, `unshare`, `setns` with user-namespace flags) without granting the capability. Chromium's sandbox works; the container cannot mount filesystems or administer devices.
- `init: true` — Chromium spawns per-site processes; without an init, crashed renderers zombie. `shm_size: 2gb` already present, kept.
- Verification task: Playwright extraction tier must pass its existing tests inside the rebuilt container with the capability removed, and `docker inspect` must show no added capabilities.

**Alternatives considered:** `--no-sandbox` Chromium flag — rejected: disables the layer that matters most when the content is untrusted. Keeping `SYS_ADMIN` with AppArmor confinement — rejected: AppArmor availability varies by host distro; seccomp ships with every Docker engine.

### D6 — SearXNG limiter and real client IP

- `SEARXNG_LIMITER=true` and the spoofed `SEARXNG_X_FORWARDED_FOR=0.0.0.0` / `SEARXNG_X_REAL_IP=0.0.0.0` env vars are removed from `ascend-web-hunter`. ascend-web-hunter forwards the `X-Forwarded-For` it receives (originating at the Caddy gateway) instead of a spoofed constant, so SearXNG's per-client limiter sees real clients.
- SearXNG itself stays loopback-bound (D1); the limiter is defense in depth for in-network abuse, not a public-surface control.

### D7 — SSRF allowlists: explicit, no loopback

- `MCP_ALLOWED_HOSTS` on both `ascend-ocr` and `ascend-audio-scribe` becomes `${MCP_ALLOWED_HOSTS:-object-store}`. The default allowlists only the in-network `object-store` hostname used for RAG-document and presigned-URL fetches. Local dev, where the S3-compatible object store runs on the host and is reached via `host.docker.internal`, sets `MCP_ALLOWED_HOSTS=host.docker.internal` in `.env` — a deliberate, documented, per-machine opt-in instead of a committed default that whitelists loopback everywhere.
- The deployment guide covers the cloud topology: the object store reachable at a private hostname, that hostname (and nothing else) in the allowlist.

### D8 — Observability exposure

- Grafana: `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?...}`, `GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:-admin}`. Port stays loopback-bound per D1; operators reach it via SSH tunnel by default. A commented Caddy route exists for deployments that want `grafana.<domain>` behind Grafana's own login.
- Prometheus: loopback-bound, no auth added (it has none built in; loopback + tunnel is the control). `--web.enable-lifecycle` is dropped in favor of container restarts, removing an unauthenticated config-reload endpoint.

### D9 — Production posture checklist mechanics

- `depends_on` entries upgraded to the long form with `condition: service_healthy` wherever the dependency has a healthcheck; healthchecks added to `docling-serve`, `unstructured-api`, `ascend-weather-mcp`, `searxng`, `flaresolverr`, `grafana`, and `prometheus` so gating is meaningful.
- A top-level `x-logging: &default-logging` anchor (json-file driver, `max-size: 10m`, `max-file: 3`) applied to every service — bounded disk usage on long-lived VMs.
- Image pinning: audit confirms every image is version-pinned except `ngrok/ngrok:3` (floating major); pin it. Locally built images unaffected.
- `SECURITY_ENABLED` passes through compose as `${SECURITY_ENABLED:-false}`; the deployment guide's production checklist requires `SECURITY_ENABLED=true` in the customer `.env`, and the ascend-ai-agent production-profile guard (D3) warns loudly when it is false. The auth behavior behind the flag belongs to `add-auth-and-identity`.

## Risks / Trade-offs

- [Loopback-bound ports still exist on the VM] → any process on the VM can reach them; acceptable in the single-tenant model where the VM runs only this stack, and strictly better than today's `0.0.0.0`. Documented in the guide.
- [Seccomp profile drift — Chromium updates may need new syscalls] → verification task pins the Playwright test suite as the canary; profile lives in-repo so a fix is a one-file PR.
- [`${VAR:?}` fail-fast also hits local dev] → intentional for the two always-required secrets; `.env.example` makes it a one-time copy step. Kept to exactly two variables to bound the friction.
- [Caddy internal CA locally means browser trust warnings] → acceptable for dev; local flows can keep using plain `http://localhost:<port>` direct to services since loopback bindings remain.
- [Real `X-Forwarded-For` may trip SearXNG's limiter for the agent's own high-volume search traffic] → the limiter distinguishes clients; the agent is one client. If throttling appears, the limiter's bot-detection thresholds are tunable in `infra/searxng/settings.yml` — an operational knob, not a design flaw.
- [Keycloak route is designed before Keycloak exists] → the Caddyfile ships the route commented/feature-flagged; `add-auth-and-identity` uncomments it. Coordination noted in both changes.
- [The production Spring-profile guard duplicates knowledge of dev defaults] → constants live in one guard class next to a test asserting they match `application.yaml` defaults; DRY preserved by the test, not by hand.

## Migration Plan

1. Land the compose changes; local devs pull, copy the updated `.env.example` deltas into their `.env` (Grafana password, SearXNG secret, optional Desktop-mount lines), and `docker compose up` as before.
2. Rotate the SearXNG secret (new random value in each `.env`); the committed value is dead.
3. First cloud deployment follows the new `docs/DEPLOYMENT.md` section end-to-end: DNS A record → `.env` from `.env.example` with real secrets → `docker compose up -d --build` → external port scan shows only 80/443 → smoke prompts via `https://<domain>`.
4. Rollback: `git revert` of the compose changes restores the previous topology; no data migration is involved anywhere in this change.

## Open Questions

- Keycloak routing shape (path prefix `/auth/*` vs `auth.<domain>` subdomain) — decided together with `add-auth-and-identity` when its Keycloak service lands; the Caddyfile reserves both forms as comments.
- Whether customer VMs will use managed data stores (RDS/ElastiCache/Qdrant Cloud) or co-located containers — the guide documents the env-var wiring for both, but backup tooling recommendations differ; confirm with the first customer deployment.
