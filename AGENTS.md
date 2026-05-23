# AGENTS.md

This file provides shared instructions to all AI coding agents working in this repository (Claude Code, Kilo Code,
OpenCode, Codex CLI). Standards and skills are imported from
[agent-standards](https://github.com/Lukk17/agent-standards).

## Skills

This project includes agent skills in `.agents/skills/`. Invoke relevant skills before starting implementation work.
Examples:

- `/code-reviewer` before reviewing code
- `/security-review` before auditing for vulnerabilities
- `/coding-standards` before writing new code
- `/tdd-workflow` before adding features or fixing bugs

Slash commands may appear as `/name` or `/name.md` in your agent's autocomplete — use whichever your agent shows.

## Subagents

This project ships 26 specialised subagents — narrow-scope agents the main session delegates to. Claude Code reads
`.claude/agents/`; OpenCode and Kilo Code both read `.opencode/agents/`. Codex CLI has no per-agent file mechanism — it
sees `AGENTS.md` plus skills only.

These files are generated artifacts pulled from agent-standards. Do **not** hand-edit them — changes will be
overwritten on the next pull. To modify a subagent permanently, edit its canonical source in the agent-standards repo
(`subagents/<name>.md`), regenerate there, and re-import.

A few of the most-used:

- `code-reviewer` — security-aware diff review before merge
- `test-automator` — write missing tests and fix failures without weakening assertions
- `security-auditor` — threat modelling, secure-coding review, compliance gap analysis
- `backend-architect` — contract-first service and API design
- `database-expert` — schema design and query / index optimisation
- `debugger` — root-cause analysis for a single failing test or runtime error
- `devops-troubleshooter` — live incident response with postmortem

Full catalogue: see the agent-standards README's "Subagents catalog" section, or list `.claude/agents/*.md` (or
`.opencode/agents/*.md`) in this project.

## MCP servers

This project may expose MCP tools (Context7 docs, MongoDB introspection, Grafana, Playwright, Chrome DevTools, Redis,
SonarQube, n8n). Check your tool list at startup and use them when they're a better fit than re-deriving the answer
from local files. Human-side setup lives in [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md).

## Working With Agents

All supported agents read this `AGENTS.md` from the project root and auto-discover skills from `.agents/skills/`.
Start your agent from the project root:

- **Claude Code** — run `claude`. Reads `.claude/CLAUDE.md`, which imports this file.
- **Kilo Code** — reads `AGENTS.md` automatically. Optional `kilo.jsonc` for extra config.
- **OpenCode** — reads `AGENTS.md` automatically. Optional `opencode.json` at project root.
- **Codex CLI** — run `codex`. Reads `AGENTS.md` automatically. Global settings in `~/.codex/config.toml`.

## Working Principles

Apply these to every task, in order. They govern *how* you work; the `coding-standards` skill governs *what the code
should look like*.

### 1. Think Before Coding

State assumptions explicitly. When the prompt is ambiguous, surface the interpretations and ask — do not pick one
silently and run with it. If a simpler approach exists, propose it before writing code. Stop and ask when genuinely
unsure — a clarifying question costs less than a wrong implementation.

### 2. Simplicity First

Write the minimum code that solves the problem.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for scenarios that cannot happen.
- If 200 lines could be 50, rewrite it.

Test: would a senior engineer call this overcomplicated? If yes, simplify.

### 3. Surgical Changes

Touch only what the task requires.

- Do not "improve" adjacent code, comments, or formatting.
- Do not refactor code that is not broken.
- Match existing style, even if you would write it differently.
- If you notice unrelated dead code, mention it — do not delete it.
- Remove imports, variables, and helpers that *your* changes orphan. Leave pre-existing dead code alone unless asked.

Test: every changed line should trace directly to the request.

### 4. Goal-Driven Execution

Define success before starting. Convert vague asks into verifiable goals:

