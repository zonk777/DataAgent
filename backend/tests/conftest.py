import pytest


@pytest.fixture(autouse=True)
def _use_isolated_sqlite_database(monkeypatch, tmp_path):
    """Keep tests isolated while the application runtime uses MySQL."""
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data_agent_test.db"))
    monkeypatch.setenv("VECTOR_STORE", "disabled")
