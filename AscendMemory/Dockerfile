# Stage 1: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
# Copy source code
COPY src/ src/

# Install python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 7020

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7020"]
