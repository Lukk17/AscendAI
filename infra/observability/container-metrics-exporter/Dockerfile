# syntax=docker/dockerfile:1.7

FROM python:3.11.12-slim@sha256:dbf1de478a55d6763afaa39c2f3d7b54b25230614980276de5cacdde79529d0c AS runtime

LABEL org.opencontainers.image.title="container-metrics-exporter" \
      org.opencontainers.image.description="First-party Prometheus exporter for per-container memory usage vs. configured limit, reading only the Docker Engine API socket." \
      org.opencontainers.image.source="https://github.com/Lukk17/AscendAI" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="AscendAI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    EXPORTER_PORT=8080 \
    DOCKER_SOCKET=/var/run/docker.sock

RUN pip install --no-cache-dir prometheus-client==0.26.0

# Primary group 0 (root) so this non-root user gets group-read/write on the
# bind-mounted /var/run/docker.sock, which Docker Desktop and Docker Engine
# both create as root:root mode 660. No other elevated privilege is granted.
RUN useradd --system --uid 10001 --gid 0 --shell /usr/sbin/nologin exporter

WORKDIR /app
COPY exporter.py ./

USER exporter

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/metrics', timeout=3)" || exit 1

CMD ["python", "exporter.py"]
