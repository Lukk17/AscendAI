# 2. Constraints

---

### Technical constraints

| Constraint                       | Rationale                                                                                |
| :------------------------------- | :--------------------------------------------------------------------------------------- |
| Java 21+ with Virtual Threads    | High-throughput concurrent prompt handling without thread-pool tuning.                   |
| Spring Boot 3.x + Spring AI 1.x  | Unified abstraction over chat models, embeddings, MCP clients.                           |
| PostgreSQL                       | Persistent chat history, metadata store, Spring Integration JDBC.                        |
| Redis                            | Distributed chat history cache with TTL-based eviction.                                  |
| Qdrant                           | Vector store for RAG document embeddings.                                                |
| MinIO (S3-compatible)            | Object storage for uploaded documents.                                                   |
| Docker Compose                   | Local development and CI environment orchestration.                                      |

---

### Organisational constraints

| Constraint                  | Rationale                                                                                                  |
| :-------------------------- | :--------------------------------------------------------------------------------------------------------- |
| Monorepo structure          | All services (AscendAgent, MCP servers) coexist in a single Git repository.                                |
| Local-first development     | Default configuration uses LM Studio (`localhost:1234`). No API keys required for development.             |
| OpenAI-compatible endpoints | Gemini and MiniMax are accessed via their OpenAI-compatible APIs to minimise adapter code.                 |

---

### Conventions

| Convention              | Details                                                                                                       |
| :---------------------- | :------------------------------------------------------------------------------------------------------------ |
| Hexagonal architecture  | Domain logic has zero framework dependencies (except Lombok).                                                 |
| Configuration via YAML  | All environment-specific values in [application.yaml](../../../src/main/resources/application.yaml) with `${ENV_VAR:default}` patterns. |
| No hardcoded secrets    | API keys always sourced from environment variables.                                                           |
