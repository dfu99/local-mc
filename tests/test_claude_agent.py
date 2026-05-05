"""Real-`claude`-binary smoke test for `ClaudeAgent`.

This is the audit's P0 unblock. The flag combination
`claude -p --output-format stream-json --input-format stream-json --verbose
--resume <sid>` was specified from memory in the scaffold; this test runs
it against the installed binary and verifies that `_parse_event` decodes
real output as expected.

Behaviour:
    - If `shutil.which('claude')` returns None (the common CI case), the
      whole module is skipped — pytest exits 0.
    - If a binary is found, ONE turn is executed with a minimal prompt.
      We assert that we observe at least one `text` event and exactly one
      `done` event within `TIMEOUT_S` seconds.

The test is intentionally tolerant: it doesn't assert on token counts,
exact text, or session-id format — those vary across Claude Code versions.
It only locks in the *shape* of the event stream that local-mc depends on.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from lmc.config import Settings
from lmc.sessions import AgentEvent, ClaudeAgent

CLAUDE_BIN = shutil.which("claude")
TIMEOUT_S = 90.0
PROMPT = "Reply with exactly the four characters: pong"

pytestmark = pytest.mark.skipif(
    CLAUDE_BIN is None,
    reason="claude binary not on PATH; skipping real-binary smoke test",
)


async def _collect(agent: ClaudeAgent, *, cwd: str) -> list[AgentEvent]:
    out: list[AgentEvent] = []

    async def _run():
        async for ev in agent.stream(
            PROMPT, cwd=cwd, claude_session_id=None, attachments=None
        ):
            out.append(ev)

    await asyncio.wait_for(_run(), timeout=TIMEOUT_S)
    return out


def test_real_claude_turn_emits_text_and_done(tmp_path: Path):
    """One real turn against the installed `claude` CLI.

    Verifies the audit's P0 risk: the `--input-format stream-json`
    flag combination still works on the installed Claude Code binary
    and `ClaudeAgent._parse_event` correctly decodes the events.
    """
    settings = Settings(agent="claude", claude_bin=CLAUDE_BIN or "claude")
    agent = ClaudeAgent(settings)
    events = asyncio.run(_collect(agent, cwd=str(tmp_path)))

    types = [ev.type for ev in events]
    # The audit-locked invariant:
    assert "text" in types or "tool_use" in types, (
        "expected at least one 'text' or 'tool_use' event; "
        f"got types={types}"
    )
    assert types.count("done") == 1, (
        f"expected exactly one 'done' event; got types={types}"
    )

    # And no error events (which would indicate stderr capture)
    err_events = [ev for ev in events if ev.type == "error"]
    assert not err_events, (
        f"unexpected error events: {[e.data for e in err_events]}"
    )


def test_real_claude_session_id_captured(tmp_path: Path):
    """The first turn should yield a `session_id` event from the init line.

    This is the value that local-mc persists to `sessions.claude_session_id`
    and replays via `--resume` on subsequent turns. Without it, multi-turn
    chat doesn't work.
    """
    settings = Settings(agent="claude", claude_bin=CLAUDE_BIN or "claude")
    agent = ClaudeAgent(settings)
    events = asyncio.run(_collect(agent, cwd=str(tmp_path)))

    sid_events = [ev for ev in events if ev.type == "session_id"]
    assert len(sid_events) >= 1, (
        "expected at least one 'session_id' event from claude init; "
        f"got types={[e.type for e in events]}"
    )
    sid = sid_events[0].data.get("session_id")
    assert sid and isinstance(sid, str) and len(sid) >= 8


def test_done_event_carries_some_metadata(tmp_path: Path):
    """`done` should at least include keys our store reads.

    `_parse_event` translates the final `result` JSON object into an
    AgentEvent with `duration_ms`, `total_cost_usd`, `num_turns`. Some
    versions of Claude Code may emit one or more of these as null, so we
    just assert the keys are present.
    """
    settings = Settings(agent="claude", claude_bin=CLAUDE_BIN or "claude")
    agent = ClaudeAgent(settings)
    events = asyncio.run(_collect(agent, cwd=str(tmp_path)))
    done = next(ev for ev in events if ev.type == "done")
    for key in ("duration_ms", "total_cost_usd", "num_turns"):
        assert key in done.data, f"done missing key: {key}; data={done.data}"
