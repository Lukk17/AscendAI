# AscendMemory Architecture Documentation

> Documented against commit `cdbb447` (branch `feat/agent-deploy-chat-history-caching-rag-attachments`),
> 2026-06-01. Claims that cannot be anchored to a source file are explicitly marked.

---

### Reading paths

Pick the path that matches your reason for being here.

| Audience | Start here |
| :------- | :--------- |
| New team member | [01 Introduction](arc42/01-introduction-and-goals.md) → [05 Building Blocks](arc42/05-building-block-view.md) → [06 Runtime](arc42/06-runtime-view.md) → [07 Deployment](arc42/07-deployment-view.md) |
| Architect / reviewer | [01 Introduction](arc42/01-introduction-and-goals.md) → [02 Constraints](arc42/02-constraints.md) → [04 Solution Strategy](arc42/04-solution-strategy.md) → [09 Decisions](arc42/09-architecture-decisions.md) → ADRs |
| Operator / on-call | [07 Deployment](arc42/07-deployment-view.md) → [11 Risks and Technical Debt](arc42/11-risks-and-technical-debt.md) → [CONFIGURATION.md](../CONFIGURATION.md) |
| Security reviewer | [02 Constraints](arc42/02-constraints.md) → [08 Crosscutting Concepts](arc42/08-crosscutting-concepts.md) → [10 Quality Requirements](arc42/10-quality-requirements.md) |

---

### Arc42 chapters

| # | Chapter | Description |
| :- | :------ | :---------- |
| 1 | [Introduction and Goals](arc42/01-introduction-and-goals.md) | Purpose, stakeholders, quality goals |
| 2 | [Constraints](arc42/02-constraints.md) | Technical and organisational constraints |
| 3 | [Context and Scope](arc42/03-context-and-scope.md) | System boundary, external interfaces |
| 4 | [Solution Strategy](arc42/04-solution-strategy.md) | Key technology choices and their rationale |
| 5 | [Building Block View](arc42/05-building-block-view.md) | Package structure, module responsibilities |
| 6 | [Runtime View](arc42/06-runtime-view.md) | Key runtime scenarios: insert, search, warmup |
| 7 | [Deployment View](arc42/07-deployment-view.md) | Docker, port map, prerequisites |
| 8 | [Crosscutting Concepts](arc42/08-crosscutting-concepts.md) | Error handling, logging, startup readiness, MCP mount order |
| 9 | [Architecture Decisions](arc42/09-architecture-decisions.md) | Summary of ADRs |
| 10 | [Quality Requirements](arc42/10-quality-requirements.md) | Availability, correctness, extensibility |
| 11 | [Risks and Technical Debt](arc42/11-risks-and-technical-debt.md) | Known issues and workarounds |
| 12 | [Glossary](arc42/12-glossary.md) | Domain vocabulary |

---

### Architecture Decision Records

| ID | Title | Status |
| :- | :---- | :----- |
| [ADR-001](decisions/ADR-001-mem0ai-as-memory-orchestrator.md) | mem0ai as memory orchestrator | Accepted |
| [ADR-002](decisions/ADR-002-qdrant-as-vector-backend.md) | Qdrant as vector backend | Accepted |
| [ADR-003](decisions/ADR-003-user-id-as-scope-boundary.md) | `user_id` as memory scope boundary | Accepted |
| [ADR-004](decisions/ADR-004-mcp-mirrors-rest-contract.md) | MCP surface mirrors the REST contract | Accepted |

Full index with date and decider fields: [decisions/README.md](decisions/README.md)

---

### Diagrams

| Diagram | Description |
| :------ | :---------- |
| [C4 Container Diagram](diagrams/container-diagram.md) | AscendMemory and its direct dependencies |
