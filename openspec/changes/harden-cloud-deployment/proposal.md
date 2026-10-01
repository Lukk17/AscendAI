# Harden Cloud Deployment

## Why

The compose stack is a setup for one developer's workstation. On a cloud VM with a public IP it is a security incident. Line numbers below were checked against the files on 2026-10-01.

Services in `compose.yaml` publish their ports on every host interface: Docling with its UI enabled (`compose.yaml:14-15`, UI flag at `:25`), Unstructured (`:37-38`), ascend-ocr (`:58-59`), ascend-agent (`:121-122`), ascend-memory (`:180-181`), ascend-weather-mcp (`:239-240`), ascend-audio-scribe (`:266-267`), Prometheus (`:347-348`) and Grafana with anonymous Editor access (`:368-369`, anonymous flags at `:371-372`). In `compose.ascend-web-hunter.yaml`, ascend-web-hunter publishes `7021` on every interface (`:178-179`). SearXNG and FlareSolverr are already bound to `127.0.0.1` (`compose.ascend-web-hunter.yaml:26` and `:63`). The observability services loki, vector, otel-collector, tempo and container-metrics-exporter publish no host port today, and that must stay true.

Further problems:

- `ascend-audio-scribe` bind-mounts the owner's Desktop and a personal model cache (`compose.yaml:282-283`) and sets `MCP_FILE_URI_ROOT=/audio` (`:277`), so any caller can read Desktop files through the transcription tool.
- `ascend-web-hunter` runs with `cap_add: SYS_ADMIN` (`compose.ascend-web-hunter.yaml:208-209`) while it renders untrusted web pages.
- The SSRF allowlists of ascend-ocr and ascend-audio-scribe list loopback (`MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1` at `compose.yaml:81` and `:275`).
- Credentials are committed defaults: object store `admin`/`password` in `apps/ascend-agent/src/main/resources/application.yaml:107-108` and in the ascend-ocr result store variables (`compose.yaml:77-78`), Postgres `postgres`/`local` (`application.yaml:370-371`), the built-in login `admin`/`admin` (`application.yaml:73-74`), Redis without a password, Qdrant without an API key.
- The object store addresses are fixed: the agent uses `http://host.docker.internal:9070` with a presign address of `http://localhost:9070` (`application-docker.yaml`, `app.s3`), and ascend-ocr uses `OCR_RESULT_S3_ENDPOINT` and `OCR_RESULT_S3_PUBLIC_ENDPOINT` with the same two fixed values (`compose.yaml:74-75`).
- Prometheus runs with `--web.enable-lifecycle` (`compose.yaml:352`), an unauthenticated reload endpoint.
- `compose.yaml` has no log rotation. The `x-logging` anchor exists only in `compose.ascend-web-hunter.yaml:6-10`, and YAML anchors do not cross an `include:`.
- Everything speaks plain HTTP.

## Build order

This change runs after group A, group B and group D, and before group C (`add-auth-and-identity`, `add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`, `add-tenant-administration`, `add-tenant-policy`). It therefore does not depend on Keycloak or on any authentication code.

Moved out of this change into `add-auth-and-identity` (the agent working on that change adds them there):

- the `SECURITY_ENABLED` production guard and the `SECURITY_ENABLED` entry in `.env.example`
- the Keycloak login and token rate limits
- every Keycloak route

Keycloak is a separate service on its own host address and port. It is never routed under a path of this gateway. `add-auth-and-identity` may give it a separate site with its own host name in `gateway/Caddyfile`.

Dependency on group D: task 2.7 configures streaming for `POST /api/v1/ai/prompt/stream`, which `add-chat-streaming-and-conversations` adds. That change is built before this one, so the route exists when this change is applied.

Dependency on `add-document-management-api`: public clients download RAG sources through the agent's `GET /api/v1/documents/{id}/content`, so the object store never needs to be public.

## What Changes

