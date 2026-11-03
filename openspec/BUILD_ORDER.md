# Build order of the active OpenSpec changes

This is the build order of the active OpenSpec changes under `openspec/changes/`. The text "build group N, position K" in every change must match this file.

### The rule that decides the order

1. Finish the work that is already started.
2. Then the web-hunter changes.
3. Then the base that the assistant stands on.
4. Then the personal assistant.
5. Company work comes last.

No change in groups 1 to 4 may depend on a company change of group 5. A company change only plugs in later, through extension points that have safe defaults.

Status "started" means at least one implementation task is ticked. A change whose only ticked tasks record facts that were already true, or record owner decisions, counts as not started, and the table says so. Task counts are the `- [x]` (done) and `- [ ]` (open) lines of each `tasks.md`, last counted on 2026-10-09 for all 51 changes, after the tasks of owner answers 98 and 99 of 2026-10-08 and of owner answers 100 to 106 of 2026-10-09 were added (answer 105.2 added `add-observability` task 18.1, and answer 103.5 added the missing host settings task 2.8 of `add-openclaw-plugin-host`). Answer 106 added no task. A status note that says "recounted 2026-10-08" gives the date of its own status text, and the two count columns are those of 2026-10-09.

### Group 1: finish started work

| Position | Change | What it delivers | Status | Tasks done | Tasks open |
| --- | --- | --- | --- | --- | --- |
| 1 | `add-observability` | Metrics, logs and traces for every service, with Prometheus, Loki, Tempo and Grafana dashboards. | started (recounted 2026-10-08) | 78 | 36 |
| 2 | `add-github-actions-pipeline` | A CI pipeline with build, test and coverage gates and a manual release workflow. | started (recounted 2026-10-08) | 41 | 20 |
| 3 | `add-web-search-scraping-e2e` | End-to-end tests for web search and page extraction of ascend-web-hunter. | started, one rework task open by owner decision 90 of 2026-10-08 (recounted 2026-10-08) | 44 | 1 |
| 4 | `fix-linux-docker-host-access` | Everything in the existing setup that breaks on Linux Docker Engine is fixed, the rule is written for developers, and four findings of its audit are fixed. No test and no live run (owner answer 84.2 of 2026-10-08). | not started (added 2026-10-08, recounted 2026-10-08 after owner answer 84) | 0 | 25 |

### Group 2: web-hunter

| Position | Change | What it delivers | Status | Tasks done | Tasks open |
| --- | --- | --- | --- | --- | --- |
| 1 | `add-ascend-python-common` | One shared Python library for errors, settings, logging, tracing, rate limits and the URL guard of the four Python services. | started, built in parallel with group 1 by owner decision of 2026-10-07 (recounted 2026-10-08 after owner answers 94.2 and 94.3) | 81 | 39 |
| 2 | `add-python-runtime-upgrades` | Newer FastAPI, uvicorn, FastMCP 4 and MCP SDK 2 for the Python services. | not started (recounted 2026-10-08) | 0 | 43 |
| 3 | `open-several-novnc-windows-at-once` | Several sites can wait for human help in the remote browser at the same time. | not started (recounted 2026-10-08 after owner answers 94.4 and 95.1) | 0 | 58 |
| 4 | `detect-challenge-walls-in-any-language` | Bot challenge pages are found by a score, in any language. | not started (recounted 2026-10-08) | 0 | 70 |
| 5 | `enhance-web-search-tier-ladder` | Two new free browser tiers in the extraction ladder. | not started (its one ticked task records an owner answer, recounted 2026-10-08 after owner answer 94.6) | 1 | 29 |
| 6 | `enhance-web-search-extraction-and-tiers` | Structured data, metadata and better extraction from pages. | not started (recounted 2026-10-08) | 0 | 28 |
| 7 | `remove-flaresolverr-tier` | The FlareSolverr tier and its container are removed. | not started (its one ticked task records an owner decision, recounted 2026-10-08) | 1 | 11 |
| 8 | `add-web-session-import` | A browser login session can be imported into ascend-web-hunter. | not started (recounted 2026-10-08) | 0 | 16 |
| 9 | `enhance-web-search-crawl-at-scale` | Crawl jobs over many pages, with polling. | not started (recounted 2026-10-08) | 0 | 30 |
| 10 | `add-file-download` | ascend-web-hunter downloads files from the web and keeps them for a short time. | not started (recounted 2026-10-08) | 0 | 48 |
| 11 | `scale-web-hunter-across-containers` | ascend-web-hunter runs as several containers of one compose service behind a small edge proxy that publishes port 7021 and routes each NoVNC window to its container, in the development stack and in the standalone bundle, with one two container e2e check of every shared mechanism of the group. | not started (added 2026-10-08 by owner answer 96, fixed Ngrok domain setting `NGROK_DOMAIN` added by owner answer 97 of 2026-10-08) | 0 | 34 |

