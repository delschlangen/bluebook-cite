"""Tests for the CORS allowlist.

A browser sends scheme + host + port as the Origin. The path is not part of
it, so a site served from a subpath of a custom domain still presents the bare
domain and must be listed as exactly that. Getting this wrong makes a healthy
backend look completely unreachable, because the browser blocks the response
before any application code sees it.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import ALLOWED_ORIGINS, app

# Every origin the site is actually served from.
LIVE_ORIGINS = [
    "https://delschlangen.com",
    "https://www.delschlangen.com",
    "https://delschlangen.github.io",
]

DEV_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("origin", LIVE_ORIGINS + DEV_ORIGINS)
def test_origin_is_in_the_allowlist(origin):
    assert origin in ALLOWED_ORIGINS


@pytest.mark.parametrize("origin", LIVE_ORIGINS)
@pytest.mark.parametrize("path", ["/api/repair", "/api/analyze", "/api/upload"])
def test_preflight_succeeds_for_live_origins(client, origin, path):
    response = client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize("origin", LIVE_ORIGINS)
def test_actual_response_carries_the_allow_origin_header(client, origin):
    """Without this header the browser discards a perfectly good response and
    the fetch rejects, which is indistinguishable from the server being down."""
    response = client.post(
        "/api/repair",
        json={"text": "Brandenburg v. Ohio, 395 U.S. 444 (1969)"},
        headers={"Origin": origin},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize("origin", LIVE_ORIGINS)
def test_health_is_readable_cross_origin(client, origin):
    """The client probes /health to tell 'server is down' apart from other
    failures. If health is not readable cross-origin, every failure looks like
    an outage."""
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_unlisted_origin_is_refused(client):
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert response.headers.get("access-control-allow-origin") is None


def test_credentials_are_not_enabled():
    """No cookies or auth headers are used. Leaving credentials on would also
    forbid ever using a wildcard origin."""
    for middleware in app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            assert middleware.kwargs.get("allow_credentials") is False
            return
    pytest.fail("CORSMiddleware is not installed")


def test_extra_origins_can_be_added_without_a_deploy(monkeypatch):
    """A new domain should be addable by setting an environment variable, not
    by editing code and waiting for a rebuild."""
    monkeypatch.setenv("EXTRA_ALLOWED_ORIGINS", "https://a.example.com, https://b.example.com")

    import importlib

    import app.main as main_module
    reloaded = importlib.reload(main_module)
    try:
        assert "https://a.example.com" in reloaded.ALLOWED_ORIGINS
        assert "https://b.example.com" in reloaded.ALLOWED_ORIGINS
    finally:
        monkeypatch.delenv("EXTRA_ALLOWED_ORIGINS", raising=False)
        importlib.reload(main_module)
