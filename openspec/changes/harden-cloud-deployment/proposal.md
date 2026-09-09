# Harden Cloud Deployment

## Why

The docker-compose stack is a personal-workstation setup that becomes a security incident the moment it lands on a cloud VM. Every service publishes its port to all host interfaces: Docling with its UI enabled (`compose.yaml:14-15,25`), Unstructured (`:37-38`), ascend-ocr (`:52-53`), ascend-ai-agent (`:106-107`), AscendMemory (`:153-154`), ascend-weather-mcp (`:208-209`), ascend-audio-scribe (`:227-228`), Prometheus (`:277-278`), Grafana with anonymous Editor access (`:298-302`), SearXNG (`compose.ascend-web-hunter.yaml:11-12`), FlareSolverr (`:28-29`), and ascend-web-hunter (`:64-65`). On a VM with a public IP, all twelve become unauthenticated public endpoints.

On top of the exposure problem: `ascend-audio-scribe` bind-mounts the owner's Desktop into the container with `MCP_FILE_URI_ROOT=/audio` (`compose.yaml:238,243-244`), so any caller can read arbitrary Desktop files through the transcription API; `ascend-web-hunter` runs with `cap_add: SYS_ADMIN` while rendering untrusted web content (`compose.ascend-web-hunter.yaml:85-86`); the SSRF allowlists whitelist loopback (`MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1` at `compose.yaml:67` and `:236`), which defeats the guard the moment the service shares a host with anything private; credentials are hardcoded defaults (the S3-compatible object store `admin`/`password` at `apps/ascend-agent/src/main/resources/application.yaml:99-100`, Postgres `postgres`/`local` at `:360-362`, passwordless Redis, a committed SearXNG `secret_key` at `infra/searxng/settings.yml:47`); SearXNG runs with its limiter disabled and a spoofed `X-Forwarded-For=0.0.0.0` (`compose.ascend-web-hunter.yaml:71-74`); and everything is plain HTTP. None of this survives contact with an external customer's VM. The sibling `add-auth-and-identity` change fixes application-level identity; this change owns the network, TLS, and secrets layer underneath it.

## What Changes

- **Edge gateway with TLS.** A reverse proxy (design decides between Caddy, Traefik, and nginx) becomes the only service publishing to all interfaces — ports 80/443 with automatic ACME certificates on a cloud VM and a self-signed/internal certificate locally. It routes to ascend-ai-agent and (coordination point) to the Keycloak service that `add-auth-and-identity` introduces. Nothing else is publicly reachable.
- **Env-driven port binding.** Every existing host-port publication gains a bind-address prefix defaulting to loopback (`${EXPOSE_BIND:-127.0.0.1}:port:port`), so `docker compose up` from the repo root keeps working unchanged for local dev (services stay reachable at `localhost:<port>`) while a cloud VM exposes nothing except the gateway. The main `compose.yaml` stays the single compose entry point — no `-f` flags, no second project.
- **Secrets out of the tree.** All credentials flow from `.env`: Postgres, Redis, the S3-compatible object store, Qdrant, Grafana admin, SearXNG secret. The committed SearXNG `secret_key` is rotated out of `infra/searxng/settings.yml` and injected via env. Under the production posture the stack fails fast when a required secret is unset; no default credential works in production. `.env.example` is extended to document every variable.
- **Personal-machine artifacts gated.** The Desktop mount and `hf-cache` bind mount become env-driven volume sources defaulting to safe named volumes, with `MCP_FILE_URI_ROOT` defaulting to disabled; the ngrok tunnel moves behind a compose profile. **BREAKING** for local dev only to the extent that the Desktop mount now requires two `.env` lines.
- **`SYS_ADMIN` dropped.** `ascend-web-hunter` loses `cap_add: SYS_ADMIN`; Chromium gets what it actually needs via a checked-in seccomp profile plus `init: true` (design documents the analysis).
- **SSRF allowlists tightened.** No loopback entries in shared deployments; object-store fetches go through the in-network `object-store` hostname (or the operator-configured endpoint), allowlisted explicitly via env.
- **SearXNG limiter re-enabled** and the spoofed `X-Forwarded-For` removed; real client context arrives via the gateway.
- **Grafana secured.** Anonymous access off, admin password from env, not publicly bound.
- **Production posture checklist.** Healthcheck-gated `depends_on`, restart policies and resource limits reviewed, log rotation via a shared logging anchor, image pinning verified (only `ngrok/ngrok:3` floats today), and `SECURITY_ENABLED=true` required in the production posture (the auth implementation itself is `add-auth-and-identity` — referenced, not re-specified).
- **Deployment guide.** `docs/DEPLOYMENT.md` (existing) gains a single-tenant-per-customer cloud VM section: DNS, TLS, `.env` preparation, and backup procedures for the four external data stores (Postgres, Redis, Qdrant, the S3-compatible object store).

