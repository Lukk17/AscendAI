# AscendWebSearch Documentation

*Architecture index for the AscendWebSearch service. Operational docs and dev commands live in the top-level
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

| ID | Decision |
| :--- | :--- |
| [ADR-001](architecture/decisions/ADR-001-multi-tier-extraction-strategy.md) | Multi-tier extraction: six strategies in fixed escalation order, `BeautifulSoup` first, `NoVNC` last. |
| [ADR-002](architecture/decisions/ADR-002-cloudflare-cookie-persistence-redis.md) | Cloudflare cookie persistence in Redis with 2-hour TTL and in-process fallback. |
| [ADR-003](architecture/decisions/ADR-003-novnc-ngrok-captcha-intervention.md) | NoVNC + Ngrok for human CAPTCHA and login-wall intervention. Dynamic URL extraction from Ngrok API. |
| [ADR-004](architecture/decisions/ADR-004-searxng-meta-search-backend.md) | SearXNG as the sole meta-search backend. Privacy-first, self-hosted, no per-query API key. |

The [architecture/decisions/README.md](architecture/decisions/README.md) lists the same set with status flags.

---

### Arc42 walkthrough

Each chapter is short and self-contained. Read them in order on first contact with the service.

| Chapter | Topic |
| :--- | :--- |
| [01](architecture/arc42/01-introduction-and-goals.md) | Introduction and goals |
| [02](architecture/arc42/02-constraints.md) | Constraints |
| [03](architecture/arc42/03-context-and-scope.md) | System context |
| [04](architecture/arc42/04-solution-strategy.md) | Solution strategy |
| [05](architecture/arc42/05-building-block-view.md) | Building-block view |
| [06](architecture/arc42/06-runtime-view.md) | Runtime view |
| [07](architecture/arc42/07-deployment-view.md) | Deployment view |
| [08](architecture/arc42/08-crosscutting-concepts.md) | Crosscutting concepts |
| [09](architecture/arc42/09-architecture-decisions.md) | Decisions index |
| [10](architecture/arc42/10-quality-requirements.md) | Quality requirements |
| [11](architecture/arc42/11-risks-and-technical-debt.md) | Risks and technical debt |
| [12](architecture/arc42/12-glossary.md) | Glossary |

---

### Diagrams

The [architecture/diagrams/container-diagram.md](architecture/diagrams/container-diagram.md) page carries the C4
container diagram and the extraction-strategy escalation sequence. Both are Mermaid; GitHub renders them inline.

---

### Where else to look

- [../README.md](../README.md) for commands and quick start
- [../AGENTS.md](../AGENTS.md) for the AI-agent contract
