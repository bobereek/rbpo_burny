"""SQLite connection setup; request persistence will be added separately."""

from pathlib import Path

from sqlalchemy import URL, Engine, create_engine


def create_database_engine(database_path: Path) -> Engine:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        URL.create("sqlite", database=str(database_path)),
        connect_args={"check_same_thread": False},
    )
