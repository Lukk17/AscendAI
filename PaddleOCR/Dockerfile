FROM python:3.11.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
        libgomp1 \
        gcc \
        g++ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
RUN python3.11 -m pip install --no-cache-dir --upgrade pip && \
    python3.11 -m pip install --no-cache-dir .

RUN DISABLE_AUTO_LOGGING_CONFIG=1 python3.11 -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en', enable_mkldnn=False); PaddleOCR(lang='pl', enable_mkldnn=False)"


FROM python:3.11.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_USER=appuser \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    DISABLE_AUTO_LOGGING_CONFIG=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
        libgomp1 \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r "$APP_USER" && useradd -r -g "$APP_USER" "$APP_USER"

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.paddlex /home/$APP_USER/.paddlex

WORKDIR /app

COPY --chown="$APP_USER":"$APP_USER" . .

RUN chown -R "$APP_USER":"$APP_USER" /home/$APP_USER/.paddlex

USER $APP_USER

ENV HOME=/home/$APP_USER

EXPOSE 7022

LABEL org.opencontainers.image.title="PaddleOCR" \
      org.opencontainers.image.description="FastAPI + FastMCP OCR microservice for AscendAI" \
      org.opencontainers.image.source="https://github.com/Lukk17/AscendAI" \
      org.opencontainers.image.licenses="MIT"

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl --fail --silent http://localhost:7022/health || exit 1

CMD ["python3.11", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7022"]
