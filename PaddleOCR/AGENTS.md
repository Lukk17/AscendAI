# AGENTS.md — PaddleOCR

## Project Overview

PaddleOCR is an OCR (Optical Character Recognition) service that wraps the PaddleOCR library behind a FastAPI REST API and FastMCP server. It supports multi-language text extraction from images.

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn, FastMCP 3.0.2
- **Version**: 0.1.0
- **Key Libraries**: PaddlePaddle 3.3.0, PaddleOCR 3.4.0, Pillow 12.1.1
- **Docker Base**: `python:3.11-slim` (multi-stage build with pre-cached models)

## Build & Run Commands

```bash
# Install dependencies
pip install -e .

# Run the server (port 7022)
uvicorn src.main:app --host 0.0.0.0 --port 7022 --reload

# Docker
docker build -t ascend-paddle-ocr:latest .
```

## Architecture

**Dual API surface**:
- REST API: OCR endpoints for image text extraction
- MCP Server: FastMCP tools exposed via Streamable HTTP

**Key Features**:
- Multi-language OCR support (English, Polish, and more)
- Image processing via Pillow
- Pre-cached models in Docker for fast startup

## Environment Variables

- `API_PORT` — Service port (default: 7022)
- `API_HOST` — Bind address (default: 0.0.0.0)
- `LOG_LEVEL` — Logging level (default: INFO)
- `DEFAULT_LANGUAGE` — Default OCR language (default: en)
- `MAX_FILE_SIZE_MB` — Maximum upload file size (default: 50)
- `OCR_REQUEST_TIMEOUT` — Request timeout in seconds (default: 120)

## Code Conventions

- Absolute imports from `src`
- Type hints (PEP 484) on all function signatures
- Pydantic models for data validation
- FastMCP for MCP tool definitions

## Relevant Skills

- `/python-patterns`, `/python-testing`
- `/api-design`, `/docker-patterns`
