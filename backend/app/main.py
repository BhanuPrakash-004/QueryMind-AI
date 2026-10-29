"""FastAPI application factory and startup checks."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api import router
from .config import get_settings
from .database import get_runtime_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        settings.require_database_url()
        with get_runtime_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database readiness check passed.")
    except Exception as exc:
        logger.warning(
            "Database readiness check failed: %s", exc.__class__.__name__
        )
    logger.info(
        "Groq configured: %s", "yes" if settings.groq_ready else "no"
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="QueryMind-AI",
        description=(
            "Ask natural-language questions about sales transactions and "
            "receive deterministic, evidence-backed answers."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    frontend_origin = (
        settings.frontend_url.strip().rstrip("/") or "http://localhost:5173"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router, prefix="/api")

    @app.get("/")
    def root() -> dict:
        return {
            "name": "QueryMind-AI API",
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
