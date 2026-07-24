"""Minimal FastAPI app for Tahap 1: only a health check.

The full API surface (spec §26) is built in Tahap 6, once there is real
data to serve. This exists now so docker-compose has something to health-
check and so the deployment shape (container, port, health endpoint) is
proven early.
"""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from src.config.settings import get_settings
from src.database.session import make_engine

app = FastAPI(
    title="IDX Investment Intelligence Platform API",
    version="0.1.0",
    description="Automated research and decision-support platform for IDX-listed stocks.",
)


@app.get("/api/v1/health")
def health() -> dict:
    settings = get_settings()
    db_status = "unknown"
    try:
        engine = make_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001 -- health check must never raise
        db_status = f"error: {exc.__class__.__name__}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "environment": settings.app_env,
        "timezone": settings.timezone,
    }