- Edge gateway with TLS. A Caddy 2 service is the only service that publishes on every interface, ports 80 and 443. It gets ACME certificates for a real domain and an internal certificate for `localhost`. It routes only to `ascend-agent:9917`.
- Bind address from the environment. Every other published port becomes `"${EXPOSE_BIND:-127.0.0.1}:<host>:<container>"`. Local `docker compose up` keeps every `localhost:<port>` address. The ports already bound to `127.0.0.1` (SearXNG, FlareSolverr) move to the same form so one variable controls all of them.
- Secrets out of the tree. Postgres, Redis, Qdrant, object store, ascend-ocr result store, Grafana admin, and the built-in login (`SECURITY_USERNAME`, `SECURITY_PASSWORD`) come from `.env`. Under the `production` Spring profile the agent refuses to start while a datastore or built-in login credential still equals its development default.
- Object store addresses from the environment, and the object store is never public. The presign address variables of the agent and of ascend-ocr are set to the private address in production, because only containers on the private network follow those links.
- Personal-machine artifacts become opt-in: the Desktop mount, the model cache path and `MCP_FILE_URI_ROOT`. The ngrok tunnel moves behind a compose profile.
- `SYS_ADMIN` removed from ascend-web-hunter. A checked-in seccomp profile and `init: true` replace it.
- SSRF allowlists with no loopback default.
- Grafana requires a login, Prometheus loses the lifecycle endpoint.
- Production posture: own `x-logging` anchor in `compose.yaml`, healthchecks for the services that lack them, `condition: service_healthy` for the agent, `no-new-privileges` on every service.
- SearXNG limiter stays off by an explicit decision (design D6), so `infra/searxng/settings.yml` and its copy are not changed.
- Deployment guide: `docs/DEPLOYMENT.md` gains a section for one cloud VM per customer.

Already true in the code and not repeated by this change: `SEARXNG_SECRET` is required by compose and `infra/searxng/settings.yml` has no `secret_key`, SearXNG and FlareSolverr are bound to `127.0.0.1`, `compose.ascend-web-hunter.yaml` has its own `x-logging` anchor on every service, the ngrok image is pinned by digest, SearXNG and FlareSolverr have healthchecks, and ascend-web-hunter waits on both with `condition: service_healthy`.

## Capabilities

### New Capabilities

- `production-deployment`: network exposure model, TLS at the gateway, secrets from the environment with a production startup guard, object store privacy, personal-artifact gating, SSRF allowlist posture, container hardening, observability exposure, production runtime posture and the cloud VM guide.

### Modified Capabilities

- `ascend-agent-containerization`: the agent port becomes loopback-bound by default with public access through the gateway, `depends_on` uses `condition: service_healthy`, and `.env.example` covers the new deployment variables.

`ingestion-security` was reviewed and stays unchanged. It covers upload checks inside the agent, not deployment posture.

## Impact

- `compose.yaml`: new `gateway` service, new `x-logging` anchor applied to every service, port prefixes, Grafana environment, Prometheus command, ascend-audio-scribe volumes and `MCP_FILE_URI_ROOT`, `MCP_ALLOWED_HOSTS` and `OCR_RESULT_S3_*` from the environment, agent credentials and object store addresses passed through, new healthchecks, `depends_on` long form, `no-new-privileges`.
- `compose.ascend-web-hunter.yaml`: port prefixes, `SYS_ADMIN` removed, seccomp profile and `init: true`, ngrok profile, `REDIS_URL` password support.
- New files: `gateway/Caddyfile`, `security/chromium-seccomp.json`.
- `apps/ascend-agent/src/main/resources/application.yaml` and `application-docker.yaml`: credentials and object store addresses from the environment. New startup guard class and its tests in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/` and `src/test/java/...`.
- `.env.example`, `docs/DEPLOYMENT.md`, root `README.md`, root `AGENTS.md`.
- `apps/ascend-web-hunter/deploy-standalone/` is not changed by this change. It keeps its own documented differences.

## Relevant Skills

- `/docker-patterns`
- `/deployment-patterns`
- `/security-review`
- `/springboot-patterns`
- `/java-coding-standards`
- `/tdd-workflow`
- `/markdown-writer`
