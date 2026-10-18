# Deployment

Build, rebuild, and publish AscendAI services. For day-to-day Quick Start see the main [README](../README.md).

---

### Docker Compose recipes

The stack is split across two project files:

- [compose.yaml](../compose.yaml). Project `ascend-ai`. Includes
  [compose.ascend-web-hunter.yaml](../compose.ascend-web-hunter.yaml) via the top-level `include:` directive,
  so a single `docker compose up` from the repo root brings up the full stack (merged into the `ascend-ai` project;
  one group in Docker Desktop).
- [compose.ascend-web-hunter.yaml](../compose.ascend-web-hunter.yaml). Project `ascend-scrapper`.
  Web-scraping stack (`searxng`, `flaresolverr`, `ascend-web-hunter`, `ngrok-ascend-web-hunter`), pulled in by the
  main file's `include:`.

A third file exists for deploying the web-search stack to a machine of its own, without the rest of the platform:
[apps/ascend-web-hunter/deploy-standalone/](../apps/ascend-web-hunter/deploy-standalone/README.md). It pulls published images rather than building, and
targets Docker Engine on Linux. It is a separate artifact on purpose and is not included by either file above. See
[Standalone web-search deployment](#standalone-web-search-deployment).

#### Required environment variables

`docker compose` reads [.env](../.env.example) from the repo root. Two variables in it are mandatory for the scrapper
stack and compose will refuse to start without them, naming the one that is missing:

- `SEARXNG_SECRET`. SearXNG's session-signing key. At least 32 characters, unique per deployment, never the literal
  `ultrasecretkey`. It replaced a `secret_key` that used to be committed in
  [infra/searxng/settings.yml](../infra/searxng/settings.yml), so that value must be treated as compromised and never reused.
- `NGROK_AUTHTOKEN`. Only when running `ngrok-ascend-web-hunter`.

`VNC_PASSWORD` is optional locally. Leaving it empty means the NoVNC desktop accepts any client and the container logs
a warning at boot, which is acceptable because port 7900 is never published outside the compose network. It is
mandatory in the standalone deployment, where ngrok puts that desktop on the public internet.

#### Bring up the full stack

Bash:

```bash
docker compose up -d --build
```

PowerShell:

```powershell
docker compose up -d --build
```

#### Rebuild and recreate everything

Bash:

```bash
docker compose up -d --build --force-recreate
```

PowerShell:

```powershell
docker compose up -d --build --force-recreate
```

#### Build and recreate a single service

`<service>` is the name from either compose file (e.g. `ascend-audio-scribe`, `ascend-web-hunter`). `--no-deps` skips linked
services (database, redis, etc.). For services in the scrapper file, target them through the merged invocation above
(because of `include:`).

Bash:

```bash
docker compose up -d --no-deps --build --force-recreate <service>
```

PowerShell:

```powershell
docker compose up -d --no-deps --build --force-recreate <service>
```

#### Build only (no recreation, ignore cache)

`--no-cache` rebuilds images without using the layer cache.

Bash:

```bash
docker compose build --no-cache
```

PowerShell:

```powershell
docker compose build --no-cache
```

#### Reaching the host from a container

A container that calls an address on the host follows five rules:

1. Container to container: the container name or the compose service name on the shared network.
2. Host to container: `127.0.0.1` and a published port.
3. Container to host: `host.docker.internal` only together with `extra_hosts: "host.docker.internal:host-gateway"` on that compose service, `--add-host=host.docker.internal:host-gateway` on a `docker run`, or `ExtraHosts` with the same value through the Docker Engine API. Needs Docker Engine 20.10 or newer.
4. Inside a container, `localhost` and `127.0.0.1` mean that container itself.
5. A `docker run` that calls no other service needs none of this.

The mapping comes from the Docker documentation. `extra_hosts` with `host-gateway` maps a name to the host, and on Linux it resolves to the host's address on the default bridge network, while Docker Desktop provides `host.docker.internal` by itself ([compose networking](https://docs.docker.com/compose/how-tos/networking/)). `--add-host` accepts the same special value ([docker run reference](https://docs.docker.com/reference/cli/docker/container/run/)). The daemon supports `host.docker.internal` on Linux since Engine 20.10.0 ([release notes](https://docs.docker.com/engine/release-notes/20.10/), moby/moby#40007). The daemon creates its Unix socket accessible by members of the `docker` group ([post-install steps](https://docs.docker.com/engine/install/linux-postinstall/)). `group_add` adds the container user to further groups by name or by number, and a name is looked up inside the container, so the host's `docker` group is added by its number ([compose file reference](https://docs.docker.com/reference/compose-file/services/)).

On Docker Engine for Linux each host prerequisite (PostgreSQL 5432, Redis 6379, Qdrant 6333, the object store 9070, LM Studio 1234) must listen on the Docker bridge address or on all addresses, because a call through `host.docker.internal` arrives at the bridge address, never at `127.0.0.1`, and a host firewall must accept the Docker bridge subnets on those ports. Concretely that means the Postgres `listen_addresses` setting, the Redis `bind` line, a container port published on `0.0.0.0` rather than `127.0.0.1`, and the LM Studio setting that serves on the local network. The GPU reservation of ascend-audio-scribe needs the NVIDIA Container Toolkit on a Linux host. The socket reader finds the group to join with one command:

```bash
stat -c %g /var/run/docker.sock
```

Put the printed number into `DOCKER_SOCKET_GID` (default `0`, the socket's group on Docker Desktop), see its [row](CONFIGURATION.md#container-metrics-exporter) in the configuration reference. The two volume sources of ascend-audio-scribe are settings too: [HF_CACHE_ROOT](CONFIGURATION.md#ascend-audio-scribe) (default `hf-cache`, the Hugging Face model cache) and [ASCEND_AUDIO_SCRIBE_MEDIA_ROOT](CONFIGURATION.md#ascend-audio-scribe) (default `ascend-audio-scribe-media`, the `/audio` mount that `MCP_FILE_URI_ROOT=/audio` jails `file://` URIs to). A plain name is a named volume and a host path is a bind mount of that folder.

---

### Publishing Docker images

Images are published by the [Release workflow](../.github/workflows/README.md), not by hand. It is dispatched manually
from Actions → Release → Run workflow, builds the selected services multi-arch (`linux/amd64,linux/arm64`), and pushes
each to four tags: `v<version>` and `latest` on Docker Hub and on GitHub Container Registry.

| Registry | Image | Login needed to pull |
|---|---|---|
| Docker Hub | `lukk17/<service>` | No. The repositories are public. |
| GHCR | `ghcr.io/lukk17/<service>` | No, once the package visibility is switched to public. |

The version comes from each service's own manifest (`build.gradle.kts` for Java, `pyproject.toml` for Python) and the
workflow refuses to release a service whose version has not changed since the previous stack tag.

GHCR packages are private when first published, even from a public repository, and no workflow setting changes that.
After a service's first release, switch it once by hand at Package settings → Danger Zone → Change visibility.

---

### Standalone web-search deployment

[apps/ascend-web-hunter/deploy-standalone/](../apps/ascend-web-hunter/deploy-standalone/README.md) is a copy-and-run bundle for putting the web-search
stack on its own host, a homelab box or a VPS, without the rest of AscendAI. It contains a compose file pinned to
published image tags, an `.env.example`, a copy of the SearXNG settings overlay, and a README covering prerequisites,
verification, resource sizing, and what is deliberately absent.

Three things differ from the development stack in a way worth knowing before deploying:

- It needs Redis on the Docker host. Redis is not part of the stack, and on Docker Engine for Linux the container only
  resolves the host through the `host.docker.internal:host-gateway` mapping the file declares.
- Telemetry is absent. The OpenTelemetry collector, Tempo, and Grafana live in the platform stack. With
  `OTEL_EXPORTER_OTLP_ENDPOINT` unset the service never initialises OpenTelemetry, so this costs nothing at runtime.
  Prometheus metrics on `/metrics` are unaffected and still exposed.
- SearXNG and FlareSolverr publish no ports. They are reachable only from inside the stack.

The bundle carries its own copy of [infra/searxng/settings.yml](../infra/searxng/settings.yml), kept byte-identical so a `diff` is
the entire sync check. Changing one means changing the other in the same commit.

---

### Production notes

- External prerequisites (PostgreSQL, Redis, Qdrant, object storage) should be managed services in production. AWS
  ElastiCache, Qdrant Cloud, Amazon S3 in place of the local object store, RDS, etc.
- All services expose `/health` for orchestrator probes.
- See [docs/architecture/](architecture/) for the deployment view and ADRs.

---

### See also

- [CONFIGURATION.md](CONFIGURATION.md). Every setting of every service.
- [../README.md](../README.md). Monorepo overview, Quick Start, ports.
- [../apps/ascend-web-hunter/deploy-standalone/README.md](../apps/ascend-web-hunter/deploy-standalone/README.md). Standalone web-search deployment.
- [../.github/workflows/README.md](../.github/workflows/README.md). CI and release workflows, image naming, registries.
- [INGESTION.md](INGESTION.md). Document ingestion lifecycle.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Reset recipes when state gets stuck.
- [architecture/arc42/04-deployment.md](architecture/arc42/04-deployment.md). Arc42 deployment view.
