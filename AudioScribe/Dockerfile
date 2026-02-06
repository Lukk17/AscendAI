# Use the official NVIDIA image with the correct CUDA and cuDNN versions
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_USER=appuser

# Install Python, pip, and other system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    ffmpeg \
    libsndfile1 \
    python3.11 \
    python3.11-distutils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install pip for Python 3.11
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

# Create a non-root user and group for security
RUN groupadd -r "$APP_USER" && useradd -r -g "$APP_USER" "$APP_USER"

# Set working directory
WORKDIR /app

# Copy requirements files first to leverage Docker layer caching
COPY pytorch-requirements.txt .
RUN python3.11 -m pip install --no-cache-dir --upgrade pip && \
    python3.11 -m pip install --no-cache-dir -r pytorch-requirements.txt

COPY pyproject.toml .
RUN python3.11 -m pip install --no-cache-dir .

# Copy the rest of the application code and set ownership
COPY --chown="$APP_USER":"$APP_USER" . .

# Switch to the non-root user
USER $APP_USER

# Expose the port the app runs on
EXPOSE 7017

# The command to run the application
CMD ["python3.11", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7017"]
