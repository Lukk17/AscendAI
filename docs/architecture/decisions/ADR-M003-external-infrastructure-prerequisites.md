# ADR-M003: Infrastructure Services as External Prerequisites

---

### Status

Accepted (2026-04-20)

---

### Context

The [docker-compose.yaml](../../../docker-compose.yaml) originally bundled generic infrastructure (Redis, Qdrant, S3-compatible object storage, PostgreSQL) alongside application services. In production, these would be managed cloud services (AWS ElastiCache, Qdrant Cloud, S3, RDS). Bundling them in the same compose file:
1. Made local dev diverge from production topology
2. Coupled application service lifecycle to infrastructure lifecycle
3. Made it harder to share infrastructure across multiple projects

---

### Decision

Move Redis, Qdrant, S3-compatible object storage, and PostgreSQL out of [docker-compose.yaml](../../../docker-compose.yaml). They become external prerequisites that must be running before `docker-compose up`. Application services connect to them via `host.docker.internal`. Locally, the object store is provided by a self-hosted S3-compatible emulator. In production it is Amazon S3 or an equivalent managed service.

The [docker-compose.yaml](../../../docker-compose.yaml) now only contains:
- Application services: AscendMemory, AudioScribe, ascend-web-hunter, WeatherMCP, PaddleOCR
- Support services: SearXNG, FlareSolverr, Docling Serve, Unstructured API

---

### Consequences

- Positive: Local dev mirrors production: infrastructure is an external dependency
- Positive: Infrastructure can be shared across projects via a separate localDev compose
- Positive: Simpler [docker-compose.yaml](../../../docker-compose.yaml) focused on application concerns
- Negative: Additional setup step: developers must ensure infrastructure is running
