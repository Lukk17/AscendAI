# ascend-web-hunter standalone deployment

Everything needed to run the web-search and scraping stack on its own host, without the rest of the AscendAI platform. Copy this directory to the target machine, fill in three secrets, and start it.

---

### What this is

The AscendAI repository runs this stack as part of a larger platform. That development setup builds images from source, wires services into a shared observability stack, and assumes Docker Desktop on Windows.

This directory is the deployment counterpart. It pulls published images instead of building, drops everything that depends on services which are not here, and is written for Docker Engine on Linux. The two are kept deliberately different, and every difference is listed under [Differences from the development stack](#differences-from-the-development-stack) below.

Four containers run by default:

| Container | Purpose | Reachable from |
|---|---|---|
| ascend-web-hunter | The service itself. REST API and MCP server. | Host, on port 7021 |
| searxng | Meta-search engine the service queries. | Inside the stack only |
| ngrok-ascend-web-hunter | Public tunnel to the NoVNC desktop for CAPTCHA solving. | Outbound only |
| redis | Session/cookie cache, so a solved Cloudflare challenge stays solved across requests. | Inside the stack only |

---

### Prerequisites

| Requirement | Detail |
|---|---|
| Docker Engine | 20.10 or newer, with the Compose plugin |
| Redis | Bundled and starts automatically with the stack. Point at your own instead; see below. |
| Free RAM | Roughly 3.5 GB free, on top of whatever the host already uses. See [Resource footprint](#resource-footprint) |
| CPU | 2 cores is enough. CPU contention costs scraping speed, not stability. |
| Free port | 7021 on the host. Nothing else is published. |
| Ngrok account | Free tier, for the CAPTCHA-intervention tunnel |

Redis holds authentication cookies and Cloudflare clearance tokens between requests, so that a challenge solved once keeps working afterwards. Without it the service still runs, but every request starts from a cold session and `/ready` reports degraded.

This bundle ships its own Redis as a fourth container, on by default, so the bundle stays self-contained without requiring you to run one yourself. `REDIS_URL` already defaults to this bundled instance, so nothing else needs setting: the plain quick-start command below is enough. Where Redis actually lives determines what `REDIS_URL` must be if you want something other than the bundled default:

| Redis location | REDIS_URL | Note |
|---|---|---|
| Bundled in this stack (default) | `redis://redis:6379/0` | The compose file's own default. Starts automatically with the stack, no flag needed. |
| On the Docker host | `redis://host.docker.internal:6379/0` | Works because the file declares `host.docker.internal:host-gateway`. Redis must listen on an address other than loopback, since the container arrives through the bridge gateway rather than through 127.0.0.1. The bundled Redis still starts by default; scale it to zero if you don't want it running unused: `docker compose up -d --scale redis=0`. |
| Another machine | `redis://<host>:6379/0` | Add a password to the URL if that Redis has one. Scale the bundled Redis to zero as above if you don't want it running unused. |

---

### Quick start

Copy this whole directory to the host. It needs all four files, including `searxng/settings.yml`, which SearXNG will not start without.

Updating an existing deployment that still has the old `docker-compose.yaml` from before this bundle was renamed to `compose.yaml`? Delete that old file after copying the new one. Compose prefers `compose.yaml` and silently ignores `docker-compose.yaml` when both are present, so a leftover copy is not read, and edits made to it do nothing.

Create the secrets file from the example.

```bash
cp .env.example .env
```

Fill in all three values. What each one has to satisfy:

| Variable | Must be |
|---|---|
| SEARXNG_SECRET | At least 32 characters, unique to this deployment, and not the literal `ultrasecretkey`, which SearXNG rejects. Nothing ever types this by hand. |
| VNC_PASSWORD | 8 characters or fewer. The VNC protocol truncates anything longer, so only the first 8 count. See [NoVNC and CAPTCHA solving](#novnc-and-captcha-solving). |
| NGROK_AUTHTOKEN | Your account token from [the ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken). |

Start the stack.

```bash
docker compose up -d
```

All three secrets are required. Compose refuses to start and names the missing variable if any is blank, so a typo fails immediately instead of producing a half-working stack.

---

### Verifying it works

Containers come up in order. SearXNG and Redis must report healthy before ascend-web-hunter is allowed to start. That takes about 30 seconds from cold; Redis reports healthy well before that.

Watch the status until all four are up and three show healthy (ngrok has no healthcheck).

```bash
docker compose ps
```

Then ask the service itself. The readiness endpoint probes Redis and SearXNG and reports each one separately.

```bash
curl -s http://localhost:7021/ready
```

A healthy response has `"status": "ready"` and every check reading `ok`. Anything reading `error` names the dependency that is not working. Redis showing `error` with the defaults untouched should not happen, since ascend-web-hunter waits for the bundled Redis to report healthy before it starts; it usually means REDIS_URL was overridden to point somewhere unreachable, see [Prerequisites](#prerequisites).

Run a real search to confirm the whole chain works end to end.

```bash
curl -s "http://localhost:7021/api/v1/web/search?query=test"
```

The interactive API documentation at [http://localhost:7021/docs](http://localhost:7021/docs) lists every endpoint, including the page-reading and session-management routes.

---

### Configuration

Three secrets live in `.env` and nothing else should, plus one optional connection override. Everything else is set directly in `compose.yaml`, because it is configuration rather than credentials and belongs in version control where changes are visible.

| Variable | Required | What it does |
|---|---|---|
| SEARXNG_SECRET | Yes | SearXNG session-signing key. Read by SearXNG from the environment, which is why `searxng/settings.yml` has no `secret_key` entry. Generate a fresh one per deployment. |
| VNC_PASSWORD | Yes | Password for the NoVNC desktop. Turned into an encrypted x11vnc password file at container start. |
| NGROK_AUTHTOKEN | Yes | Authenticates the ngrok tunnel. |
| REDIS_URL | No | Where ascend-web-hunter's cookie/session cache lives. Defaults to the bundled Redis (`redis://redis:6379/0`); override to point at an external Redis instead. See [Prerequisites](#prerequisites). |
| WEB_HUNTER_API_PORT | No | Service port. Code default `7021` applies when unset. |
| WEB_HUNTER_HOST_PORT | No | Host port of the service. Default `7021` applies when unset. |
| API_HOST | No | Bind address. Code default `0.0.0.0` applies when unset. |
| LOG_LEVEL | No | Logging level. Code default `INFO` applies when unset. |
| LOG_FORMAT | No | Log format, `json` or `color`. Code default `json` applies when unset. |
| WEB_HUNTER_RATE_LIMIT_DEFAULT | No | Flood-protection rate limit for REST routes and MCP tools. Code default `1200/minute` applies when unset. |
| READINESS_PROBE_TIMEOUT_SECONDS | No | Seconds each readiness probe may take. Code default `3` applies when unset. |
| STARTUP_PROBE_TIMEOUT_SECONDS | No | Seconds each startup banner check may take. Code default `2` applies when unset. |
| SECURITY_HSTS_MAX_AGE_SECONDS | No | Max age of the strict-transport-security header. Code default `63072000` applies when unset. |
| WEB_HUNTER_FETCH_MAX_REDIRECT_HOPS | No | Redirect hops the URI fetch guard follows. Code default `10` applies when unset. |
| NOVNC_PUBLIC_URL | No | One base address shared by every container, the web-hunter edge proxy, with no path. Empty for one container without that proxy. |
| NOVNC_MAX_CONCURRENT_FLOWS | No | Maximum concurrent intervention windows per container. Code default `4` applies when unset. |
| NOVNC_DISPLAY_SIZE | No | Size of the shared Xvfb display as `<width>x<height>`, read by Xvfb and the service. Code default `1920x1080` applies when unset. |
| NOVNC_WINDOW_WIDTH_PX | No | Width in pixels of each intervention window. Code default `1280` applies when unset. |
| NOVNC_WINDOW_HEIGHT_PX | No | Height in pixels of each intervention window. Code default `800` applies when unset. |
| NOVNC_WINDOW_CASCADE_OFFSET_PX | No | Cascade step in pixels between intervention windows. Code default `48` applies when unset. |
| NOVNC_FLOW_LEASE_GRACE_SECONDS | No | Teardown grace added on top of the flow timeout before a held flow is reclaimed. Code default `30.0` applies when unset. |
| NOVNC_FLOW_SWEEP_INTERVAL_SECONDS | No | Interval in seconds between lease-sweeper runs. Code default `30.0` applies when unset. |
| NOVNC_FLOW_CANCEL_GRACE_SECONDS | No | Bounds reclamation and shutdown. Code default `10.0` applies when unset. |
| NOVNC_BUSY_RETRY_AFTER_SECONDS | No | Short poll interval answered in the 409 Retry-After header. Code default `30` applies when unset. |
| CHALLENGE_SCORE_THRESHOLD | No | Score at or above which a page is a wall. Code default `100` applies when unset. |
| CHALLENGE_RICH_CONTENT_WORDS | No | Extracted words at or above which the rich-content guard fires. Code default `150` applies when unset. |
| CHALLENGE_FORM_DOMINANCE_RATIO | No | Share of visible text inside forms at or above which form dominance fires. Code default `0.6` applies when unset. |
| CHALLENGE_MIN_WORDS_PER_KB | No | Extracted words per kilobyte of HTML under which thin text fires. Code default `2.0` applies when unset. |
| CHALLENGE_THIN_LINK_COUNT | No | Fewer anchors with href than this fires few links. Code default `5` applies when unset. |
| CHALLENGE_RICH_LINK_COUNT | No | At least this many anchors with href fires the many-links guard. Code default `20` applies when unset. |
| CHALLENGE_SHAPE_MAX_BYTES | No | Bounds the extraction the shape family uses. Code default `500000` applies when unset. |
| CHALLENGE_WEIGHT_DEFINITIVE_HEADER | No | Weight of the definitive_header signal. Code default `200` applies when unset. |
| CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE | No | Weight of the interstitial_structure signal. Code default `80` applies when unset. |
| CHALLENGE_WEIGHT_VENDOR_SCRIPT | No | Weight of the vendor_script signal. Code default `60` applies when unset. |
| CHALLENGE_WEIGHT_VENDOR_PRESENCE | No | Weight of the vendor_presence signal. Code default `30` applies when unset. |
| CHALLENGE_WEIGHT_STATUS_EMPTY_BODY | No | Weight of the status_empty_body signal. Code default `200` applies when unset. |
| CHALLENGE_WEIGHT_STATUS_SMALL_BODY | No | Weight of the status_small_body signal. Code default `50` applies when unset. |
| CHALLENGE_WEIGHT_STATUS_LARGE_BODY | No | Weight of the status_large_body signal. Code default `20` applies when unset. |
| CHALLENGE_WEIGHT_CAPTCHA_INPUT | No | Weight of the captcha_input signal. Code default `50` applies when unset. |
| CHALLENGE_WEIGHT_CAPTCHA_ELEMENT | No | Weight of the captcha_element signal. Code default `40` applies when unset. |
| CHALLENGE_WEIGHT_FORM_DOMINANCE | No | Weight of the form_dominance signal. Code default `40` applies when unset. |
| CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY | No | Weight of the script_only_body signal. Code default `40` applies when unset. |
| CHALLENGE_WEIGHT_THIN_TEXT | No | Weight of the thin_text signal. Code default `20` applies when unset. |
| CHALLENGE_WEIGHT_FEW_LINKS | No | Weight of the few_links signal. Code default `20` applies when unset. |
| CHALLENGE_WEIGHT_NO_ARTICLE | No | Weight of the no_article signal. Code default `20` applies when unset. |
| CHALLENGE_WEIGHT_RICH_CONTENT | No | Weight of the rich_content guard signal. Code default `-60` applies when unset. |
| CHALLENGE_WEIGHT_MANY_LINKS | No | Weight of the many_links guard signal. Code default `-20` applies when unset. |
| CHALLENGE_WEIGHT_PHRASE_TITLE | No | Weight of the phrase_title signal. Code default `60` applies when unset. |
| CHALLENGE_WEIGHT_PHRASE_BODY | No | Weight of the phrase_body signal. Code default `30` applies when unset. |
| CAMOUFOX_ENABLED | No | Route reads through the 4b-camoufox tier. Code default `true` applies when unset. |
| TIER_MEMORY_TTL_SECONDS | No | TTL in seconds for the per-domain tier memory. Code default `86400` applies when unset. |
| NETWORKIDLE_POLL_MS | No | Page-quiet poll interval in milliseconds for browser tiers. Code default `1000` applies when unset. |
| SCROLL_PAUSE_MS | No | Pause in milliseconds between two scroll steps. Code default `200` applies when unset. |
| EXTRACTION_SCHEMA_MAX_BYTES | No | Maximum size in bytes of the caller-supplied extraction schema. Code default `16384` applies when unset. |
| EXTRACTION_LLM_BASE_URL | No | Base URL of the OpenAI-compatible endpoint schema extraction calls. Empty turns the schema format off. |
| EXTRACTION_LLM_MODEL | No | Model name sent to the extraction endpoint. Empty until the operator names one. |
| EXTRACTION_LLM_API_KEY | No | API key for the extraction endpoint, read from the repository `.env` file only. Empty when unset. |
| EXTRACTION_LLM_MAX_INPUT_CHARS | No | Page text characters sent to the extraction endpoint before the cap cuts them. Code default `60000` applies when unset. |
| EXTRACTION_LLM_TIMEOUT_SECONDS | No | Timeout in seconds for one extraction model call. Code default `60` applies when unset. |
| RECIPE_TTL_SECONDS | No | TTL in seconds for a stored extraction recipe. Code default `604800` applies when unset. |
| RECIPE_SELECTOR_MAX_CHARS | No | Maximum characters of one stored CSS selector. Code default `512` applies when unset. |
| DOCUMENT_MAX_BYTES | No | Maximum bytes fetched for one routed PDF, image or audio file. Code default `52428800` applies when unset. |
| DOCLING_SERVE_URL | No | Base URL of the docling-serve document conversion service. Empty turns the PDF route off. Code default `http://docling-serve:5001` applies when unset. |
| ASCEND_OCR_URL | No | Base URL of the ascend-ocr service. Empty turns the image route off. Code default `http://ascend-ocr:7022` applies when unset. |
| OCR_ROUTE_TIMEOUT_SECONDS | No | Timeout in seconds polling one ascend-ocr job. Code default `300` applies when unset. |
| AUDIO_SCRIBE_URL | No | Base URL of the ascend-audio-scribe service. Empty turns the audio route off. Code default `http://ascend-audio-scribe:7017` applies when unset. |
| READ_CACHE_PURGE_RECONNECT_SECONDS | No | Wait in seconds between two connection attempts of the read cache purge subscriber. Code default `5` applies when unset. |
| OBJECT_STORE_S3_ENDPOINT | No | Address of the S3-compatible store. Default `http://host.docker.internal:9070` applies when unset. |
| OBJECT_STORE_S3_ACCESS_KEY | No | Access key of the S3-compatible store. Empty when unset. |
| OBJECT_STORE_S3_SECRET_KEY | No | Secret key of the S3-compatible store. Empty when unset. |
| CRAWL_MAX_SEEDS | No | Most seeds in one crawl request. Code default `20` applies when unset. |
| CRAWL_MAX_PATTERNS | No | Most include patterns and most exclude patterns in one crawl request. Code default `50` applies when unset. |
| CRAWL_MAX_DEPTH | No | Largest `max_depth` a crawl request may ask for. Code default `5` applies when unset. |
| CRAWL_DEFAULT_DEPTH | No | `max_depth` when the request has none. Code default `2` applies when unset. |
| CRAWL_MAX_PAGES | No | Largest `page_budget` a crawl request may ask for. Code default `10000` applies when unset. |
| CRAWL_DEFAULT_PAGE_BUDGET | No | `page_budget` when the request has none. Code default `100` applies when unset. |
| CRAWL_ROBOTS_OPT_OUT_DOMAINS | No | Seed domains for which `respect_robots` false is accepted. Empty by default. |
| CRAWL_RESULT_S3_BUCKET | No | Bucket of the crawl results. Code default `web-hunter-crawls` applies when unset. |
| CRAWL_RESULT_S3_PREFIX | No | Key prefix of the crawl results after the tenant prefix. Code default `crawl-results/` applies when unset. |
| CRAWL_JOB_RETENTION_SECONDS | No | Lifetime of job records, results, frontier keys and recrawl state. Code default `604800` applies when unset. |
| CRAWL_DOMAIN_CONCURRENCY | No | Pages of one domain read at once, all instances together. Code default `2` applies when unset. |
| CRAWL_DEFAULT_DELAY_SECONDS | No | Least time between two fetches of one domain. Code default `1` applies when unset. |
| CRAWL_PROXY_URL | No | Customer proxy for crawl fetches only. Empty turns it off. |
| CRAWL_CLAIM_LEASE_SECONDS | No | Lifetime of a page claim. Code default `120` applies when unset. |
| CRAWL_CLAIM_MAX_EXPIRIES | No | Claim expiries after which a URL counts as failed. Code default `2` applies when unset. |
| CRAWL_WORKER_CONCURRENCY | No | Crawl worker tasks each instance starts. Code default `4` applies when unset. |
| CRAWL_WORKER_IDLE_SECONDS | No | Wait of a worker that found nothing to claim. Code default `1` applies when unset. |
| CRAWL_POLL_AFTER_SECONDS | No | The `poll_after_seconds` hint of a crawl submission. Code default `5` applies when unset. |

The full list of tunable settings, timeouts, extraction thresholds, circuit-breaker values and so on, lives in [../docs/configuration.md](../docs/configuration.md). Every one of them can be added to the `environment:` block of the ascend-web-hunter service.

---

### NoVNC and CAPTCHA solving

When the extraction chain hits a CAPTCHA it cannot clear on its own, it escalates to a real browser running inside the container on a virtual X server, and returns HTTP 428 to the caller. You then open that browser in your own browser, through the ngrok tunnel, solve the CAPTCHA by hand, and the cookies are captured and reused.

Find the current tunnel address. Ngrok generates a new one every time the container restarts.

```bash
docker exec ngrok-ascend-web-hunter curl -s http://localhost:4040/api/tunnels
```

Opening that address prompts for the VNC password from `.env`.

Two things to understand about this. The VNC protocol truncates passwords at 8 characters, so anything longer is silently cut and the extra characters do nothing. And the tunnel is a public internet address for as long as the container runs, protected only by that 8-character password. If you do not need interactive CAPTCHA solving, the safest configuration is to not run the tunnel at all.

```bash
docker compose up -d --scale ngrok-ascend-web-hunter=0
```

---

### What does not work here, and why

Telemetry. In the full platform this service exports traces over OTLP to an OpenTelemetry collector, which feeds Tempo for traces and Grafana for viewing. None of that is in this stack, so the three `OTEL_` variables are not set here.

This is not a degraded mode. The service reads `OTEL_EXPORTER_OTLP_ENDPOINT` once at startup and, finding it unset, never initialises OpenTelemetry at all. Nothing retries, nothing logs errors, nothing waits. The application is fully functional without it.

To get traces back you would need a collector accepting OTLP over gRPC on port 4317, plus somewhere to store and view what it collects. The working configuration for all of that is in the repository root: the `otel-collector`, `tempo` and `grafana` services in `compose.yaml`, with their config files under `infra/observability/`. Add them here, then set `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` on the ascend-web-hunter service.

Metrics are a separate matter. The service exposes Prometheus metrics on its own HTTP port regardless of whether OpenTelemetry is configured, so any Prometheus that can reach port 7021 can scrape them without adding anything to this stack.

---

### Resource footprint

Every container has a hard memory and CPU ceiling. Without one, a single hostile page can drive Chromium's memory up until the kernel starts killing processes, and the kernel does not necessarily kill the container that caused it. It might kill Redis, or the SSH daemon. With a ceiling the damage is confined to the offending container, which then restarts on its own.

The shipped numbers are sized for an 8 GB host that is already running other things, which is the case this bundle was written for.

| Container | CPU limit | Memory limit | CPU reserved | Memory reserved |
|---|---|---|---|---|
| ascend-web-hunter | 1.5 | 2560M | 0.25 | 512M |
| searxng | 0.5 | 384M | 0.1 | 128M |
| ngrok-ascend-web-hunter | 0.25 | 96M | 0.05 | 32M |
| redis | 0.25 | 256M | 0.05 | 64M |

Memory ceilings total 3.3 GB, with the bundled Redis running as it does by default. Scale Redis to zero to use an external instance instead and the ceiling drops to 3.0 GB. Reservations, which is what the stack actually holds at rest, total about 0.7 GB and 0.45 CPU with the bundled Redis running, or about 0.7 GB and 0.4 CPU with it scaled to zero. Redis's own 256M ceiling is sized against its measured 46 MiB peak elsewhere on the platform (`docs/architecture/memory-budget.md`), with headroom for session growth.

Do the arithmetic before deploying. Take the host's total RAM, subtract what it already uses, and the remainder must exceed 3.3 GB, the stack's default footprint, with something left over for page cache. Scaling the bundled Redis to zero to use an external instance instead brings that down to 3.0 GB. On an 8 GB host already using 2.3 GB, that leaves 5.7 GB free, the stack can claim at most 3.3 GB of it, and over 2 GB stays spare. On a 4 GB host these numbers do not fit and the stack will start killing containers under load.

Two things interact and are easy to miss.

Shared memory counts against the limit. The ascend-web-hunter container gets a 1 GB `/dev/shm` because Chromium crashes on Docker's 64 MB default. Those pages are charged to the container's memory cgroup, so of its 2560M ceiling, up to 1 GB can be shared memory. Raise `shm_size` and you must raise the memory limit with it, or you have quietly halved the working set.

CPU limits above the core count are meaningless. On a 2-core host a container cannot exceed 2.0 no matter what the file says. The numbers above assume 2 cores. On a larger machine you can raise them, but CPU is the benign constraint: contention makes scraping slower, it does not kill anything.

To scale up on a bigger host, raise ascend-web-hunter first, since that is where Chromium runs, and raise `shm_size` alongside it.

---

### Logs

Container logs are capped at 10 MB per file with 3 files kept, so 30 MB per container and 120 MB for the stack, permanently. Docker rotates at the size limit and deletes the oldest file, with no maintenance needed.

Read them the usual way.

```bash
docker compose logs -f ascend-web-hunter
```

There is no log aggregation in this stack. The Loki and Grafana setup used in development is part of the platform's observability stack, covered under [What does not work here, and why](#what-does-not-work-here-and-why).

---

### Upgrading

Images are pinned to exact versions rather than `latest`, so a restart never silently changes what is running and you can always roll back to a version you know worked.

To move to a newer ascend-web-hunter build, change the `image:` tag on the ascend-web-hunter service, then pull and recreate.

```bash
docker compose pull ascend-web-hunter
```

```bash
docker compose up -d ascend-web-hunter
```

Published tags are listed at [hub.docker.com/r/lukk17/ascend-ai-ascend-web-hunter/tags](https://hub.docker.com/r/lukk17/ascend-ai-ascend-web-hunter/tags). The same images are published to `ghcr.io/lukk17/ascend-ai-ascend-web-hunter` if you prefer GitHub's registry. Both are public and neither needs a login to pull.

Upstream images, SearXNG and the bundled Redis, are pinned too. SearXNG ships a new build most days and its search engines break as the sites they scrape change, so it is worth bumping every few months even when nothing appears wrong.

---

### Security notes

The service has no authentication. Anything that can reach port 7021 can make it fetch arbitrary URLs. That is fine on a trusted network and not fine on an untrusted one. If the host is exposed beyond your own network, put it behind a reverse proxy with authentication rather than publishing the port directly.

SearXNG publishes no ports at all here. It is reachable only from inside the stack.

The container runs with `SYS_ADMIN` capability, which Chromium's sandbox needs. It is rendering untrusted web content with an elevated capability, which is worth knowing about even though it is the standard way to run a browser in a container.

---

### Differences from the development stack

The equivalent file in the repository root is `compose.ascend-web-hunter.yaml`. Everything below is a deliberate difference, not drift. Anything not on this list should be identical in both files.

| Topic | Development stack | This file |
|---|---|---|
| ascend-web-hunter image | Built from source with `build:` | Pulled, pinned to a published version tag |
| SearXNG port 9020 | Published on 127.0.0.1 through `SEARXNG_HOST_PORT` so the service can run natively against it | Not published |
| OTEL variables | Set, pointing at the platform collector | Absent |
| VNC_PASSWORD | Optional. Unset means an unauthenticated desktop and a warning at boot, which is acceptable because port 7900 is not published locally | Required. Compose refuses to start without it |
| NGROK_AUTHTOKEN | Optional | Required |
| host.docker.internal | Declared, though Docker Desktop would provide it anyway | Declared, and required, because Docker Engine on Linux does not provide it |
| Resource limits | Sized for a development workstation, 4G for ascend-web-hunter | Sized for an 8 GB host with other workloads on it, 2560M for ascend-web-hunter |
| shm_size | 2gb | 1gb, to fit inside the smaller memory ceiling |
| REDIS_URL default | `redis://host.docker.internal:6379/0`, the development machine's own external-prerequisite Redis | `redis://redis:6379/0`, the bundled Redis below, since this bundle is meant to be self-contained |
| redis service activation | Gated behind the `redis` Compose profile: off by default, since this host already runs its own Redis as an external prerequisite and a second instance would split session data | Runs unconditionally: this bundle has no external Redis to fall back to, so it must always be present for the bundle to stay self-contained |
| ascend-web-hunter `depends_on` redis | Absent. Compose refuses to resolve a `depends_on` that crosses a profile boundary, so a profiled `redis` cannot be a dependency here | Present, `condition: service_healthy`, now that the profile boundary is gone. Costs no measurable startup time, since Redis's health arrives well before searxng's |
| redis service `container_name` | `ascend-scrapper-redis`, to avoid colliding with the development machine's own pre-existing `redis` container | `redis`, matching every other service in this file; no such collision exists on this bundle's target host |
| redis service volume | None. The profile is meant for occasional local testing of this bundle, and the development machine's own Redis already persists its own data | `redisdata`, since a lost session here means a human re-solving every Cloudflare challenge by hand |
| ALLOWED_PRIVATE_HOSTS | Passed from `WEB_HUNTER_ALLOWED_PRIVATE_HOSTS`, empty by default and set only by the start command of an end-to-end sweep | Absent. The bundle passes no allow list to the service |
| MCP_ALLOWED_HOST_HEADERS | Passed from `WEB_HUNTER_MCP_ALLOWED_HOST_HEADERS`, `ascend-web-hunter,localhost,127.0.0.1` by default, which fills `MCP_ALLOWED_HOST_HEADERS` of the container. Set it when callers reach the service under another host name | Same. Override it in the bundle `.env` when the machine's own host name must reach `/mcp` |

---

### Keeping this directory in sync

`searxng/settings.yml` here is a copy of `infra/searxng/settings.yml` in the repository root, kept byte-identical on purpose so that a diff is the whole check.

```bash
diff searxng/settings.yml ../../../infra/searxng/settings.yml
```

That command printing nothing means they match. When you change one, change the other in the same commit.

The same applies to environment variables. Adding one to the scrapper stack means adding it to `.env.example` here as well as the one in the repository root, and to the table under [Configuration](#configuration).

---

### Related documentation

- [ascend-web-hunter README](../README.md), what the service does and how it is built
- [Configuration reference](../docs/configuration.md), every setting the service accepts
- [Running locally](../docs/running.md), development without containers
- [Platform deployment guide](../../../docs/DEPLOYMENT.md), the full AscendAI stack