| Instead of...       | Transform to...                                                       |
| ------------------- | --------------------------------------------------------------------- |
| "Add validation"    | "Write tests for invalid inputs, then make them pass"                 |
| "Fix the bug"       | "Write a failing test that reproduces it, then make it pass"          |
| "Refactor X"        | "Ensure tests pass before and after, behavior unchanged"              |

For multi-step work, state the plan first:

1. `<step>` → verify: `<check>`
2. `<step>` → verify: `<check>`
3. `<step>` → verify: `<check>`

Then loop until each check passes. Do not claim a task is done without running the verification.

## OpenSpec Workflow

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven development. Specs and changes
live under `openspec/`.

The full lifecycle (run inside your agent shell):

1. **Propose a change** — agent generates proposal, design, and `tasks.md` under `openspec/changes/`:
   ```text
   /opsx:propose add dark mode support
   ```
2. **Apply the code** — after reviewing/editing `tasks.md`, agent implements and checks off tasks:
   ```text
   /opsx:apply
   ```
3. **Verify and refine** — pass back logs or bug reports to refine:
   ```text
   /opsx:verify The toggle button is invisible on mobile. Fix it.
   ```
4. **Archive** — once tested, merge delta specs into `openspec/specs/` and archive the change folder:
   ```text
   /opsx:archive
   ```

Some agents render commands as `/opsx-propose.md` instead of `/opsx:propose` — both work; use what appears in your
autocomplete.

Use multiline prompts when you need to include logs or detailed context with a command.

**Approval gate:** after creating a change proposal, **always wait for explicit user approval** before starting implementation. Do NOT modify source code, configs, or any project files until the user explicitly approves the plan. This is the most important rule in the workflow.

## What This Repo Is

AscendAI is a multi-module AI orchestration platform built with Spring AI and the Model Context Protocol (MCP). It routes user prompts to multiple AI providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax) with per-request selection, extends LLM capabilities with external tools via MCP, and provides a RAG pipeline with semantic memory.

## Architecture

- **Monorepo-level**: System overview, service interactions, deployment, ADRs — in `docs/architecture/`
- **AscendAgent internals**: Component diagrams, internal arc42, module-specific ADRs — in `AscendAgent/docs/architecture/`

## Monorepo Structure

