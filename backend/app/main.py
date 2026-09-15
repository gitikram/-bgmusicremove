"""FastAPI application entry point: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import queueing
from .api.routes import cleanup_loop, router, run_cleanup_once
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("clearvoice")


async def _cleanup_task() -> None:
    # Run one pass shortly after startup so leftovers from previous runs are purged.
    await asyncio.sleep(10)
    try:
        run_cleanup_once()
    except Exception:  # noqa: BLE001
        log.exception("startup cleanup pass failed")
    await cleanup_loop()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    if not settings.redis_url:
        recovered = queueing.recover_stale_jobs()
        if recovered:
            log.info("Marked %d stale job(s) as failed after restart (thread-queue mode).", recovered)
    log.info(
        "ClearVoice API ready | queue=%s | model=%s | device=%s | fake_separation=%s",
        queueing.queue_backend_name(),
        settings.demucs_model,
        settings.device,
        settings.dev_fake_separation,
    )
    task = asyncio.create_task(_cleanup_task())
    yield
    task.cancel()
    queueing.shutdown_thread_queue()


app = FastAPI(title="ClearVoice API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve the built frontend when it exists (single-box deployments).
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
    log.info("Serving frontend from %s", _FRONTEND_DIST)
