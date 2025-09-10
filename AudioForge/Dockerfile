FROM python:3.13-slim

# 2. Install FFmpeg and SoX using the system package manager
RUN apt-get update &&  \
    apt-get install -y --no-install-recommends ca-certificates ffmpeg sox  &&  \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 3. Set the working directory in the container
WORKDIR /app

# 4. Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copy your application code
COPY main.py .
COPY src/ ./src/

# 6. Expose the port the app runs on
EXPOSE 7018

# 7. Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7018"]