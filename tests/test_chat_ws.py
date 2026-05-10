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


def test_cancel_stops_a_running_turn(client: TestClient, project_dir: Path):
    """`{type:cancel}` aborts the agent stream and the client gets `cancelled`.

    EchoAgent paces ~one delta per 10 ms. A 200-word message takes ~2 s, so
    a cancel sent right after `assistant_start` should land before the stream
    drains naturally. We assert: a `cancelled` event lands, *no* `done` event
    lands, and fewer than 200 deltas streamed before the cancel took effect.
    """
    sid = _create_session(client, project_dir)
    long_text = " ".join([f"w{i}" for i in range(200)])
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": long_text})
        first = ws.receive_json()
        second = ws.receive_json()
        assert first["type"] == "user_message"
        assert second["type"] == "assistant_start"
        ws.send_json({"type": "cancel"})

        events: list[dict] = []
        for _ in range(400):
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("cancelled", "done", "error"):
                break

    types = [e["type"] for e in events]
    assert "cancelled" in types
    assert "done" not in types
    assert types.count("delta") < 200


def test_cancel_with_no_active_turn_is_a_no_op(
    client: TestClient, project_dir: Path
):
    """A spurious cancel must not break the socket or wedge the loop."""
    sid = _create_session(client, project_dir)
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "cancel"})
        # Socket should still be alive — verify with a ping/pong round-trip.
        ws.send_json({"type": "ping"})
        ev = ws.receive_json()
        assert ev == {"type": "pong"}


def test_message_during_active_turn_is_rejected(
    client: TestClient, project_dir: Path
):
    """Server refuses a second message while one is mid-flight.

    Locks down a small but real footgun: if the client double-clicks Send,
    we'd otherwise spawn two competing tasks that both write to the socket.
    """
    sid = _create_session(client, project_dir)
    long_text = " ".join([f"w{i}" for i in range(80)])
    with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
        ws.send_json({"type": "message", "text": long_text})
        ws.receive_json()  # user_message
        ws.receive_json()  # assistant_start
        ws.send_json({"type": "message", "text": "second"})
        # The "in progress" error arrives before the next delta — but we're
        # tolerant in case scheduling lets a delta sneak in.
        for _ in range(20):
            ev = ws.receive_json()
            if ev.get("type") == "error":
                assert "in progress" in ev["message"]
                break
        else:
            raise AssertionError("expected an 'in progress' error")
        # Cancel to free the turn so the WS context manager doesn't hang.
        ws.send_json({"type": "cancel"})
        for _ in range(400):
            ev = ws.receive_json()
            if ev["type"] in ("cancelled", "done"):
                break


def test_client_app_js_has_cancel_and_reconnect_wiring():
    """Structural pin so a future refactor can't silently strip these.

    The browser side has no unit-test harness; this is a cheap canary
    that the cancel + reconnect logic survives an app.js rewrite. If
    the names change, update both ends so the contract stays intact.
    """
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "lmc" / "web" / "app.js"
    src = js.read_text()
    assert "cancelTurn" in src, "cancel handler missing from app.js"
    assert '"cancel"' in src, 'cancel must be sent as {"type":"cancel"}'
    assert "reconnectAttempts" in src, "reconnect bookkeeping missing"
    assert "RECONNECT_DELAY_MS" in src, "exponential backoff schedule missing"
    assert "userClosedSocket" in src, "intentional-close guard missing"


def test_client_index_html_has_cancel_button():
    from pathlib import Path

    html = Path(__file__).resolve().parents[1] / "lmc" / "web" / "index.html"
    src = html.read_text()
    assert 'id="cancel"' in src
    # Default-hidden so it doesn't sit empty next to Send when idle.
    assert 'id="cancel" type="button" hidden' in src


def test_settings_artifact_globs_filter_done_artifacts(
    project_dir: Path, lmc_paths
):
    """Confirms `Settings.artifact_globs` is plumbed through to the WS turn.

    Before q06 the server called `snapshot(proj.path)` and `diff(proj.path,
    snap)` without passing `settings.artifact_globs` — meaning the user
    setting was silently ignored. Pin the regression: set globs to match
    only `figures/*.png` and assert a `.csv` plant doesn't surface.
    """
    from fastapi.testclient import TestClient
    from lmc.config import Settings
    from lmc.server import create_app

    settings = Settings(agent="echo", artifact_globs=["figures/*.png"])
    app = create_app(paths=lmc_paths, settings=settings)
    with TestClient(app) as client:
        sid = _create_session(client, project_dir)
        (project_dir / "figures").mkdir()
        with client.websocket_connect(f"/api/sessions/{sid}/chat") as ws:
            ws.send_json({"type": "message", "text": "go"})
            ws.receive_json()  # user_message
            ws.receive_json()  # assistant_start
            (project_dir / "figures" / "loss.png").write_bytes(b"\x89PNG")
            (project_dir / "ignore.csv").write_text("a,b\n1,2\n")
            rest = _drain(ws)

        done = next(e for e in rest if e["type"] == "done")
        rels = [a["rel_path"] for a in done["artifacts"]]
        assert any(r.endswith("loss.png") for r in rels)
        assert not any(r.endswith("ignore.csv") for r in rels)
