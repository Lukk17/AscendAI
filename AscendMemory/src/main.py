import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from src.core.config import settings
from src.api.rest.rest_endpoints import rest_router
from src.api.mcp.mcp_server import mcp

mcp_asgi_app = mcp.http_app()

app = FastAPI(title="AscendMemory", lifespan=mcp_asgi_app.lifespan)

app.include_router(rest_router)

app.mount("/", mcp_asgi_app)

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )
