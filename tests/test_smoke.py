"""Smoke tests: import, EchoAgent REST + WS round-trip, artifact surfacing."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from lmc.config import Paths, Settings
from lmc.projects import Registry
from lmc.server import create_app


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_paths(tmp_path):
    paths = Paths(config_dir=tmp_path / "config", state_dir=tmp_path / "state")
    paths.ensure()
    return paths


@pytest.fixture
def proj_root(tmp_path):
    p = tmp_path / "demo"
    p.mkdir()
    return p


@pytest.fixture
def echo_settings():
    return Settings(agent="echo")


@pytest.fixture
def client(tmp_paths, echo_settings, proj_root):
    Registry(tmp_paths).add("demo", str(proj_root))
    app = create_app(paths=tmp_paths, settings=echo_settings)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── tests ─────────────────────────────────────────────────────────────────


def test_import(tmp_path):
    """create_app must be importable and callable without error."""
    from lmc.server import create_app as _ca  # noqa: F401

    _ca(
        paths=Paths(config_dir=tmp_path / "cfg", state_dir=tmp_path / "state"),
        settings=Settings(agent="echo"),
    )


def test_list_projects(client, proj_root):
    r = client.get("/api/projects")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "demo"
    assert data[0]["exists"] is True


def test_create_and_list_session(client):
    r = client.post("/api/projects/demo/sessions")
    assert r.status_code == 200
    sid = r.json()["id"]

    r2 = client.get("/api/projects/demo/sessions")
    assert r2.status_code == 200
    assert any(s["id"] == sid for s in r2.json())


def test_session_not_found(client):
    r = client.get("/api/projects/missing/sessions")
    assert r.status_code == 404


def test_echo_ws_roundtrip(client):
    """WS turn: user message echoed back as streaming deltas, done event fires."""
    sid = client.post("/api/projects/demo/sessions").json()["id"]

    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "hello world"})

        events: list[dict] = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "done":
                break

    types = {e["type"] for e in events}
    assert {"user_message", "assistant_start", "delta", "done"} <= types

    text = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "hello world" in text

    done = next(e for e in events if e["type"] == "done")
    assert "artifacts" in done


def test_ping_pong(client):
    sid = client.post("/api/projects/demo/sessions").json()["id"]
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "ping"})
        r = ws.receive_json()
        assert r["type"] == "pong"


def test_artifact_surfaced_after_file_drop(client, proj_root):
    """A PNG written to the project root during a turn appears in done.artifacts."""
    sid = client.post("/api/projects/demo/sessions").json()["id"]

    png = proj_root / "plot.png"

    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "go"})

        done_ev: dict | None = None
        seen_start = False
        while True:
            ev = ws.receive_json()
            if ev["type"] == "assistant_start" and not seen_start:
                seen_start = True
                # Snapshot was taken just before _run_turn; write the file
                # NOW so it is new relative to the before-snapshot.
                png.write_bytes(b"\x89PNG\r\n\x1a\n")
            if ev["type"] == "done":
                done_ev = ev
                break

    assert done_ev is not None
    artifacts = done_ev.get("artifacts", [])
    rel_paths = [a["rel_path"] for a in artifacts]
    assert "plot.png" in rel_paths


def test_message_history_persists(client):
    sid = client.post("/api/projects/demo/sessions").json()["id"]

    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "remember this"})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "done":
                break

    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()
    assert any("remember this" in m["content"] for m in msgs)
    assert any(m["role"] == "assistant" for m in msgs)
