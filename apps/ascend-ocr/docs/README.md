# ascend-ocr Documentation

*Architecture index for the ascend-ocr service. Operational docs and dev commands live in the top-level
[README.md](../README.md).*

---

### Layout

```text
docs/
  README.md                        this index
  architecture/
    decisions/                     ADRs in lightweight Markdown
    arc42/                         twelve-chapter arc42 walkthrough
    diagrams/                      Mermaid diagrams referenced from arc42
```

---

### Architecture Decision Records

| ID                                                                                                 | Decision                                                                          |
| :------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------- |
| [ADR-001](architecture/decisions/ADR-001-mcp-file-transport-uri-only.md)                           | MCP file transport. URI only with SSRF guard and `file://` jail.                  |
| [ADR-002](architecture/decisions/ADR-002-mcp-error-catalog.md)                                     | Error code catalog shared by REST and MCP. Locale-neutral `detail`. RFC 7807 deviation. |
| [ADR-003](architecture/decisions/ADR-003-versioning-strategy.md)                                   | URL versioning for REST. Tool-name versioning for MCP. `schema_version` field.    |
| [ADR-004](architecture/decisions/ADR-004-liveness-readiness-split.md)                              | `/health` (liveness) and `/ready` (readiness) serve different audiences.          |
| [ADR-005](architecture/decisions/ADR-005-fixed-pdf-render-resolution.md)                           | The fixed 144 dpi PDF rendering resolution is accepted, recorded, and not exposed. |
| [ADR-006](architecture/decisions/ADR-006-detector-input-bound.md)                                  | Bound what text detection sees, measured against real documents.                  |
| [ADR-007](architecture/decisions/ADR-007-explicit-ocr-model-selection.md)                          | Name the OCR models explicitly and key the engine cache by the pair.              |
| [ADR-008](architecture/decisions/ADR-008-every-request-is-a-job.md)                                | Every request is a job, at every length, on both surfaces.                        |
| [ADR-009](architecture/decisions/ADR-009-results-in-object-storage.md)                             | A finished result is a Markdown file in object storage.                           |
| [ADR-010](architecture/decisions/ADR-010-quality-modes-and-service-side-rendering.md)              | Render pages in the service, two locked quality modes, and a page allowance per engine. |
| [ADR-011](architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md)                 | Name every preprocessing step, straighten only on request, classify each text line on its own. |

The [architecture/decisions/README.md](architecture/decisions/README.md) lists the same set with status flags.

---

### Arc42 walkthrough

Each chapter is short and self-contained. Read them in order on first contact with the service.

| Chapter                                                                                           | Topic                                          |
| :------------------------------------------------------------------------------------------------ | :--------------------------------------------- |
| [01](architecture/arc42/01-introduction-and-goals.md)                                             | Introduction and goals                         |
| [02](architecture/arc42/02-constraints.md)                                                        | Constraints                                    |
| [03](architecture/arc42/03-context-and-scope.md)                                                  | System context                                 |
| [04](architecture/arc42/04-solution-strategy.md)                                                  | Solution strategy                              |
| [05](architecture/arc42/05-building-block-view.md)                                                | Building-block view                            |
| [06](architecture/arc42/06-runtime-view.md)                                                       | Runtime view (cold start, submit-poll-collect, MCP) |
| [07](architecture/arc42/07-deployment-view.md)                                                    | Deployment view                                |
| [08](architecture/arc42/08-crosscutting-concepts.md)                                              | Crosscutting concepts                          |
| [09](architecture/arc42/09-architecture-decisions.md)                                             | Decisions index                                |
| [10](architecture/arc42/10-quality-requirements.md)                                               | Quality requirements                           |
| [11](architecture/arc42/11-risks-and-technical-debt.md)                                           | Risks and technical debt                       |
| [12](architecture/arc42/12-glossary.md)                                                           | Glossary                                       |

---

### Diagrams

The [architecture/diagrams/container-diagram.md](architecture/diagrams/container-diagram.md) page carries the C4
container diagram and the MCP happy-path runtime sequence, both including the result bucket. Both are Mermaid; GitHub
renders them inline.

---

### Where else to look

Operational docs sit one directory up:

- [../README.md](../README.md) for commands and quick start
- [../AGENTS.md](../AGENTS.md) for the AI-agent contract
- [../e2e/README.md](../e2e/README.md) for the e2e capability matrix and the Bruno tie-in
- [../e2e/load/README.md](../e2e/load/README.md) for the k6 load profile
- [../tests/contract/test_ascend_agent_pact.py](../tests/contract/test_ascend_agent_pact.py) for the Pact provider
  verification of the contract ascend-agent records against ascend-ocr
