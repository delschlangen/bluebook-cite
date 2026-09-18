"""Tests for the serverless deployment surface.

The Vercel function imports the same FastAPI app that uvicorn serves. These
tests fail if that entry point breaks or if the app grows a dependency on
something only a long-lived container provides.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_vercel_entry_point_exports_the_asgi_app():
    entry = BACKEND_ROOT / "api" / "index.py"
    assert entry.exists(), "api/index.py is what Vercel serves"

    spec = importlib.util.spec_from_file_location("vercel_entry", entry)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "app"), "Vercel's Python runtime serves the `app` export"
    assert module.app.__class__.__name__ == "FastAPI"


def test_vercel_config_routes_everything_to_the_function():
    config = json.loads((BACKEND_ROOT / "vercel.json").read_text())
    rewrites = config.get("rewrites", [])
    assert any(
        r.get("source") == "/(.*)" and r.get("destination") == "/api/index"
        for r in rewrites
    ), "every path must reach the ASGI app, not just /api/*"

    fn = config.get("functions", {}).get("api/index.py", {})
    assert "app/**" in str(fn.get("includeFiles", "")), (
        "the app package must be bundled with the function"
    )


def test_app_works_without_lifespan_events():
    """Some serverless runtimes never dispatch ASGI lifespan events. The app
    must still serve requests, which means the lookup service cannot depend on
    startup having run."""
    # Simulate a cold serverless invocation: no lifespan, no warm globals.
    import app.main as main_module
    from app.main import app, get_lookup_service
    main_module._lookup_service = None

    # TestClient without a context manager does not run lifespan.
    client = TestClient(app)
    response = client.post(
        "/api/repair", json={"text": "Brandenburg v. Ohio, 395 U.S. 444 (1969)"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"

    assert get_lookup_service() is not None


def test_health_reports_which_build_and_host_answered(monkeypatch):
    from app.main import app

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "abcdef1234567890")

    with TestClient(app) as client:
        body = client.get("/health").json()

    assert body["host"] == "vercel"
    assert body["commit"] == "abcdef1"
    assert "/api/repair" in body["endpoints"]


@pytest.mark.parametrize(
    "name,default",
    [
        ("COMPLETION_BUDGET_SECONDS", 25.0),
        ("REPAIR_BUDGET_SECONDS", 20.0),
    ],
)
def test_time_budgets_are_tunable_without_a_code_change(name, default):
    """Serverless function timeouts vary by plan, so the budgets have to be
    settable per environment."""
    import app.main as main_module

    assert getattr(main_module, name) == default
