FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TORCHCODEC_DISABLE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates ffmpeg libgomp1 libsndfile1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu121 \
      "torch==2.5.1+cu121" && \
    pip install --no-cache-dir -r requirements.txt

COPY main.py ./main.py
COPY src/ ./src/

EXPOSE 7017
# Run the application using Uvicorn
# The host 0.0.0.0 makes the app accessible from outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7017"]
