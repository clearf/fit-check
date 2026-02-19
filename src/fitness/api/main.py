"""FastAPI application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from fitness.db.engine import get_engine
from fitness.api.routes import activities, sync as sync_routes


def create_app() -> FastAPI:
    """Build and return the FastAPI app."""

    engine = get_engine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Create tables on startup (idempotent)
        SQLModel.metadata.create_all(engine)
        yield

    app = FastAPI(
        title="Fitness API",
        description="Garmin run analysis backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(activities.router, prefix="/activities", tags=["activities"])
    app.include_router(sync_routes.router, prefix="/sync", tags=["sync"])

    return app


# Module-level app instance for uvicorn
app = create_app()
