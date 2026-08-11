"""Tests for the FastAPI web UI (``code_agent.ui.web``).

The web UI exposes the capability catalog over HTTP and dispatches audited
invocations. These tests exercise the API with FastAPI's ``TestClient`` and
do not require Node or a built frontend: the static SPA test is skipped when
``webapp/dist`` has not been built yet.
"""

from __future__ import annotations

import shutil

from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from fastapi.testclient import TestClient

from code_agent import cli
from code_agent.ui.web import _DIST_DIR, app


# Path to the React SPA build dir, derived from the CLI module so it stays in
# sync with where ``serve --web`` actually looks for it.
_WEBAPP_DIR = Path(cli.__file__).resolve().parent / "ui" / "webapp"
_CLI_DIST_DIR = _WEBAPP_DIR / "dist"


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


# --- `serve --web` build-on-demand (code_agent.cli._ensure_webapp_built) ---
# The npm subprocess is mocked so the suite stays fast and does not require
# Node/npm to be installed; we assert the *control flow* (when a build is
# attempted, and when it is skipped gracefully).


@pytest.fixture
def _dist_absent() -> Iterator[None]:
    """Temporarily move webapp/dist aside so the build-on-demand path runs."""
    backup = None
    if _CLI_DIST_DIR.is_dir():
        backup = _WEBAPP_DIR / ".dist_test_bak"
        if backup.exists():
            backup = _WEBAPP_DIR / ".dist_test_bak2"
        shutil.move(str(_CLI_DIST_DIR), str(backup))
    try:
        assert not _CLI_DIST_DIR.exists()
        yield
    finally:
        if backup is not None and backup.is_dir():
            if _CLI_DIST_DIR.exists():
                shutil.rmtree(str(_CLI_DIST_DIR))
            shutil.move(str(backup), str(_CLI_DIST_DIR))


def test_ensure_webapp_built_skips_when_dist_present() -> None:
    """If dist/ already exists, no npm install/build is attempted."""
    if not _CLI_DIST_DIR.is_dir():
        pytest.skip("dist/ not built; run `npm run build` in webapp/")
    with (
        mock.patch("code_agent.cli.subprocess.run") as run,
        mock.patch("shutil.which", return_value="/usr/bin/npm"),
    ):
        cli._ensure_webapp_built()
    run.assert_not_called()


def test_ensure_webapp_built_graceful_when_npm_missing(_dist_absent) -> None:
    """dist/ missing + npm absent -> returns without error, no build attempted."""
    with (
        mock.patch("code_agent.cli.subprocess.run") as run,
        mock.patch("shutil.which", return_value=None),
    ):
        cli._ensure_webapp_built()  # must not raise
    run.assert_not_called()
    assert not _CLI_DIST_DIR.is_dir()


def test_ensure_webapp_built_runs_npm_when_dist_missing(_dist_absent) -> None:
    """dist/ missing + npm present -> runs `npm install` then `npm run build`."""
    with (
        mock.patch("code_agent.cli.subprocess.run") as run,
        mock.patch("shutil.which", return_value="/usr/bin/npm"),
    ):
        cli._ensure_webapp_built()
    commands = [c.args[0] for c in run.call_args_list]
    assert commands[0][:2] == ["/usr/bin/npm", "install"]
    assert commands[-1][:3] == ["/usr/bin/npm", "run", "build"]