## Capabilities

### New Capabilities

- `production-deployment`: network exposure model (loopback-default bindings, gateway-only public surface), TLS termination, secrets management with production fail-fast, personal-artifact gating, SSRF allowlist posture, SearXNG hardening, production readiness checklist, and the cloud VM deployment guide.

### Modified Capabilities

- `ascend-agent-containerization`: the "ascend-ai-agent runs as a Compose service by default" requirement changes — the host port mapping becomes loopback-bound by default and public reachability moves behind the gateway; the "`.env.example` documents the secrets compose consumes" requirement expands to cover the new datastore credentials, Grafana admin password, bind-address, and volume-source variables.

(`ingestion-security` was reviewed and left unchanged — its requirements cover upload hygiene inside ascend-ai-agent (filename sanitization, MIME allowlist, size limits), not deployment posture. The SSRF allowlist tightening lives in `production-deployment` because the allowlists are compose-level configuration of ascend-ocr and ascend-audio-scribe, not ascend-ai-agent ingestion behavior.)

## Impact

- **`compose.yaml`**: every `ports:` entry gains the `${EXPOSE_BIND:-127.0.0.1}` prefix; new `gateway` service; Grafana env block rewritten; `ascend-audio-scribe` volumes and `MCP_FILE_URI_ROOT` become env-driven; `MCP_ALLOWED_HOSTS` values become env-driven with safe defaults; `depends_on` entries upgraded to `condition: service_healthy` where healthchecks exist; new healthchecks for services lacking them; shared `x-logging` anchor for rotation.
- **`compose.ascend-web-hunter.yaml`**: `ascend-web-hunter` loses `SYS_ADMIN`, gains seccomp profile + `init: true`; SearXNG limiter env flips; `ngrok-ascend-web-hunter` gains a profile; `ngrok/ngrok:3` pinned.
- **New files**: gateway config (e.g. `gateway/Caddyfile` — final name per design), `security/chromium-seccomp.json`, extended `.env.example`.
- **`infra/searxng/settings.yml`**: committed secret removed; the leaked value must be rotated.
- **`apps/ascend-agent/src/main/resources/application.yaml` + `application-docker.yaml`**: object-store / Postgres / Redis / Qdrant credentials become env-parameterized with dev-only fallbacks; production posture rejects fallback values at startup.
- **`AscendMemory`, `ascend-web-hunter` compose env**: Qdrant API key and Redis password wiring.
- **Docs**: `docs/DEPLOYMENT.md` extended; root `README.md` configuration/ports section updated.
- **Coordination**: the gateway must route to Keycloak once `add-auth-and-identity` lands its compose service; this change reserves the route but does not wire Keycloak. Application-level JWT auth, service tokens, tenant isolation, metering, and audit are owned by their sibling changes.
- **Coordination (presign resolution)**: the gateway-only public surface holds for RAG source downloads because `add-document-management-api` moves the client-facing download path onto the agent's authenticated `GET /api/v1/documents/{id}/content` endpoint. The S3-compatible object store therefore stays loopback-bound/unexposed like every other datastore; presigned object-store URLs, if used at all, are an in-network mechanism only and are never expected to be reachable from public clients.
- **Backwards compatibility**: local `docker compose up` from the repo root continues to bring up the full stack with all of today's `localhost:<port>` access points; the only local-dev deltas are the `.env` entries for the Desktop mount and Grafana admin password.

## Relevant Skills

- `/docker-patterns`
- `/deployment-patterns`
- `/security-review`
- `/springboot-security`
