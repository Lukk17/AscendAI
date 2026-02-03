import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from src.core.config import settings
from src.api.rest.rest_endpoints import rest_router
from src.api.mcp.mcp_server import mcp

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="AscendWebSearch", lifespan=lifespan)

# 1. Mount REST API (Specific path)
app.include_router(rest_router)

# 2. Mount MCP Server (Root path for HTTP streamable /mcp/messages handling)
app.mount("/", mcp.streamable_http_app())

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