### Group 3: base

| Position | Change | What it delivers | Status | Tasks done | Tasks open |
| --- | --- | --- | --- | --- | --- |
| 1 | `close-agent-test-gaps` | Missing agent tests and the shared end-to-end harness with a scripted model and a fake MCP server. | not started | 0 | 19 |
| 2 | `upgrade-spring-boot-4` | Spring Boot 4, Spring AI 2, Flyway and RFC 7807 error bodies for the agent. | not started | 0 | 101 |
| 3 | `add-keycloak-login` | Keycloak login, the agent as an OAuth2 resource server, roles, the service token and the production login guard. | not started | 0 | 72 |
| 4 | `harden-cloud-deployment` | A TLS gateway, loopback ports, secrets from `.env`, container hardening and a cloud VM guide. | not started (its only ticked tasks are section 0 checks of facts that were already true, recounted 2026-10-08 after its task 4.1 moved to `fix-linux-docker-host-access` and owner answer 95.1 added task 2.7) | 5 | 48 |
| 5 | `scale-ocr-and-audio-across-containers` | ascend-ocr job records and queue in Redis, submitted files in object storage, ascend-audio-scribe transcript downloads in object storage, and every job visible from any container. | not started (added 2026-10-08 by owner answer 94.5) | 0 | 32 |
| 6 | `add-deployment-modules` | Switchable modules and presets, and the company extension ports with safe defaults. | not started | 0 | 47 |
| 7 | `add-shared-scheduler` | One shared persistent scheduler and the owner notification store. | not started | 0 | 35 |
| 8 | `add-document-management-api` | A document registry with list, read, download and delete endpoints. | not started | 0 | 63 |
| 9 | `add-chat-streaming-and-conversations` | Streamed chat answers and named conversations. | not started | 0 | 48 |

### Group 4: personal assistant

| Position | Change | What it delivers | Status | Tasks done | Tasks open |
| --- | --- | --- | --- | --- | --- |
| 1 | `add-agent-skills` | The agent loads, searches and writes skills. | not started | 0 | 58 |
| 2 | `add-agent-subagents` | Subagent definitions and background runs. | not started | 0 | 62 |
| 3 | `add-agent-sandbox` | A sandbox runner where the agent runs shell and file tools safely. | not started (its two ticked tasks record owner decisions) | 2 | 66 |
| 4 | `add-agent-soul` | A personality file, a user facts file and a context budget. | not started | 0 | 43 |
| 5 | `add-action-approvals` | Tools that wait for the owner's approval before they run. | not started | 0 | 43 |
| 6 | `add-mcp-tool-servers` | Configured outside MCP tool servers with trust levels and an egress proxy. | not started | 0 | 36 |
| 7 | `add-connector-framework` | A framework for connectors that sync outside sources into the knowledge base. | not started | 0 | 34 |
| 8 | `add-download-ingestion` | A downloaded file can be added to the knowledge base. | not started | 0 | 13 |
| 9 | `add-obsidian-vault` | An Obsidian vault is synced, searched and written by the agent. | not started | 0 | 57 |
| 10 | `add-openclaw-plugin-host` | Chat platforms such as Telegram and Slack through OpenClaw plugins. | not started | 0 | 79 |
| 11 | `add-coding-agent-delegation` | The agent hands coding tasks to a coding agent in the sandbox. | not started (its one ticked task records owner decisions) | 1 | 51 |
| 12 | `add-scheduled-tasks` | Jobs the assistant runs at a set time or on a schedule. | not started | 0 | 36 |
| 13 | `add-self-improvement` | The agent reviews its own work and proposes improvements. | not started | 0 | 55 |
| 14 | `add-self-built-integrations` | The agent builds, tests and runs small integrations of its own. | not started (its one ticked task records an owner decision) | 1 | 52 |
| 15 | `add-passage-level-citations` | Answers cite the exact passage and page of a source. | not started | 0 | 49 |
| 16 | `add-web-crawl-rag-connector` | A connector that crawls a website into the knowledge base. | not started | 0 | 12 |
| 17 | `add-flutter-chat-app` | A Flutter chat app for desktop, mobile and web. | not started | 0 | 142 |

### Group 5: company, last

