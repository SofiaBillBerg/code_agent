"""Tests for the FastAPI web UI (``code_agent.ui.web``).

The web UI exposes the capability catalog over HTTP and dispatches audited
invocations. These tests exercise the API with FastAPI's ``TestClient`` and
do not require Node or a built frontend: the static SPA test is skipped when
``webapp/dist`` has not been built yet.
"""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from code_agent.ui.web import _DIST_DIR, app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Return a TestClient bound to the web app."""
    return TestClient(app)


def test_list_capabilities_returns_nonempty_catalog(client: TestClient) -> None:
    """GET /capabilities returns 200 with a non-empty capability list."""
    response = client.get("/capabilities")
    assert response.status_code == 200
    catalog = response.json()
    assert isinstance(catalog, list)
    assert len(catalog) > 0
    ids = {entry["id"] for entry in catalog}
    assert "read-file" in ids


def test_invoke_valid_capability_returns_response_and_receipt(
    client: TestClient,
) -> None:
    """POST /invoke with a valid capability returns response plus receipt."""
    response = client.post(
        "/invoke",
        json={
            "capability_id": "read-file",
            "params": {"file_path": "README.md"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "response" in payload
    assert "receipt" in payload
    assert payload["response"]["status"] == "ok"
    assert payload["response"]["capability_id"] == "read-file"
    assert payload["receipt"]["capability_id"] == "read-file"
    assert payload["receipt"]["receipt_hash"]


def test_invoke_unknown_capability_returns_error(client: TestClient) -> None:
    """POST /invoke with an unknown capability id returns 400."""
    response = client.post(
        "/invoke",
        json={"capability_id": "does-not-exist", "params": {}},
    )
    assert response.status_code == 400


def test_static_spa_served_when_dist_present(client: TestClient) -> None:
    """GET / serves the built React app when webapp/dist exists."""
    if not _DIST_DIR.is_dir():
        pytest.skip("webapp/dist not built; run `npm run build` in webapp/")
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
