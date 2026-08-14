# AscendWebSearch standalone deployment

Everything needed to run the web-search and scraping stack on its own host, without the rest of the AscendAI platform. Copy this directory to the target machine, fill in three secrets, and start it.

---

### What this is

The AscendAI repository runs this stack as part of a larger platform. That development setup builds images from source, wires services into a shared observability stack, and assumes Docker Desktop on Windows.

This directory is the deployment counterpart. It pulls published images instead of building, drops everything that depends on services which are not here, and is written for Docker Engine on Linux. The two are kept deliberately different, and every difference is listed under [Differences from the development stack](#differences-from-the-development-stack) below.

Four containers run:

| Container | Purpose | Reachable from |
|---|---|---|
| ascend-web-search | The service itself. REST API and MCP server. | Host, on port 7021 |
| searxng | Meta-search engine the service queries. | Inside the stack only |
| flaresolverr | Cloudflare challenge solver, runs its own Chrome. | Inside the stack only |
| ngrok-ascend-web-search | Public tunnel to the NoVNC desktop for CAPTCHA solving. | Outbound only |

---

### Prerequisites

| Requirement | Detail |
|---|---|
| Docker Engine | 20.10 or newer, with the Compose plugin |
| Redis | Reachable at port 6379. Not part of this stack. |
| Free RAM | Roughly 4.5 GB free, on top of whatever the host already uses. See [Resource footprint](#resource-footprint) |
| CPU | 2 cores is enough. CPU contention costs scraping speed, not stability. |
| Free port | 7021 on the host. Nothing else is published. |
| Ngrok account | Free tier, for the CAPTCHA-intervention tunnel |

Redis holds authentication cookies and Cloudflare clearance tokens between requests, so that a challenge solved once keeps working afterwards. Without it the service still runs, but every request starts from a cold session and `/ready` reports degraded.

Where Redis lives determines what `REDIS_URL` must be. The compose file ships with the first option below.

| Redis location | REDIS_URL | Note |
|---|---|---|
| On the Docker host | `redis://host.docker.internal:6379/0` | Works because the file declares `host.docker.internal:host-gateway`. Redis must listen on an address other than loopback, since the container arrives through the bridge gateway rather than through 127.0.0.1. |
| A container on this compose network | `redis://<service-name>:6379/0` | Add the service to this file and drop the `extra_hosts` entry. |
| Another machine | `redis://<host>:6379/0` | Add a password to the URL if that Redis has one. |

---

### Quick start

Copy this whole directory to the host. It needs all four files, including `searxng/settings.yml`, which SearXNG will not start without.

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

Containers come up in order. SearXNG and FlareSolverr must report healthy before ascend-web-search is allowed to start, which takes about 30 to 60 seconds from cold because FlareSolverr has to launch Chrome.

Watch the status until all four are up and the first three show healthy.

```bash
docker compose ps
```

Then ask the service itself. The readiness endpoint probes Redis, SearXNG and FlareSolverr and reports each one separately.

```bash
curl -s http://localhost:7021/ready
```

A healthy response has `"status": "ready"` and every check reading `ok`. Anything reading `error` names the dependency that is not working. Redis showing `error` is the usual first failure and means the container cannot reach Redis on the host, see [Prerequisites](#prerequisites).

Run a real search to confirm the whole chain works end to end.

```bash
curl -s "http://localhost:7021/api/v1/web/search?query=test"
```

The interactive API documentation at [http://localhost:7021/docs](http://localhost:7021/docs) lists every endpoint, including the page-reading and session-management routes.

---

### Configuration

Three secrets live in `.env` and nothing else should. Everything else is set directly in `docker-compose.yaml`, because it is configuration rather than credentials and belongs in version control where changes are visible.

| Variable | Required | What it does |
|---|---|---|
| SEARXNG_SECRET | Yes | SearXNG session-signing key. Read by SearXNG from the environment, which is why `searxng/settings.yml` has no `secret_key` entry. Generate a fresh one per deployment. |
| VNC_PASSWORD | Yes | Password for the NoVNC desktop. Turned into an encrypted x11vnc password file at container start. |
| NGROK_AUTHTOKEN | Yes | Authenticates the ngrok tunnel. |

The full list of tunable settings, timeouts, extraction thresholds, circuit-breaker values and so on, lives in [../docs/configuration.md](../docs/configuration.md). Every one of them can be added to the `environment:` block of the ascend-web-search service.

---

### NoVNC and CAPTCHA solving

When the extraction chain hits a CAPTCHA it cannot clear on its own, it escalates to a real browser running inside the container on a virtual X server, and returns HTTP 428 to the caller. You then open that browser in your own browser, through the ngrok tunnel, solve the CAPTCHA by hand, and the cookies are captured and reused.

Find the current tunnel address. Ngrok generates a new one every time the container restarts.

```bash
docker exec ngrok-ascend-web-search curl -s http://localhost:4040/api/tunnels
```

Opening that address prompts for the VNC password from `.env`.

Two things to understand about this. The VNC protocol truncates passwords at 8 characters, so anything longer is silently cut and the extra characters do nothing. And the tunnel is a public internet address for as long as the container runs, protected only by that 8-character password. If you do not need interactive CAPTCHA solving, the safest configuration is to not run the tunnel at all.

```bash
docker compose up -d --scale ngrok-ascend-web-search=0
```

---

### What does not work here, and why

Telemetry. In the full platform this service exports traces over OTLP to an OpenTelemetry collector, which feeds Tempo for traces and Grafana for viewing. None of that is in this stack, so the three `OTEL_` variables are not set here.

This is not a degraded mode. The service reads `OTEL_EXPORTER_OTLP_ENDPOINT` once at startup and, finding it unset, never initialises OpenTelemetry at all. Nothing retries, nothing logs errors, nothing waits. The application is fully functional without it.

To get traces back you would need a collector accepting OTLP over gRPC on port 4317, plus somewhere to store and view what it collects. The working configuration for all of that is in the repository root: the `otel-collector`, `tempo` and `grafana` services in `docker-compose.yaml`, with their config files under `observability/`. Add them here, then set `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` on the ascend-web-search service.

Metrics are a separate matter. The service exposes Prometheus metrics on its own HTTP port regardless of whether OpenTelemetry is configured, so any Prometheus that can reach port 7021 can scrape them without adding anything to this stack.

---

### Resource footprint

Every container has a hard memory and CPU ceiling. Without one, a single hostile page can drive Chromium's memory up until the kernel starts killing processes, and the kernel does not necessarily kill the container that caused it. It might kill Redis, or the SSH daemon. With a ceiling the damage is confined to the offending container, which then restarts on its own.

The shipped numbers are sized for an 8 GB host that is already running other things, which is the case this bundle was written for.

| Container | CPU limit | Memory limit | CPU reserved | Memory reserved |
|---|---|---|---|---|
| ascend-web-search | 1.5 | 2560M | 0.25 | 512M |
| flaresolverr | 1.0 | 1280M | 0.15 | 256M |
| searxng | 0.5 | 384M | 0.1 | 128M |
| ngrok-ascend-web-search | 0.25 | 96M | 0.05 | 32M |

Memory ceilings total 4.2 GB. Reservations, which is what the stack actually holds at rest, total about 0.9 GB and 0.55 CPU.

Do the arithmetic before deploying. Take the host's total RAM, subtract what it already uses, and the remainder must exceed 4.2 GB with something left over for page cache. On an 8 GB host already using 2.3 GB, that leaves 5.7 GB free, the stack can claim at most 4.2 GB of it, and roughly 1.5 GB stays spare. On a 4 GB host these numbers do not fit and the stack will start killing containers under load.

Two things interact and are easy to miss.

Shared memory counts against the limit. The ascend-web-search container gets a 1 GB `/dev/shm` because Chromium crashes on Docker's 64 MB default. Those pages are charged to the container's memory cgroup, so of its 2560M ceiling, up to 1 GB can be shared memory. Raise `shm_size` and you must raise the memory limit with it, or you have quietly halved the working set.

CPU limits above the core count are meaningless. On a 2-core host a container cannot exceed 2.0 no matter what the file says. The numbers above assume 2 cores. On a larger machine you can raise them, but CPU is the benign constraint: contention makes scraping slower, it does not kill anything.

To scale up on a bigger host, raise ascend-web-search first, since that is where Chromium runs, and raise `shm_size` alongside it.

---

### Logs

Container logs are capped at 10 MB per file with 3 files kept, so 30 MB per container and 120 MB for the stack, permanently. Docker rotates at the size limit and deletes the oldest file, with no maintenance needed.

Read them the usual way.

```bash
docker compose logs -f ascend-web-search
```

There is no log aggregation in this stack. The Loki and Grafana setup used in development is part of the platform's observability stack, covered under [What does not work here, and why](#what-does-not-work-here-and-why).

---

### Upgrading

Images are pinned to exact versions rather than `latest`, so a restart never silently changes what is running and you can always roll back to a version you know worked.

To move to a newer AscendWebSearch build, change the `image:` tag on the ascend-web-search service, then pull and recreate.

```bash
docker compose pull ascend-web-search
```

```bash
docker compose up -d ascend-web-search
```

Published tags are listed at [hub.docker.com/r/lukk17/ascend-web-search/tags](https://hub.docker.com/r/lukk17/ascend-web-search/tags). The same images are published to `ghcr.io/lukk17/ascend-web-search` if you prefer GitHub's registry. Both are public and neither needs a login to pull.

Upstream images, SearXNG and FlareSolverr, are pinned too. SearXNG ships a new build most days and its search engines break as the sites they scrape change, so it is worth bumping every few months even when nothing appears wrong.

---

### Security notes

The service has no authentication. Anything that can reach port 7021 can make it fetch arbitrary URLs. That is fine on a trusted network and not fine on an untrusted one. If the host is exposed beyond your own network, put it behind a reverse proxy with authentication rather than publishing the port directly.

SearXNG and FlareSolverr publish no ports at all here. They are reachable only from inside the stack. FlareSolverr in particular will fetch any URL handed to it, so exposing it to a wider network hands out a request-forwarding tool.

The container runs with `SYS_ADMIN` capability, which Chromium's sandbox needs. It is rendering untrusted web content with an elevated capability, which is worth knowing about even though it is the standard way to run a browser in a container.

---

### Differences from the development stack

The equivalent file in the repository root is `ascend-scrapper.docker-compose.yaml`. Everything below is a deliberate difference, not drift. Anything not on this list should be identical in both files.

| Topic | Development stack | This file |
|---|---|---|
| ascend-web-search image | Built from source with `build:` | Pulled, pinned to a published version tag |
| SearXNG port 9020 | Published on 127.0.0.1 so the service can run natively against it | Not published |
| FlareSolverr port 8191 | Published on 127.0.0.1 for the same reason | Not published |
| OTEL variables | Set, pointing at the platform collector | Absent |
| VNC_PASSWORD | Optional. Unset means an unauthenticated desktop and a warning at boot, which is acceptable because port 7900 is not published locally | Required. Compose refuses to start without it |
| NGROK_AUTHTOKEN | Optional | Required |
| host.docker.internal | Declared, though Docker Desktop would provide it anyway | Declared, and required, because Docker Engine on Linux does not provide it |
| Resource limits | Sized for a development workstation, 4G for ascend-web-search | Sized for an 8 GB host with other workloads on it, 2560M for ascend-web-search |
| shm_size | 2gb | 1gb, to fit inside the smaller memory ceiling |

---

### Keeping this directory in sync

`searxng/settings.yml` here is a copy of `searxng/settings.yml` in the repository root, kept byte-identical on purpose so that a diff is the whole check.

```bash
diff searxng/settings.yml ../../searxng/settings.yml
```

That command printing nothing means they match. When you change one, change the other in the same commit.

The same applies to environment variables. Adding one to the scrapper stack means adding it to `.env.example` here as well as the one in the repository root, and to the table under [Configuration](#configuration).

---

### Related documentation

- [AscendWebSearch README](../README.md), what the service does and how it is built
- [Configuration reference](../docs/configuration.md), every setting the service accepts
- [Running locally](../docs/running.md), development without containers
- [Platform deployment guide](../../docs/DEPLOYMENT.md), the full AscendAI stack