| Module | Tech Stack | Port | Role |
|---|---|---|---|
| [AscendAgent](AscendAgent/AGENTS.md) | Java 21, Spring Boot 3.5.4, Gradle | 9917 | Main API gateway, multi-provider AI, RAG pipeline, MCP client |
| [AudioScribe](AudioScribe/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7017 | MCP server for audio transcription (Whisper, OpenAI, HF) |
| [AscendWebSearch](AscendWebSearch/AGENTS.md) | Python 3.12, FastAPI, FastMCP | 7021 | MCP server for web search and scraping via SearXNG |
| [AscendMemory](AscendMemory/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7020 | Semantic memory service using mem0ai + Qdrant |
| [WeatherMCP](WeatherMCP/AGENTS.md) | Java 21, Spring Boot 3.5.4, Gradle | 9998 | MCP server for weather data |
| [PaddleOCR](PaddleOCR/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7022 | OCR service using PaddleOCR |

## External Prerequisites

These services must be running before starting docker-compose. In production they map to managed cloud services (e.g., AWS ElastiCache, Qdrant Cloud, S3).

| Service | Port(s) | Purpose |
|---|---|---|
| PostgreSQL | 5432 | Persistent metadata, chat history, ingestion state |
| Redis | 6379 | Chat history cache and session persistence |
| Qdrant | 6333 / 6334 | Vector database for RAG embeddings and semantic memory |
| MinIO | 9070 / 9071 | S3-compatible object storage for RAG document ingestion |

## Docker Compose Services

Compose is split into two project files so each forms its own group in Docker Desktop when run standalone:

- **`docker-compose.yaml`** (project `ascend-ai`) — main application stack. Top-level `include:` pulls in the scrapper file, so `docker compose up` from the repo root brings up everything (merged into one project).
- **`ascend-scrapper.docker-compose.yaml`** (project `ascend-scrapper`) — web-scraping stack. Self-contained; can be run on its own with `docker compose -f ascend-scrapper.docker-compose.yaml up`.

### `ascend-ai` (docker-compose.yaml)

| Service | Port | Purpose |
|---|---|---|
| Docling Serve | 5001 | Document conversion service |
| Unstructured API | 9080 | Document parsing for RAG pipeline |
| AscendMemory | 7020 | Semantic memory REST + MCP |
| PaddleOCR | 7022 | OCR REST + MCP |
| WeatherMCP | 9998 | Weather MCP |
| AudioScribe | 7017 | Audio transcription MCP |

### `ascend-scrapper` (ascend-scrapper.docker-compose.yaml)

| Service | Port | Purpose |
|---|---|---|
| SearXNG | 9020 | Privacy-respecting meta search engine |
| FlareSolverr | 8191 | Cloudflare bypass proxy for web scraping |
| AscendWebSearch | 7021 | Web search & scraping MCP |
| ngrok-ascend-web-search | – | Ngrok tunnel for NoVNC CAPTCHA intervention |

## How to Build and Run

```bash
# 1. Ensure external prerequisites are running (PostgreSQL :5432, Redis :6379, Qdrant :6333, MinIO :9070)

# 2. Start application and support services (the main file pulls in ascend-scrapper via `include:`)
docker compose up -d --build

# Or bring up just the scrapper stack as its own Docker Desktop group:
# docker compose -f ascend-scrapper.docker-compose.yaml up -d --build

# 3. Ensure PostgreSQL has database 'ascend_ai' (user: postgres, password: local)

# 4. Run the AscendAgent
cd AscendAgent && ./gradlew bootRun

# 5. Python services run via uvicorn or docker-compose
```

## Cross-Module Conventions

- **Java modules** (AscendAgent, WeatherMCP): Java 21, Spring Boot 3.5.4, Gradle, Spring AI 1.1.5.
- **Python modules** (AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR): FastAPI + Uvicorn, pydantic for validation, FastMCP for MCP server mode.
- All services expose a `/health` endpoint for Docker healthchecks.
- All services are containerized with Dockerfiles and wired through `docker-compose.yaml` (with `ascend-scrapper.docker-compose.yaml` included for the web-scraping stack).
- MCP servers use SSE (Server-Sent Events) or Streamable HTTP for communication with the AscendAgent.

## End-to-End Test Suite

Capability-level e2e tests for the AscendAgent live in [`AscendAgent/e2e/`](AscendAgent/e2e/README.md). Five numbered specs exercise the agent against a live stack via the Bruno collection at `docs/api/request/AscendAI/`. Each spec is paired with a tasks-template the runner copies into `e2e/testing/runs/` per execution. Pass criteria are observable behavior only — HTTP status, response body, persisted state in MinIO / Qdrant / Postgres — never log substrings. See [`AscendAgent/e2e/README.md`](AscendAgent/e2e/README.md) for the full contract and capability matrix.

## IDE Compatibility

Always output file edits using strict SEARCH/REPLACE blocks.
Ensure exact matching of existing indentation and formatting for the diff viewer to parse correctly.

## Project-Specific Skills

In addition to the generic skill list above, this project relies on these domain-specific skills. Invoke them before starting work in the matching area:

- `/springboot-patterns` or `/java-coding-standards` for Java/Spring Boot work
- `/python-patterns` or `/python-testing` for Python work
- `/docker-patterns` for Docker/compose changes
- `/api-design` for REST API design
- `/git-workflow` for branching and commit conventions
- `/database-migrations` for schema changes

Every OpenSpec change proposal must include a **Relevant Skills** section listing all skills that should be loaded before implementing. This ensures the agent always knows which domain-specific standards apply to the work at hand.
