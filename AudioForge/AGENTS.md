# AGENTS.md — AudioForge

## Project Overview

AudioForge is an audio processing microservice that provides conversion, silence removal, and full audio processing pipelines. It exposes both a REST API and MCP server interface, using ffmpeg and SoX as processing backends.

## Tech Stack

- **Language**: Python 3.13
- **Framework**: FastAPI + Uvicorn
- **Docker Base**: `python:3.13-slim`
- **System Dependencies**: ffmpeg, SoX (`sox.portable` on Windows)

## Build & Run Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (port 7018)
uvicorn src.main:app --host 0.0.0.0 --port 7018 --reload

# Docker
docker build -t audio-forge:latest .
```

## Architecture

**Dual API surface**:
- REST API: Audio processing endpoints (convert, remove silence, full processing)
- MCP Server: MCP tools via `mcp` library

**Key Features**:
- Audio format conversion (multiple output formats and sample rates)
- Silence removal using SoX
- Combined processing pipeline
- Swagger/Redoc documentation

## System Requirements

- **ffmpeg**: Required for audio conversion
- **SoX**: Required for silence removal
  - Windows: `choco install sox.portable`
  - Linux: `apt-get install sox`

## Code Conventions

- FastAPI for REST endpoints
- Type hints on all function signatures
- Pydantic models for request/response validation

## Relevant Skills

- `/python-patterns`, `/api-design`, `/docker-patterns`
