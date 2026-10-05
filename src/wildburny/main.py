"""Minimal locally runnable API for the EK1 technical foundation."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from wildburny.database import create_database_engine


def create_app(*, database_path: str | Path | None = None) -> FastAPI:
    """Configure an app; SQLite is opened only when its lifespan starts."""
    if database_path is None:
        database_path = os.environ.get("WILDBURNY_DB_PATH", "var/wildburny.sqlite3")
    path = Path(database_path).expanduser().resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(path)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT name FROM sqlite_master LIMIT 1"))
            app.state.db_engine = engine
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="WildBurny", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health(request: Request) -> dict[str, str]:
        try:
            with request.app.state.db_engine.connect() as connection:
                connection.execute(text("SELECT name FROM sqlite_master LIMIT 1"))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Service unavailable") from None
        return {"status": "ok"}

    return app
