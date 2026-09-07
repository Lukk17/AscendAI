FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

# Install system dependencies for VNC and Supervisor
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    fluxbox \
    dbus-x11 \
    supervisor \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Copy source code and supervisor config
COPY src/ src/
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Set up a strictly isolated Python virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install python dependencies strictly within the venv
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install .

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
ENV DBUS_SESSION_BUS_ADDRESS=autolaunch:

# Expose ports (API and NoVNC)
EXPOSE 7021 7900

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# The entrypoint resolves VNC authentication, then hands off to Supervisor,
# which manages the background graphical processes and Uvicorn.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
