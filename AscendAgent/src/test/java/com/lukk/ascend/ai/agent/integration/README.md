# Integration tests

`@Tag("integration")` Spring Boot tests that boot the full context against real Postgres / Redis / Qdrant / MinIO
via Testcontainers.

---

### Run

Bash:

```bash
./gradlew integrationTest
```

PowerShell:

```powershell
.\gradlew.bat integrationTest
```

These tests are **excluded** from the default `gradle test` run. They only execute when you ask for them
explicitly.

---

### Prerequisites

- **Docker Desktop running** (not just `docker` CLI). The daemon must be reachable from the JVM.
- The active Docker context's named pipe must respond cleanly to a Docker `Info` request.

---

### Troubleshooting

#### `Could not find a valid Docker environment`

Two things to check on Windows + Docker Desktop, in order.

**1. Active Docker context must be `default`** (the `docker_engine` pipe), not `desktop-linux`. The latter proxies
through a shim that returns malformed Info structs to non-CLI Docker clients.

```powershell
docker context use default
```

**2. A stale `~/.testcontainers.properties`** can pin the wrong client strategy. If you see
`Loaded NpipeSocketClientProviderStrategy from ~/.testcontainers.properties, will try it first` in the verbose log
and the run still fails, delete or rename the file. Testcontainers auto-detects on next run.

Bash:

```bash
mv ~/.testcontainers.properties ~/.testcontainers.properties.bak
```

PowerShell:

```powershell
Move-Item ~/.testcontainers.properties ~/.testcontainers.properties.bak
```

#### `client version 1.32 is too old. Minimum supported API version is 1.40`

The bundled docker-java client is older than your daemon expects. The Testcontainers BOM in `libs.versions.toml` is
pinned to **`2.0.5`** for this reason. It ships docker-java 3.5+ which negotiates the API version correctly. If you
downgrade the BOM, you may hit this error.

#### Override the Docker host per run

For non-standard setups (TCP daemon, remote Docker, WSL2-only):

Bash:

```bash
./gradlew integrationTest -Pdocker.host=tcp://localhost:2375
```

```bash
./gradlew integrationTest -Pdocker.host=npipe:////./pipe/docker_engine
```

PowerShell:

```powershell
.\gradlew.bat integrationTest -Pdocker.host=tcp://localhost:2375
```

```powershell
.\gradlew.bat integrationTest -Pdocker.host=npipe:////./pipe/docker_engine
```

---

### What's covered

| Test class                | What it verifies                                                                                                                                                                                  |
| :------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `BackingServicesIT`       | Spring context boots end-to-end against real Postgres / Redis / Qdrant / MinIO. Liquibase migrations run, Qdrant collections (`ascendai-768`, `ascendai-1536`) get created, MinIO `knowledge-base` bucket exists, RestClient builder produces a working bean. |
| `StartupBannerIT`         | `StartupLogConfig` emits the expected banner on `AvailabilityChangeEvent<ReadinessState.ACCEPTING_TRAFFIC>`. Labels for Postgres / Redis / Qdrant / S3 / AscendMemory / MCP, a status marker per line (`[Connected]` / `[FAILED]` / `[Warning]` / `[Disabled]`), the `MAIN PROMPT ENDPOINT` line, and the mapped `/api/v1/ai/prompt` path. Also asserts the listener early-returns for non-`ACCEPTING_TRAFFIC` states. |
| `VectorStoreConfigIT`     | Multi-provider vector-store routing wired correctly: with `app.embedding.default-provider=lmstudio` the active store maps to `ascendai-768`; with `=openai` it maps to `ascendai-1536`. Validates `VectorStoreResolver` round-trips through the per-provider bean map. |
| `IngestionEndToEndIT`     | Full ingestion pipeline against real MinIO + Postgres + Qdrant. Drives `POST /api/v1/ingestion/upload` for markdown / PDF / DOCX (single multipart request), asserts objects land at `markdown/<key>.md` and `documents/<key>.<ext>`, rejects disallowed MIME types with `415` + `ApiError`, sanitises traversal filenames (`../../etc/passwd.md`), runs `POST /api/v1/ingestion/run` and asserts `INT_METADATA_STORE` rows are persisted in Postgres and the resolved vector store receives chunk writes, and proves the run is idempotent across repeated invocations (no double-write of metadata or vectors). The embedding model is stubbed via `@MockitoBean VectorStoreResolver` because LM Studio / OpenAI are unreachable in CI. |

More IT classes are planned. See the OpenSpec `add-integration-tests` change once it's drafted.

---

### Why this matters

The `config/` package was at 52% line coverage before these tests existed because every `@Bean` factory in
`AppConfig` (S3 client, RestClient, JDBC metadata store, Qdrant init runner) only runs when a real Spring context
starts with real backing services. Mock-based unit tests can't reach them. These tests close that gap honestly.
