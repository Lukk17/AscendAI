# syntax=docker/dockerfile:1.7

# -------- Stage 1: builder --------
# Pin the patch version so build artifacts don't drift silently when the
# slim base updates its rolling tag.
FROM python:3.11.12-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# build-essential only lives in the builder; runtime image stays slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Isolated venv we can copy verbatim into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --upgrade pip \
    && pip install .


# -------- Stage 2: runtime --------
FROM python:3.11.12-slim AS runtime

# OCI labels for image registry inspection.
LABEL org.opencontainers.image.title="AscendMemory" \
      org.opencontainers.image.description="AscendAI semantic memory service (REST + MCP)" \
      org.opencontainers.image.source="https://github.com/Lukk17/AscendAI" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="AscendAI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    API_PORT=7020 \
    API_HOST=0.0.0.0 \
    HOME=/home/ascend \
    MEM0_DIR=/home/ascend/.mem0

# curl is the only runtime-required system package — kept for HEALTHCHECK.
# Create a real home for the non-root user so mem0 (which calls
# os.path.expanduser("~") at import time to choose its working directory)
# has a writable target. MEM0_DIR pins it explicitly even if expanduser
# misbehaves on a misconfigured passwd entry.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 ascend \
    && useradd --system --uid 10001 --gid ascend \
        --home-dir /home/ascend --create-home \
        --shell /usr/sbin/nologin ascend

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=ascend:ascend src/ src/

USER ascend

EXPOSE 7020

# /health is the liveness probe (always 200 once uvicorn binds). /ready
# checks Qdrant + embedding-API reachability; we don't use it here because
# Docker would mark the container unhealthy during the legitimate
# cold-boot window, and orchestrators are better placed to consume /ready
# directly than to bury it behind a binary HEALTHCHECK.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD curl --fail --silent --show-error "http://localhost:${API_PORT}/health" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7020"]
