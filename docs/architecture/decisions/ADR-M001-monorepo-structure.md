# ADR-M001: Monorepo with Polyglot Services

## Status

Accepted

## Context

AscendAI consists of multiple services with different optimal technology choices — Spring Boot/Java for the main API gateway (strong Spring AI ecosystem) and Python for ML-adjacent services (faster-whisper, PaddleOCR, mem0ai, Playwright). We needed to decide between a monorepo or multi-repo approach.

## Decision

Use a single monorepo with per-module build systems:
- **Java modules** (AscendAgent, WeatherMCP): Gradle with `build.gradle.kts`
- **Python modules** (AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR): `pyproject.toml` + pip

Each module has its own `Dockerfile`, `AGENTS.md`, and independent dependency management. A shared `docker-compose.yaml` at the root wires everything together.

## Consequences

- **Positive**: Single git history, atomic cross-service changes, shared CI/CD, consistent documentation structure
- **Positive**: Simplified onboarding — one clone, one `docker-compose up`
- **Negative**: Mixed toolchains (Gradle + pip) require polyglot developer setup
- **Negative**: No shared build cache across languages
