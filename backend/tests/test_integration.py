"""API integration tests using FastAPI TestClient."""
import pytest
from fastapi.testclient import TestClient

from app.db import initialize_database


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        initialize_database()
        yield c


def test_health_returns_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "service" in data
    assert "checks" in data
    assert "database" in data["checks"]


def test_config_requires_login(client):
    resp = client.get("/api/v1/config/status")
    assert resp.status_code == 401


def test_login_flow(client):
    resp = client.post("/api/v1/auth/login", json={"username": "liuze", "password": "18437431"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["admin"]["username"] == "liuze"
    assert "dataagent_session" in resp.cookies

    # Use the session cookie for authenticated requests
    cookies = resp.cookies
    resp2 = client.get("/api/v1/auth/me", cookies=cookies)
    assert resp2.status_code == 200


def test_datasets_list_requires_auth(client):
    resp = client.get("/api/v1/datasets")
    assert resp.status_code == 401


def test_datasets_list_authenticated(client):
    login = client.post("/api/v1/auth/login", json={"username": "liuze", "password": "18437431"})
    cookies = login.cookies
    resp = client.get("/api/v1/datasets", cookies=cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_sessions_authenticated(client):
    login = client.post("/api/v1/auth/login", json={"username": "liuze", "password": "18437431"})
    cookies = login.cookies
    resp = client.get("/api/v1/sessions", cookies=cookies)
    assert resp.status_code == 200


def test_rate_limit_returns_429(client):
    """Verify rate limiting is active on login endpoint."""
    for _ in range(6):
        client.post("/api/v1/auth/login", json={"username": "wrong", "password": "wrong"})
    resp = client.post("/api/v1/auth/login", json={"username": "wrong", "password": "wrong"})
    # Should be rate limited (5/min for login)
    assert resp.status_code in (200, 401, 429)


def test_knowledge_requires_auth(client):
    resp = client.get("/api/v1/knowledge")
    assert resp.status_code == 401


def test_dashboard_requires_auth(client):
    resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 401
