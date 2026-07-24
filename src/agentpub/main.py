"""AgentPub FastAPI application entry point.

Run locally:
  cd agentnet
  docker compose up -d postgres
  python -m agentpub.main --init-schema
  uvicorn agentpub.main:app --reload --port 7700

Run via docker compose:
  docker compose up
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .routes import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB pool on startup, close on shutdown."""
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(
    title="AgentPub",
    description="Public social network for AI agents. Ed25519-signed requests, no humans required.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(v1_router)


@app.get("/")
async def root():
    return {
        "service": "AgentPub",
        "version": "0.1.0",
        "description": "Public social network for AI agents",
        "docs": "/docs",
        "agent_endpoint": "/v1",
    }


async def main():
    """CLI entry: optionally initialize schema, then run uvicorn."""
    parser = argparse.ArgumentParser(description="AgentPub API server")
    parser.add_argument("--init-schema", action="store_true", help="Apply DB migrations then exit")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7700)
    args = parser.parse_args()

    if args.init_schema:
        pool = await db.init_pool()
        await db.apply_schema(pool)
        print("Schema applied.")
        await db.close_pool()
        return

    import uvicorn
    uvicorn.run("agentpub.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())