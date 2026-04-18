# AGENTS.md — OpenMemory

## Project Overview

OpenMemory is a Docker wrapper for the mem0 OpenMemory MCP Server, customized to work with LM Studio for local LLM and embedding inference. This module is **deprecated** — its functionality has been replaced by the AscendMemory module which provides a cleaner REST API and MCP interface.

## Status

**Deprecated**: Commented out in `docker-compose.yaml`. Use AscendMemory instead.

## What It Was

- Custom Dockerfile based on `mem0/openmemory-mcp`
- Patches for LM Studio compatibility (removed `json_object` response format requirement in `categorization.py`)
- Qdrant backend with 768-dimension embeddings
- `configure_mem0.sh` startup script for auto-configuration
- YAML anchors for centralized model configuration

## Default Models (historical)

- **LLM**: meta-llama-3.1-8b-instruct (via LM Studio)
- **Embedder**: nomic-ai/nomic-embed-text-v1.5-GGUF

## Note for Agents

Do not invest effort in this module. If memory-related work is needed, focus on AscendMemory instead.
