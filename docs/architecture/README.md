# AscendAI Architecture Documentation

This directory contains monorepo-level architecture documentation following the [arc42](https://arc42.org/) template with Mermaid diagrams and Architecture Decision Records (ADRs).

## Arc42 Sections

| # | Section | Description |
|---|---|---|
| 1 | [Introduction and Goals](arc42/01-introduction-and-goals.md) | Purpose, capabilities, quality goals |
| 2 | [System Context](arc42/02-system-context.md) | Context diagram, external interfaces |
| 3 | [Building Blocks](arc42/03-building-blocks.md) | Service decomposition, responsibilities, interaction flows |
| 4 | [Deployment](arc42/04-deployment.md) | Local topology, port map, prerequisites |
| 5 | [Crosscutting Concerns](arc42/05-crosscutting-concerns.md) | Multi-provider routing, MCP, RAG, memory, embeddings |

## Diagrams

| Diagram | Description |
|---|---|
| [System Overview](diagrams/system-overview.md) | High-level system architecture with all services and data flows |
| [Prompt Flow](diagrams/prompt-flow.md) | Detailed sequence diagram of prompt processing |

## Architecture Decision Records

| Index | Description |
|---|---|
| [ADR Index](decisions/README.md) | All monorepo-level and AscendAgent-specific ADRs |

## Module-Level Architecture

The AscendAgent has its own detailed arc42 documentation in [`AscendAgent/docs/architecture/`](../../AscendAgent/docs/architecture/) covering internal class structure, component diagrams, and module-specific ADRs.
