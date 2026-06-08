"""Smoke tests: import, EchoAgent REST + WS round-trip, artifact surfacing."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from lmc.config import Paths, Settings
from lmc.projects import Registry
from lmc.server import create_app


@pytest.fixture
def tmp_paths(tmp_path: Path) -> Paths:
    p = Paths(config_dir=tmp_path / "config", state_dir=tmp_path / "state")
    p.ensure()
    return p


@pytest.fixture
def proj_root(tmp_path: Path) -> Path:
    d = tmp_path / "demo"
    d.mkdir()
    return d


@pytest.fixture
def echo_settings() -> Settings:
    return Settings(agent="echo")


@pytest.fixture
def client(tmp_paths: Paths, proj_root: Path, echo_settings: Settings) -> TestClient:
    reg = Registry(tmp_paths)
    reg.add("demo", str(proj_root))
    app = create_app(paths=tmp_paths, settings=echo_settings)
    return TestClient(app, raise_server_exceptions=True)


def test_import() -> None:
    """create_app must be importable and callable without error."""
    from lmc.server import create_app as _ca
    cfg = _ca.__module__
    assert "lmc.server" in cfg


def test_list_projects(client: TestClient) -> None:
    r = client.get("/api/projects")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert any(p["name"] == "demo" for p in data)


def test_create_and_list_session(client: TestClient) -> None:
    r = client.post("/api/projects/demo/sessions")
    assert r.status_code == 200
    sid = r.json()["id"]
    r2 = client.get("/api/projects/demo/sessions")
    assert r2.status_code == 200
    assert any(s["id"] == sid for s in r2.json())


def test_session_not_found(client: TestClient) -> None:
    r = client.get("/api/sessions/doesnotexist/messages")
    assert r.status_code == 404


def test_echo_ws_roundtrip(client: TestClient) -> None:
    sid = client.post("/api/projects/demo/sessions").json()["id"]
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "hello"})
        events = []
        while True:
            msg = ws.receive_json()
            events.append(msg)
            if msg["type"] == "done":
                break
    types = [e["type"] for e in events]
    assert "user_message" in types
    assert "assistant_start" in types
    assert "done" in types
    # At least one delta event with echoed text
    deltas = [e for e in events if e["type"] == "delta"]
    assert len(deltas) > 0
    text = "".join(e["text"] for e in deltas)
    assert "hello" in text


def test_ping_pong(client: TestClient) -> None:
    sid = client.post("/api/projects/demo/sessions").json()["id"]
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "ping"})
        resp = ws.receive_json()
        assert resp["type"] == "pong"


def test_artifact_surfaced_after_file_drop(
    client: TestClient, proj_root: Path
) -> None:
    sid = client.post("/api/projects/demo/sessions").json()["id"]
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "generate"})
        # The EchoAgent streams text events then done.
        # Between the assistant_start and done we write a PNG so the diff
        # will catch it.
        events = []
        while True:
            msg = ws.receive_json()
            events.append(msg)
            if msg["type"] == "assistant_start":
                # Drop the file now — it will be found in the post-done diff.
                fig = proj_root / "figures"
                fig.mkdir(exist_ok=True)
                (fig / "result.png").write_bytes(b"\x89PNG\r\n")
            if msg["type"] == "done":
                break
    done_msg = next(e for e in events if e["type"] == "done")
    assert len(done_msg["artifacts"]) > 0
    assert any("result.png" in a["rel_path"] for a in done_msg["artifacts"])


def test_message_history_persists(client: TestClient) -> None:
    sid = client.post("/api/projects/demo/sessions").json()["id"]
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "remember this"})
        while True:
            msg = ws.receive_json()
            if msg["type"] == "done":
                break
    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert user_msg["content"] == "remember this"
