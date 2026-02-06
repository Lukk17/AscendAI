# Stage 1: Runtime
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY src/ src/

# Install python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Install Playwright dependencies & browsers
RUN playwright install-deps && \
    playwright install chromium

# Environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 7021

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7021"]
