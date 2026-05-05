"""Tests for lmc/sessions.py — EchoAgent stream, make_agent factory."""
from __future__ import annotations

import pytest

from lmc.config import Settings
from lmc.sessions import AgentEvent, EchoAgent, make_agent


# ── EchoAgent ─────────────────────────────────────────────────────────────


async def _collect(agent, message, *, cwd="/tmp", claude_session_id=None, attachments=None):
    events: list[AgentEvent] = []
    async for ev in agent.stream(
        message,
        cwd=cwd,
        claude_session_id=claude_session_id,
        attachments=attachments,
    ):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_echo_emits_text_events(tmp_path):
    agent = EchoAgent()
    events = await _collect(agent, "hello", cwd=str(tmp_path))
    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) > 0
    full = "".join(e.data["text"] for e in text_events)
    assert "hello" in full


@pytest.mark.asyncio
async def test_echo_emits_done(tmp_path):
    agent = EchoAgent()
    events = await _collect(agent, "hi", cwd=str(tmp_path))
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1
    assert done[0].data["num_turns"] == 1
    assert done[0].data["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_echo_emits_session_id_on_new_session(tmp_path):
    agent = EchoAgent()
    events = await _collect(agent, "hi", cwd=str(tmp_path), claude_session_id=None)
    sid_events = [e for e in events if e.type == "session_id"]
    assert len(sid_events) == 1
    assert sid_events[0].data["session_id"].startswith("echo-")


@pytest.mark.asyncio
async def test_echo_no_session_id_when_resuming(tmp_path):
    agent = EchoAgent()
    events = await _collect(agent, "hi", cwd=str(tmp_path), claude_session_id="existing-123")
    sid_events = [e for e in events if e.type == "session_id"]
    assert len(sid_events) == 0


@pytest.mark.asyncio
async def test_echo_includes_cwd_name(tmp_path):
    proj = tmp_path / "myproject"
    proj.mkdir()
    agent = EchoAgent()
    events = await _collect(agent, "test", cwd=str(proj))
    full = "".join(e.data["text"] for e in events if e.type == "text")
    assert "myproject" in full


@pytest.mark.asyncio
async def test_echo_mentions_attachments(tmp_path):
    agent = EchoAgent()
    events = await _collect(
        agent, "look", cwd=str(tmp_path), attachments=["/tmp/file.pdf"]
    )
    full = "".join(e.data.get("text", "") for e in events if e.type == "text")
    assert "/tmp/file.pdf" in full


@pytest.mark.asyncio
async def test_echo_no_attachment_text_when_none(tmp_path):
    agent = EchoAgent()
    events = await _collect(agent, "hi", cwd=str(tmp_path), attachments=None)
    full = "".join(e.data.get("text", "") for e in events if e.type == "text")
    assert "Attachments" not in full


@pytest.mark.asyncio
async def test_echo_event_ordering(tmp_path):
    agent = EchoAgent()
    events = await _collect(agent, "order", cwd=str(tmp_path), claude_session_id=None)
    types = [e.type for e in events]
    # session_id must come before text, done must be last
    assert types[0] == "session_id"
    assert types[-1] == "done"
    assert "text" in types


# ── AgentEvent ────────────────────────────────────────────────────────────


def test_agent_event_fields():
    ev = AgentEvent(type="text", data={"text": "hello"})
    assert ev.type == "text"
    assert ev.data == {"text": "hello"}


# ── make_agent factory ────────────────────────────────────────────────────


def test_make_agent_echo():
    s = Settings(agent="echo")
    agent = make_agent(s)
    assert isinstance(agent, EchoAgent)


def test_make_agent_claude():
    from lmc.sessions import ClaudeAgent
    s = Settings(agent="claude")
    agent = make_agent(s)
    assert isinstance(agent, ClaudeAgent)


def test_make_agent_echo_settings_stored():
    s = Settings(agent="echo")
    agent = make_agent(s)
    assert isinstance(agent, EchoAgent)
    assert agent.settings is s
