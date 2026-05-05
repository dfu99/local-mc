"""WebSocket chat — EchoAgent end-to-end.

Locks in the protocol contract `docs/architecture.md` advertises:

    user_message → assistant_start → delta+ → done

EchoAgent makes this safe to run in CI (no real `claude` binary needed).
The real-`claude` test lives in `tests/test_claude_agent.py` and is gated
behind `shutil.which('claude')`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _create_session(client: TestClient, project_dir: Path) -> str:
    client.post(
        "/api/projects",
        json={"name": "demo", "path": str(project_dir)},
    )
    return client.post("/api/projects/demo/sessions").json()["id"]


def _drain(ws, *, max_events: int = 200, until_done: bool = True) -> list[dict]:
    """Pull JSON events until we see `done` or run out of room."""
    events: list[dict] = []
    for _ in range(max_events):
        ev = ws.receive_json()
        events.append(ev)
        if until_done and ev.get("type") in ("done", "error"):
            break
    return events


def test_full_echo_turn_emits_protocol_in_order(client: TestClient, project_dir: Path):
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "hello local-mc"})
        events = _drain(ws)

    types = [e["type"] for e in events]
    assert types[0] == "user_message"
    assert "assistant_start" in types
    assert types.count("delta") >= 1
    assert types[-1] == "done"

    # Order: assistant_start strictly before any delta, deltas before done.
    a_start = types.index("assistant_start")
    first_delta = types.index("delta")
    last_delta = max(i for i, t in enumerate(types) if t == "delta")
    assert a_start < first_delta < types.index("done")
    assert last_delta < types.index("done")


def test_user_message_persists_with_attachments(client: TestClient, project_dir: Path):
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({
            "type": "message",
            "text": "see attached",
            "attachments": [
                {"filename": "spec.pdf", "path": "/tmp/x.pdf", "size": 12, "mime": "application/pdf"}
            ],
        })
        _drain(ws)

    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert user_msg["content"] == "see attached"
    assert user_msg["attachments"][0]["filename"] == "spec.pdf"


def test_assistant_message_accumulates_deltas_in_store(
    client: TestClient, project_dir: Path
):
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "hi there"})
        events = _drain(ws)

    delta_concat = "".join(
        e["text"] for e in events if e["type"] == "delta"
    )
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    assistant = next(m for m in msgs if m["role"] == "assistant")
    assert assistant["content"] == delta_concat
    assert "hi there" in assistant["content"]  # echoed back


def test_done_event_carries_stats(client: TestClient, project_dir: Path):
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "ping"})
        events = _drain(ws)
    done = next(e for e in events if e["type"] == "done")
    assert "stats" in done
    assert "duration_ms" in done["stats"]
    # EchoAgent reports a flat stat profile; just assert presence.
    assert "artifacts" in done


def test_done_artifacts_picks_up_new_files_in_project(
    client: TestClient, project_dir: Path
):
    sid = _create_session(client, project_dir)
    figures_dir = project_dir / "figures"
    figures_dir.mkdir()
    # snapshot is taken at turn-start, so create the file AFTER the WS message.
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": "make a plot"})
        # Grab the assistant_start so we know the snapshot has been captured
        first = ws.receive_json()
        second = ws.receive_json()
        assert first["type"] == "user_message"
        assert second["type"] == "assistant_start"
        # Now plant a file as if the agent generated it
        new_png = figures_dir / "loss.png"
        new_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        # Drain the rest
        rest = _drain(ws)

    done = next(e for e in rest if e["type"] == "done")
    paths = [a["rel_path"] for a in done["artifacts"]]
    assert any(p.endswith("loss.png") for p in paths)


def test_ping_pong(client: TestClient, project_dir: Path):
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "ping"})
        ev = ws.receive_json()
        assert ev == {"type": "pong"}


def test_unknown_event_type_returns_error(client: TestClient, project_dir: Path):
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "garbage"})
        ev = ws.receive_json()
        assert ev["type"] == "error"
        assert "expected" in ev["message"]
