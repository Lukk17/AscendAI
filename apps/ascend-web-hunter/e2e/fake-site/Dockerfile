FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir starlette==0.41.3 uvicorn==0.34.0
COPY app.py .
COPY files/ ./files/
EXPOSE 7031
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7031"]
