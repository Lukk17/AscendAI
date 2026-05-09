# Deployment

Build, rebuild, and publish AscendAI services. For day-to-day Quick Start see the main [README](../README.md).

---

## Docker Compose recipes

Start application and support services:

```bash
docker-compose up -d
```

Rebuild and recreate everything:

```bash
docker compose up -d --build --force-recreate
```

Build and recreate a single service (e.g. `audio-scribe`):

```bash
docker compose up -d --no-deps --build --force-recreate <service>
```

- `<service>` is the name from `docker-compose.yaml` (e.g. `audio-scribe`).
- `--no-deps` skips linked services (database, redis, etc.).

Build only (no recreation, ignore cache):

```bash
docker compose build --no-cache
```

- `--no-cache` rebuilds images without using layer cache.

---

## Publishing Docker images

```bash
docker login
docker push lukk17/ascend-ai:v1.0.0
docker push lukk17/ascend-ai:latest
```

Tag and push individual module images the same way (e.g. `lukk17/ascend-agent:v1.0.0`).

---

## Production notes

- External prerequisites (PostgreSQL, Redis, Qdrant, MinIO) should be managed services in production — AWS ElastiCache, Qdrant Cloud, S3, RDS, etc.
- All services expose `/health` for orchestrator probes.
- See [docs/architecture/](architecture/) for the deployment view and ADRs.
