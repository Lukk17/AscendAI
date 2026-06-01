# syntax=docker/dockerfile:1.7

# -------- Stage 1: builder --------
# Pin the runtime image so build artefacts don't drift silently when the
# rolling cuDNN/Ubuntu tag updates.
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl \
        python3.11 python3.11-distutils \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3.11

WORKDIR /build
COPY pytorch-requirements.txt ./
RUN python3.11 -m pip install --upgrade pip \
    && python3.11 -m pip install -r pytorch-requirements.txt

COPY pyproject.toml ./
COPY src/ src/
RUN python3.11 -m pip install .


# -------- Stage 2: runtime --------
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04 AS runtime

LABEL org.opencontainers.image.title="AudioScribe" \
      org.opencontainers.image.description="AscendAI speech-to-text service (REST + MCP)" \
      org.opencontainers.image.source="https://github.com/Lukk17/AscendAI" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="AscendAI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    API_PORT=7017 \
    HOME=/home/appuser \
    HF_HOME=/hf-cache

# ffmpeg + libsndfile1 are runtime-required (transcription + audio I/O).
# curl is kept for HEALTHCHECK.
# python3.11 + distutils so the venv-free pip install layout works; pip
# itself is bootstrapped from the builder via PYTHONPATH copy below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl \
        ffmpeg libsndfile1 \
        python3.11 python3.11-distutils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser \
        --home-dir /home/appuser --create-home \
        --shell /usr/sbin/nologin appuser \
    && mkdir -p /hf-cache \
    && chown -R appuser:appuser /home/appuser /hf-cache

# Bring across the installed packages from the builder (avoids re-running
# the heavy pip install for PyTorch + faster-whisper at runtime stage).
COPY --from=builder /usr/local/lib/python3.11/dist-packages /usr/local/lib/python3.11/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY --chown=appuser:appuser src/ src/

USER appuser

EXPOSE 7017

# /health is the liveness probe (always 200 once uvicorn binds). The 300s
# start-period covers the cold-boot window for fastapi + faster-whisper
# import + initial CUDA context allocation.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl --fail --silent --show-error "http://localhost:${API_PORT}/health" || exit 1

CMD ["python3.11", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7017"]
