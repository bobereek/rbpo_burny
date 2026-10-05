import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from wildburny.main import create_app


@pytest.fixture(autouse=True)
def isolate_database_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WILDBURNY_DB_PATH", raising=False)


@pytest.mark.parametrize("as_string", [False, True])
def test_health_initializes_empty_database_during_startup(tmp_path: Path, as_string: bool) -> None:
    database_path = tmp_path / "nested" / "data" / "wildburny.sqlite3"
    app = create_app(database_path=str(database_path) if as_string else database_path)

    assert not database_path.parent.exists()

    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert database_path.is_file()
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []


def test_default_database_path_is_relative_to_working_directory(tmp_path: Path) -> None:
    app = create_app()
    database_path = tmp_path / "var" / "wildburny.sqlite3"

    assert not database_path.parent.exists()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert database_path.is_file()


def test_database_path_can_be_configured_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "configured" / "app.sqlite3"
    monkeypatch.setenv("WILDBURNY_DB_PATH", str(database_path))

    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert database_path.is_file()
        assert not (tmp_path / "var").exists()


def test_explicit_database_path_overrides_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment_path = tmp_path / "environment" / "app.sqlite3"
    explicit_path = tmp_path / "explicit" / "app.sqlite3"
    monkeypatch.setenv("WILDBURNY_DB_PATH", str(environment_path))

    with TestClient(create_app(database_path=explicit_path)) as client:
        assert client.get("/health").status_code == 200
        assert explicit_path.is_file()
        assert not environment_path.parent.exists()


def test_existing_database_is_preserved_across_restarts(tmp_path: Path) -> None:
    database_path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES (?)", ("keep this value",))

    for _ in range(2):
        with TestClient(create_app(database_path=database_path)) as client:
            assert client.get("/health").status_code == 200
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT value FROM sentinel").fetchall() == [
                ("keep this value",)
            ]


def test_startup_fails_when_database_path_is_a_directory(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path)

    with pytest.raises(SQLAlchemyError), TestClient(app):
        pytest.fail("Application startup must fail when SQLite cannot open the database")


def test_startup_rejects_a_corrupt_database(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt.sqlite3"
    database_path.write_bytes(b"not a SQLite database" * 100)

    with pytest.raises(SQLAlchemyError), TestClient(create_app(database_path=database_path)):
        pytest.fail("Application must not start with an unreadable database")


def test_health_detects_database_corruption_after_startup(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt-later.sqlite3"

    with TestClient(create_app(database_path=database_path)) as client:
        assert client.get("/health").status_code == 200
        database_path.write_bytes(b"not a SQLite database" * 100)

        response = client.get("/health")

        assert response.status_code == 503
        assert response.json() == {"detail": "Service unavailable"}


def test_health_returns_sanitized_error_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(database_path=tmp_path / "health.sqlite3")

    def unavailable_connection():
        raise SQLAlchemyError("private connection details: /secret/path/database.sqlite3")

    with TestClient(app) as client:
        with monkeypatch.context() as database_failure:
            database_failure.setattr(app.state.db_engine, "connect", unavailable_connection)
            response = client.get("/health")

        assert response.status_code == 503
        assert response.json() == {"detail": "Service unavailable"}
        assert client.get("/health").json() == {"status": "ok"}


def test_database_engine_is_disposed_on_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(database_path=tmp_path / "shutdown.sqlite3")

    with TestClient(app) as client:
        dispose = Mock(wraps=app.state.db_engine.dispose)
        monkeypatch.setattr(app.state.db_engine, "dispose", dispose)
        assert client.get("/health").status_code == 200
        dispose.assert_not_called()

    dispose.assert_called_once()
