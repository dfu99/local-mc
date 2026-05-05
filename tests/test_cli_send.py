"""`lmc send` CLI subcommand — round-trips through EchoAgent.

Mirrors `mc send` from the original Mission Control. The smallest piece
of v0.2: gives scripted workflows a way to push a prompt into a project
without going through the browser.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lmc.cli import main


@pytest.fixture
def env_isolation(monkeypatch, tmp_path: Path):
    """Force `get_paths()` to use this test's tmp dirs."""
    monkeypatch.setenv("LMC_HOME", str(tmp_path / "lmc"))
    return tmp_path


def _seed(env_isolation: Path):
    """Run `lmc init` + `lmc add` to set up a project."""
    proj_dir = env_isolation / "demo-project"
    proj_dir.mkdir()
    assert main(["init"]) == 0
    assert main(["add", "demo", str(proj_dir)]) == 0
    # Force echo agent so we don't shell out to claude
    assert main(["settings", "--set", "agent=echo"]) == 0
    return proj_dir


def test_send_round_trips_through_echo(env_isolation, capsys):
    _seed(env_isolation)
    rc = main(["send", "demo", "hello world"])
    assert rc == 0
    captured = capsys.readouterr()
    # EchoAgent reflects the message back, prefixed with "(echo @ <name>)"
    assert "hello world" in captured.out
    assert "echo @ demo-project" in captured.out
    assert "[done]" in captured.out


def test_send_quiet_suppresses_stream(env_isolation, capsys):
    _seed(env_isolation)
    rc = main(["send", "demo", "ping", "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[done]" in out
    # Echo'd text should be absent in quiet mode
    assert "(echo @" not in out
    assert "ping" not in out.replace("[done]", "")  # ignore "done" header


def test_send_unknown_project_returns_1(env_isolation, capsys):
    _seed(env_isolation)
    rc = main(["send", "ghost", "hi"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown project" in err


def test_send_missing_path_returns_1(env_isolation, capsys, tmp_path: Path):
    _seed(env_isolation)
    # Move the project dir away to simulate a stale registry entry
    proj_dir = env_isolation / "demo-project"
    proj_dir.rename(tmp_path / "moved")
    rc = main(["send", "demo", "hi"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "project path missing" in err


def test_send_persists_to_store(env_isolation):
    """After `lmc send`, the user message + assistant reply are in SQLite."""
    _seed(env_isolation)
    main(["send", "demo", "remember me"])

    # Reach into the store with the same LMC_HOME
    from lmc.config import get_paths
    from lmc.store import Store
    store = Store(paths=get_paths())
    sessions = store.list_sessions("demo")
    assert len(sessions) >= 1
    msgs = store.messages(sessions[0].id)
    contents = [m.content for m in msgs]
    assert "remember me" in contents
    assert any("remember me" in c for c in contents if c != "remember me"), (
        "echo agent reply should also be in store"
    )


def test_send_subsequent_calls_reuse_latest_session(env_isolation):
    _seed(env_isolation)
    main(["send", "demo", "first"])
    main(["send", "demo", "second"])
    from lmc.config import get_paths
    from lmc.store import Store
    store = Store(paths=get_paths())
    sessions = store.list_sessions("demo")
    # Both messages should land in the same session (second call reused).
    assert len(sessions) == 1
    msgs = store.messages(sessions[0].id)
    user_msgs = [m for m in msgs if m.role == "user"]
    assert [m.content for m in user_msgs] == ["first", "second"]