| Position | Change | What it delivers | Status | Tasks done | Tasks open |
| --- | --- | --- | --- | --- | --- |
| 1 | `add-auth-and-identity` | The tenant claim, company sign-in, directory groups and group principals. | not started | 0 | 44 |
| 2 | `add-tenant-isolation` | Every store is separated by tenant and by access list, and earlier data becomes tenant `default`. | not started | 0 | 81 |
| 3 | `add-tenant-policy` | Per-tenant rules for providers, models, tools and modules. | not started | 0 | 39 |
| 4 | `add-tenant-administration` | Tenant and user administration and tenant suspension. | not started | 0 | 40 |
| 5 | `add-audit-and-gdpr-compliance` | An audit log, data erasure, data export, retention and tenant delete. | not started | 0 | 100 |
| 6 | `add-usage-metering-and-quotas` | A usage ledger, quotas and per-tenant provider keys. | not started | 0 | 95 |
| 7 | `add-document-connectors` | Company document connectors such as SharePoint. | not started | 0 | 24 |
| 8 | `add-customer-stack-installer` | An installer that sets up one customer stack on a Linux server. | not started (its one ticked task records an owner decision) | 1 | 41 |
| 9 | `plan-scaled-deployment` | A Kubernetes Helm chart for company deployments: a Horizontal Pod Autoscaler for the five busy services, probes from the existing health endpoints, every setting of the configuration reference as a chart value, secrets from a Kubernetes Secret, Service and Ingress in place of the gateway and the web-hunter edge proxy, the sandbox runner per node, prerequisites external or from pinned dependency charts that are off by default. Docker Compose stays for local work and single servers. | not started (added 2026-10-09 by owner answer 99.1, recounted 2026-10-09 after owner answers 103.2 and 103.3) | 0 | 30 |
| 10 | `update-docs-and-architecture` | The architecture documents and diagrams brought up to date with all changes. | not started | 0 | 25 |

### Order decisions

- 2026-10-01: the earlier order (groups A, B and D, `harden-cloud-deployment`, group C and the rest). Superseded.
- 2026-10-04: five groups, the personal assistant first and company work last, with no earlier change depending on a company change.
- 2026-10-04: `add-keycloak-login` split out of `add-auth-and-identity`, and `add-connector-framework` and `add-download-ingestion` split out of their company and web-hunter changes.
- 2026-10-06: `harden-cloud-deployment` moved from group 1 to group 3, position 4, directly after `add-keycloak-login`, because it was never started.
- 2026-10-06 (owner answer 73.4): `add-agent-sandbox`, `add-coding-agent-delegation`, `add-self-built-integrations`, `add-customer-stack-installer`, `enhance-web-search-tier-ladder` and `remove-flaresolverr-tier` count as not started. Their only ticked tasks record owner decisions or owner answers, not implementation work. The order does not change.
- 2026-10-08 (owner answer 83): the new change `fix-linux-docker-host-access` joins group 1 as position 4. It fixes everything in the existing setup that breaks on Linux Docker Engine and is implemented by the agent that implements groups 1 and 2. Groups 2 to 5 keep their positions. It takes over task 4.1 and the `extra_hosts` part of task 6.1 of `harden-cloud-deployment`.
- 2026-10-08 (owner answer 94.5): the new change `scale-ocr-and-audio-across-containers` joins group 3 as position 5, directly after `harden-cloud-deployment` (position 4), because it builds on the Redis and the runtime of group 2 and on the compose settings of `harden-cloud-deployment`, and every later change of group 3 may then rely on ascend-ocr and ascend-audio-scribe running as several containers. `add-deployment-modules` moves from position 5 to 6, `add-shared-scheduler` from 6 to 7, `add-document-management-api` from 7 to 8 and `add-chat-streaming-and-conversations` from 8 to 9. Groups 1, 2, 4 and 5 keep their positions.
- 2026-10-08 (owner answer 96): the new change `scale-web-hunter-across-containers` joins group 2 as position 11, the last change of the group, directly after `add-file-download` (position 10). The owner deploys ascend-web-hunter on its own through the standalone bundle right after group 2 and runs it as several containers, so nothing it needs may wait for group 3. It builds on the shared state of every earlier group 2 change. `harden-cloud-deployment` (group 3, position 4) reuses its edge proxy for the NoVNC site of its task 2.7. Groups 1, 3, 4 and 5 keep their positions.
- 2026-10-09 (owner answer 99.1): the new change `plan-scaled-deployment` joins group 5 as position 9, the last company change, and `update-docs-and-architecture` moves from position 9 to 10, so the documentation change still documents the Kubernetes deployment. It needs every earlier change, because the chart deploys their services with their settings, and no change of groups 1 to 4 depends on it. Groups 1 to 4 and positions 1 to 8 of group 5 keep their positions.

### How to update this file

When the order changes, edit this file first. Then change the "build group N, position K" text in every change whose position moved, and in every change that names one of those positions.
