"""GET /status — read-only project status panel."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lmc.server import _humanize_idle


def _seed(client: TestClient, project_dir: Path) -> str:
    client.post("/api/projects", json={"name": "demo", "path": str(project_dir)})
    return client.post("/api/projects/demo/sessions").json()["id"]


def test_status_returns_html(client: TestClient):
    r = client.get("/status")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>local-mc status</title>" in r.text


def test_status_shows_no_session_marker_for_blank_project(
    client: TestClient, project_dir: Path
):
    client.post("/api/projects", json={"name": "demo", "path": str(project_dir)})
    r = client.get("/status")
    assert "(no session)" in r.text
    assert "demo" in r.text
    assert str(project_dir) in r.text


def test_status_shows_active_session_with_idle(
    client: TestClient, project_dir: Path
):
    sid = _seed(client, project_dir)
    r = client.get("/status")
    # First 8 chars of session id surface; should not be 'stale' class yet.
    assert sid[:8] in r.text
    assert "tr class='stale'" not in r.text
    # Idle bucket should be tiny — seconds. Match the <td>Ns</td> wrapper
    # so we don't false-positive on timestamps like `14:32:42Z`.
    assert any(f">{n}s<" in r.text for n in ("0", "1", "2"))


def test_status_flags_stale_session_red(
    client: TestClient, project_dir: Path, monkeypatch
):
    """Backdate the latest session by 2h and confirm the row is red."""
    sid = _seed(client, project_dir)
    # Reach into the same store the app uses
    store = client.app.state.store
    with store.connect() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?",
            (time.time() - (2 * 60 * 60), sid),
        )
    r = client.get("/status")
    assert "tr class='stale'" in r.text
    # And the idle column reads "2h …" or "1h …" depending on rounding
    assert ("2h" in r.text) or ("1h 5" in r.text)


def test_status_lists_multiple_projects(
    client: TestClient, tmp_path: Path
):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    client.post("/api/projects", json={"name": "alpha", "path": str(a)})
    client.post("/api/projects", json={"name": "beta", "path": str(b)})
    r = client.get("/status")
    assert "alpha" in r.text
    assert "beta" in r.text
    # Both should be in the project count line
    assert "2 project(s)" in r.text


def test_status_escapes_html_in_project_name(
    client: TestClient, tmp_path: Path
):
    """Project names accepted by the API can include `_-`. The escape is
    defensive — if the registry ever gets edited by hand to include
    `<script>`, /status must not render it as live HTML."""
    # We can't add a project named `<script>` via the API (validator rejects
    # it). Forge it directly into the registry.
    reg = client.app.state.registry
    proj_path = tmp_path / "p"
    proj_path.mkdir()
    from lmc.projects import Project
    raw = reg.load() + [Project(name="<script>x</script>", path=str(proj_path))]
    reg.save(raw)
    r = client.get("/status")
    assert "<script>x</script>" not in r.text
    assert "&lt;script&gt;" in r.text


@pytest.mark.parametrize(
    "secs,expect",
    [
        (5, "5s"),
        (60, "1m"),
        (180, "3m"),
        (3600, "1h 0m"),
        (3661, "1h 1m"),
        (86400, "1d 0h"),
        (90061, "1d 1h"),
    ],
)
def test_humanize_idle(secs, expect):
    assert _humanize_idle(secs) == expect
