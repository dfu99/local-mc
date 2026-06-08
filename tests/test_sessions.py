"""Tests for lmc/sessions.py — EchoAgent and make_agent."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lmc.config import Settings
from lmc.sessions import AgentEvent, EchoAgent, make_agent


async def _collect(agent, message: str, *, cwd: str, claude_session_id=None, attachments=None):
    events = []
    async for ev in agent.stream(message, cwd=cwd, claude_session_id=claude_session_id, attachments=attachments):
        events.append(ev)
    return events


def test_echo_emits_text_events(tmp_path: Path) -> None:
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "hello world", cwd=str(tmp_path)))
    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) > 0
    combined = "".join(e.data["text"] for e in text_events)
    assert "hello" in combined


def test_echo_emits_done(tmp_path: Path) -> None:
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "hi", cwd=str(tmp_path)))
    done_events = [e for e in events if e.type == "done"]
    assert len(done_events) == 1


def test_echo_emits_session_id_on_new_session(tmp_path: Path) -> None:
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "hi", cwd=str(tmp_path), claude_session_id=None))
    sid_events = [e for e in events if e.type == "session_id"]
    assert len(sid_events) == 1
    assert "session_id" in sid_events[0].data


def test_echo_no_session_id_when_resuming(tmp_path: Path) -> None:
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "hi", cwd=str(tmp_path), claude_session_id="existing-id"))
    sid_events = [e for e in events if e.type == "session_id"]
    assert len(sid_events) == 0


def test_echo_includes_cwd_name(tmp_path: Path) -> None:
    proj = tmp_path / "myproject"
    proj.mkdir()
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "test", cwd=str(proj)))
    text = "".join(e.data["text"] for e in events if e.type == "text")
    assert "myproject" in text


def test_echo_mentions_attachments(tmp_path: Path) -> None:
    agent = EchoAgent()
    paths = ["/tmp/file1.png", "/tmp/file2.pdf"]
    events = asyncio.run(_collect(agent, "check files", cwd=str(tmp_path), attachments=paths))
    text = "".join(e.data["text"] for e in events if e.type == "text")
    assert "file1.png" in text or "Attachments" in text


def test_echo_no_attachment_text_when_none(tmp_path: Path) -> None:
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "no files", cwd=str(tmp_path), attachments=None))
    text = "".join(e.data["text"] for e in events if e.type == "text")
    assert "Attachments" not in text


def test_echo_event_ordering(tmp_path: Path) -> None:
    agent = EchoAgent()
    events = asyncio.run(_collect(agent, "order test", cwd=str(tmp_path)))
    types = [e.type for e in events]
    # session_id (if any) must come before text events, done must be last
    if "session_id" in types:
        assert types.index("session_id") < types.index("text")
    assert types[-1] == "done"


def test_agent_event_fields() -> None:
    ev = AgentEvent(type="text", data={"text": "hello"})
    assert ev.type == "text"
    assert ev.data == {"text": "hello"}


def test_make_agent_echo() -> None:
    settings = Settings(agent="echo")
    agent = make_agent(settings)
    assert isinstance(agent, EchoAgent)


def test_make_agent_claude() -> None:
    from lmc.sessions import ClaudeAgent
    settings = Settings(agent="claude")
    agent = make_agent(settings)
    assert isinstance(agent, ClaudeAgent)


def test_make_agent_echo_settings_stored() -> None:
    settings = Settings(agent="echo")
    agent = make_agent(settings)
    assert isinstance(agent, EchoAgent)
    assert agent.settings is settings
