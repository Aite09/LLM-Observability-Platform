"""
FastAPI application factory.

Why a factory function (create_app) instead of a module-level `app`?
  Tests call create_app() to get a fresh app instance with overridden
  dependencies. Module-level singletons share state across tests.

Why lifespan instead of @app.on_event("startup")?
  lifespan (FastAPI 0.93+) is the current pattern. on_event is deprecated.
  lifespan is a context manager: code before `yield` = startup,
  code after `yield` = shutdown. Clean, no implicit ordering issues.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routers import health, logs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup → yield → shutdown."""
    settings = get_settings()
    logger.info("Starting %s", settings.app_name)
    # Future: initialise connection pools, background schedulers here
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="LLM Evaluation & Observability Platform",
        version="0.1.0",
        lifespan=lifespan,
        # Disable docs in prod by setting docs_url=None in a prod settings subclass
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow the React dashboard (localhost:5173 in dev)
    # In production, replace with your actual frontend domain
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router)
    app.include_router(logs.router)
    # Week 3+: app.include_router(evals.router)
    # Week 4+: app.include_router(metrics.router)
    # Week 5+: app.include_router(drift.router)

    return app


# Module-level app instance — used by uvicorn:
#   uvicorn api.main:app --reload
app = create_app()


# Configure logging once at module level
# Every logger.getLogger(__name__) in every file flows through this config
logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
