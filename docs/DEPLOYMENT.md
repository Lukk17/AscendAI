# Deployment

Build, rebuild, and publish AscendAI services. For day-to-day Quick Start see the main [README](../README.md).

---

### Docker Compose recipes

The stack is split across two project files:

- [docker-compose.yaml](../docker-compose.yaml). Project `ascend-ai`. Includes
  [ascend-scrapper.docker-compose.yaml](../ascend-scrapper.docker-compose.yaml) via the top-level `include:` directive,
  so a single `docker compose up` from the repo root brings up the full stack (merged into the `ascend-ai` project;
  one group in Docker Desktop).
- [ascend-scrapper.docker-compose.yaml](../ascend-scrapper.docker-compose.yaml). Project `ascend-scrapper`.
  Web-scraping stack (`searxng`, `flaresolverr`, `ascend-web-search`, `ngrok-ascend-web-search`). Self-contained and
  runnable on its own; when run standalone it forms its own group in Docker Desktop.

#### Bring up the full stack

Bash:

```bash
docker compose up -d --build
```

PowerShell:

```powershell
docker compose up -d --build
```

#### Bring up only the scrapper stack

Bash:

```bash
docker compose -f ascend-scrapper.docker-compose.yaml up -d --build
```

PowerShell:

```powershell
docker compose -f ascend-scrapper.docker-compose.yaml up -d --build
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

`<service>` is the name from either compose file (e.g. `audio-scribe`, `ascend-web-search`). `--no-deps` skips linked
services (database, redis, etc.). For services in the scrapper file you can target them through the merged invocation
above (because of `include:`) or with `-f ascend-scrapper.docker-compose.yaml`.

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

---

### Publishing Docker images

Bash:

```bash
docker login
```

```bash
docker push lukk17/ascend-ai:v1.0.0
```

```bash
docker push lukk17/ascend-ai:latest
```

PowerShell:

```powershell
docker login
```

```powershell
docker push lukk17/ascend-ai:v1.0.0
```

```powershell
docker push lukk17/ascend-ai:latest
```

Tag and push individual module images the same way (e.g. `lukk17/ascend-agent:v1.0.0`).

---

### Production notes

- External prerequisites (PostgreSQL, Redis, Qdrant, MinIO) should be managed services in production. AWS
  ElastiCache, Qdrant Cloud, S3, RDS, etc.
- All services expose `/health` for orchestrator probes.
- See [docs/architecture/](architecture/) for the deployment view and ADRs.

---

### See also

- [../README.md](../README.md). Monorepo overview, Quick Start, ports.
- [INGESTION.md](INGESTION.md). Document ingestion lifecycle.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Reset recipes when state gets stuck.
- [architecture/arc42/04-deployment.md](architecture/arc42/04-deployment.md). Arc42 deployment view.
