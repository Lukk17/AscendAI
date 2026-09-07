# Design — update-docs-and-architecture

## Context

The platform's documentation is spread across `docs/architecture/` (monorepo arc42, C4, ADRs), `apps/ascend-ai-agent/docs/architecture/` (internal), the root and per-module `README.md` and `AGENTS.md` files, topic docs (`SECURITY.md`, `COMPLIANCE.md`, `CONNECTORS.md`, `USAGE_AND_QUOTAS.md`, `DEPLOYMENT.md`, `MCP_SETUP.md`), and the OpenAPI/Bruno API collection. Each sibling change edits the slice it touches; none owns the whole. This change makes the set coherent after the others land.

## Goals / Non-Goals

**Goals:**

- One consistent end-state picture across every diagram, overview, and cross-reference.
- ADRs recording the load-bearing decisions the initiative made.
- READMEs that follow the documentation standard and a documentation map where every link resolves.
- AGENTS.md and the API collection matching the shipped surface exactly.

**Non-Goals:**

- Application code or behavior changes.
- Rewriting docs the sibling changes already made correct — this reconciles and fills the system-level gaps, it does not redo per-change docs.
- Marketing/website content.

## Decisions

### D1 — Run last, document reality, flag the pending

This change is scheduled after the others are implemented and archived. Where a dependency has not shipped, the docs describe what exists and mark the rest pending, never describing unshipped behavior as shipped. This keeps the docs honest even if the initiative is delivered in waves.

### D2 — Diagrams in text, kept in version control

C4 and request-path diagrams stay as text (Mermaid) so they diff and review in git, per the documentation standard. Two request-path diagrams are the priority because their shape changed most: an authenticated streamed chat turn with RAG sources via the content endpoint, and a document flowing through ingestion/connector into tenant RAG.

### D3 — Counts in badges, not prose

Changing numbers (service counts, endpoint counts, capability counts) live in README badges, not in sentences, so they do not silently go stale — matching the documentation standard.

### D4 — The documentation map is the completeness check

The root README's documentation map is the single index; the acceptance bar is that every shipped doc is linked from it and every link resolves. This turns "are the docs complete" into a checkable property.

## Risks / Trade-offs

- [Docs drift again after this lands] → per-change docs remain each change's responsibility; this capstone is a periodic reconciliation, and the documentation map + AGENTS.md reconciliation make the next drift visible.
- [Documenting unshipped behavior if a dependency slips] → D1's document-reality-flag-pending rule prevents it.
- [Diagram rot] → text/Mermaid diagrams in git are reviewed like code, not binary exports that silently age.

## Open Questions

- None blocking.
