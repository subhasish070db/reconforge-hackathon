"""ReconForge FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import seed_demo_users
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import audit, auth, breaks, client, configs, governance, loops, regulatory, runs, seed

settings = get_settings()
# Reuse Uvicorn's configured INFO handler so request lines reach Cloud Logging.
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed the five demo users (idempotent).
    db = SessionLocal()
    try:
        seed_demo_users(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="ReconForge API",
    description=(
        "Author reconciliations from natural language, run them deterministically, "
        "and resolve breaks with agents that explain themselves and never guess."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request(request, call_next):
    """Emit Cloud Run-friendly request logs without recording sensitive bodies."""
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed method=%s path=%s duration_ms=%d",
            request.method,
            request.url.path,
            round((time.perf_counter() - started_at) * 1000),
        )
        raise

    logger.info(
        "request_complete method=%s path=%s status=%s duration_ms=%d",
        request.method,
        request.url.path,
        response.status_code,
        round((time.perf_counter() - started_at) * 1000),
    )
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}


app.include_router(auth.router)
app.include_router(configs.router)
app.include_router(runs.router)
app.include_router(breaks.router)
app.include_router(governance.router)
app.include_router(regulatory.router)
app.include_router(client.router)
app.include_router(loops.router)
app.include_router(audit.router)
app.include_router(seed.router)
