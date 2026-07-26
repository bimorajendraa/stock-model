"""FastAPI app (spec §26). Started as a health-check-only scaffold in
Tahap 1; now also exposes the computed results from every pipeline built
since (technical/fundamental/valuation/recommendation/sector/news+
sentiment) -- read-only, see ``routers/`` for each resource group. This
layer computes nothing itself; it only serializes what those pipelines
already wrote.
"""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from apps.api.routers import companies, recommendations
from src.config.settings import get_settings
from src.database.session import make_engine

app = FastAPI(
    title="IDX Investment Intelligence Platform API",
    version="0.1.0",
    description="Automated research and decision-support platform for IDX-listed stocks.",
)

app.include_router(companies.router)
app.include_router(recommendations.router)


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
