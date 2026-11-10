# syntax=docker/dockerfile:1.7

FROM mcr.microsoft.com/playwright/python:v1.60.0-noble@sha256:8ff591d613b01c884cc488339ed4318b4513eaf0c57a164a878ba49e70e3f384 AS base

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Set up a strictly isolated Python virtual environment
RUN python3 -m venv $VIRTUAL_ENV

# Install python dependencies strictly within the venv
COPY pyproject.toml /build/pyproject.toml
COPY --from=ascend-python-common . /opt/ascend-python-common
RUN pip install --no-cache-dir pip==26.2.2 && \
    pip install --no-cache-dir /opt/ascend-python-common && \
    python -c 'import pathlib, tomllib; dependencies = tomllib.loads(pathlib.Path("/build/pyproject.toml").read_text())["project"]["dependencies"]; pathlib.Path("/build/dependencies.txt").write_text("\n".join(dependencies) + "\n")' && \
    pip install --no-cache-dir -r /build/dependencies.txt

FROM base AS runtime

# Install system dependencies for VNC and Supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    fluxbox \
    dbus-x11 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 webhunter && \
    useradd --uid 10001 --gid 10001 --create-home --home-dir /home/webhunter --shell /usr/sbin/nologin webhunter && \
    install -d -m 1777 /tmp/.X11-unix && \
    install -d -m 0700 -o webhunter -g webhunter /run/vnc && \
    install -d -m 0755 -o webhunter -g webhunter /app/.crawlee_storage

COPY --from=builder /opt/venv /opt/venv

# Fetch both browser builds at image build time, pinned to the pyproject
# versions. A missing browser binary is a startup error, never a download
# at request time. The base image already carries the system libraries
# Chromium needs, so no --with-deps here.
RUN python -c "from camoufox.fpgen_model import ensure_fpgen_model; ensure_fpgen_model()"
RUN chmod -R a+rX /opt/venv/lib/python3.12/site-packages/fpgen/data
USER webhunter
RUN python -m patchright install chromium
RUN python -m camoufox fetch
USER root

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && \
    sed -i 's/^! background: none$/background: unset/' /etc/X11/fluxbox/overlay && \
    grep -qx 'background: unset' /etc/X11/fluxbox/overlay

COPY novnc/paste-clipboard.js /usr/share/novnc/app/paste-clipboard.js
RUN paste_version="$(sha256sum /usr/share/novnc/app/paste-clipboard.js | cut -c1-12)" && \
    paste_tag="    <script type=\"module\" crossorigin=\"anonymous\" src=\"app/paste-clipboard.js?v=${paste_version}\"></script>" && \
    sed -i "s|^    <script type=\"module\" crossorigin=\"anonymous\" src=\"app/ui.js\"></script>\$|&\n${paste_tag}|" /usr/share/novnc/vnc.html && \
    grep -qxF "${paste_tag}" /usr/share/novnc/vnc.html

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --no-deps . && \
    chown -R webhunter:webhunter src/assets

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
ENV NOVNC_DISPLAY_SIZE=1920x1080
ENV DBUS_SESSION_BUS_ADDRESS=autolaunch:
ENV API_HOST=0.0.0.0
ENV API_PORT=7021

# Expose ports (API and NoVNC)
EXPOSE 7021 7900

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS "http://localhost:${API_PORT}/health" || exit 1

USER webhunter

# The entrypoint resolves VNC authentication, then hands off to Supervisor,
# which manages the background graphical processes and Uvicorn.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
