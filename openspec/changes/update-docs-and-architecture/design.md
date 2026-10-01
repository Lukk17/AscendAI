# Design - Update Docs and Architecture

## Context

Documentation lives in `docs/architecture/` (five arc42 files, two diagrams `diagrams/system-overview.md` and `diagrams/prompt-flow.md`, monorepo decision records `ADR-M001` to `ADR-M010`), `apps/ascend-agent/docs/architecture/` (twelve arc42 files, four C4 diagrams `context-diagram.md`, `container-diagram.md`, `component-diagram.md`, `deployment-diagram.md`, decision records `ADR-001` to `ADR-010`), topic documents in `docs/`, the root and module `README.md` and `AGENTS.md` files, and the Bruno collection in `docs/api/request/AscendAI/`. No OpenAPI file is committed today, although the agent already applies the springdoc Gradle plugin (`apps/ascend-agent/build.gradle.kts:6`) and the springdoc web starter (`:84`).

## Goals / Non-Goals

Goals:

- One consistent end-state picture across every diagram, overview and cross-reference.
- Decision records for the load-bearing decisions of the consolidated changes.
- A documentation map where every link resolves.
- `AGENTS.md`, OpenAPI and Bruno matching the shipped surface.

Non-Goals:

- Application behavior changes.
- Redoing documents a sibling change already made correct.
- Marketing content.

## Decisions

### D1 - Run last, document reality, mark the pending

This change runs after every other change in the build order. The implementer starts with `openspec list` and the archive folder. Where a change has not shipped, the documents describe what exists and mark the rest with the word "Pending" and the change name. Nothing unshipped is described as shipped.

### D2 - Diagrams as Mermaid text in git

The monorepo has two diagrams. `system-overview.md` becomes the container view of the end state: the gateway as the only public entry, Keycloak on its own host address, the agent, the MCP services, ascend-ocr with its result store, the observability services, and the four external data stores. `prompt-flow.md` becomes the path of one authenticated streamed chat turn with sources served by the content endpoint. A new `document-ingestion-flow.md` shows a document from upload or connector through ingestion (Docling, Unstructured, the OCR job API) into tenant RAG. The agent's four C4 files are updated in place.

### D3 - Counts in badges, not prose

Service, endpoint and capability counts live in README badges only.

### D4 - The documentation map is the completeness check

The root README map links every shipped document. A link check makes completeness testable.

### D5 - OpenAPI generated at build time and exported

The springdoc Gradle plugin starts the application, reads `/v3/api-docs` and writes the file. An `openApi { }` block in `apps/ascend-agent/build.gradle.kts` sets `apiDocsUrl` to `http://localhost:9917/v3/api-docs`, `outputDir` to the repository's `docs/api` folder and `outputFileName` to `openapi.json`, and passes a Spring profile that starts without external services when one exists (otherwise the task runs with the local prerequisite stack up, and the task says so). `./gradlew generateOpenApiDocs` regenerates the file. The committed file is the reviewed snapshot, and a change to the API shows up as a diff of it.

## Risks / Trade-offs

- Documents drift again later. Per-change documents stay each change's job, and the map and `AGENTS.md` pass make drift visible.
- The OpenAPI task needs the application to start. D5 names the fallback.

## Open Questions

None.
