# AscendWebSearch — Architecture Documentation

> As of commit `cdbb447` (2026-05-31). Code SHA is the anchor; treat anything older with suspicion.

---

### Reading paths

| Audience | Start here |
| :--- | :--- |
| New contributor | [01 Introduction](arc42/01-introduction-and-goals.md), [04 Solution strategy](arc42/04-solution-strategy.md), [05 Building blocks](arc42/05-building-block-view.md) |
| Architect / reviewer | [02 Constraints](arc42/02-constraints.md), [03 Context](arc42/03-context-and-scope.md), [09 ADR index](arc42/09-architecture-decisions.md), [11 Risks](arc42/11-risks-and-technical-debt.md) |
| Operator (incident response) | [07 Deployment](arc42/07-deployment-view.md), [06 Runtime](arc42/06-runtime-view.md), [04 Solution strategy](arc42/04-solution-strategy.md) |
| Security reviewer | [ADR-001](decisions/ADR-001-multi-tier-extraction-strategy.md), [ADR-002](decisions/ADR-002-cloudflare-cookie-persistence-redis.md), [ADR-003](decisions/ADR-003-novnc-ngrok-captcha-intervention.md), [10 Quality requirements](arc42/10-quality-requirements.md) |

---

### Arc42 chapters

| # | Chapter | One-line summary |
| :--- | :--- | :--- |
| 1 | [Introduction and goals](arc42/01-introduction-and-goals.md) | What the service does and who depends on it |
| 2 | [Constraints](arc42/02-constraints.md) | Python 3.12, Playwright base image, single-process, external service dependencies |
| 3 | [Context and scope](arc42/03-context-and-scope.md) | AscendAgent caller, SearXNG, FlareSolverr, Ngrok, Redis |
| 4 | [Solution strategy](arc42/04-solution-strategy.md) | Dual surface, ordered strategy chain, 428 human-intervention protocol |
| 5 | [Building block view](arc42/05-building-block-view.md) | Module map: api, reader, search, validator, config |
| 6 | [Runtime view](arc42/06-runtime-view.md) | Search path, extraction escalation, NoVNC trigger |
| 7 | [Deployment view](arc42/07-deployment-view.md) | docker-compose placement, env-var surface, Ngrok wiring |
| 8 | [Crosscutting concepts](arc42/08-crosscutting-concepts.md) | Logging, SSRF guard, blocklist, content validation |
| 9 | [Architecture decisions](arc42/09-architecture-decisions.md) | Index linking to ADRs |
| 10 | [Quality requirements](arc42/10-quality-requirements.md) | Security posture, observability targets, test coverage |
| 11 | [Risks and technical debt](arc42/11-risks-and-technical-debt.md) | Cloudflare drift, NoVNC reliability, Redis single point |
| 12 | [Glossary](arc42/12-glossary.md) | Domain vocabulary |

---

### ADRs

| ID | Title | Status |
| :--- | :--- | :--- |
| [ADR-001](decisions/ADR-001-multi-tier-extraction-strategy.md) | Multi-tier extraction strategy: six strategies in fixed escalation order | Accepted |
| [ADR-002](decisions/ADR-002-cloudflare-cookie-persistence-redis.md) | Cloudflare cookie persistence in Redis | Accepted |
| [ADR-003](decisions/ADR-003-novnc-ngrok-captcha-intervention.md) | NoVNC + Ngrok for human CAPTCHA and login-wall intervention | Accepted |
| [ADR-004](decisions/ADR-004-searxng-meta-search-backend.md) | SearXNG as the meta-search backend | Accepted |

For monorepo-level decisions see [docs/architecture/decisions/](../../../../docs/architecture/decisions/).

---

### Diagrams

| Diagram | File |
| :--- | :--- |
| C4 container diagram | [diagrams/container-diagram.md](diagrams/container-diagram.md) |
| Extraction escalation sequence | [diagrams/container-diagram.md](diagrams/container-diagram.md#extraction-strategy-escalation) |
