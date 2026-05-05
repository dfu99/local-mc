"""Per-message Claude Code subprocess driver.

Why per-message instead of a long-running TTY: simpler, more robust, and
matches Claude Code's own --resume / --continue model. Each user turn invokes
``claude -p "msg" --resume <claude_session_id>`` (or --continue for the first
turn), then we stream the response back via the stream-json output format.

For testing or demos without a Claude binary, set ``settings.agent = 'echo'``
and the ``EchoAgent`` will reflect the user's message back.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from .config import Settings


@dataclass
class AgentEvent:
    """One streaming event from the agent.

    type:
        'text'       — text delta to append to the current assistant message
        'tool_use'   — tool invocation summary
        'tool_result'— result of a tool call
        'session_id' — Claude session id (saved by store, used for next turn)
        'done'       — final event; ``data`` may include cost/tokens
        'error'      — agent failed; ``data['message']`` has details
    """

    type: str
    data: dict


# Agents implement an async-generator method:
#
#     async def stream(self, message, *, cwd, claude_session_id, attachments):
#         yield AgentEvent(...)
#
# We don't formalize this with typing.Protocol because async-generator method
# protocols don't round-trip cleanly through Pyright. Duck typing is fine —
# both ClaudeAgent and EchoAgent below match the same shape.
Agent = object  # nominal alias for type hints


# ── Claude CLI agent ────────────────────────────────────────────────────


class ClaudeAgent:
    """Wraps the ``claude`` CLI in non-interactive mode."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _resolve_bin(self) -> str:
        bin_name = self.settings.claude_bin
        path = shutil.which(bin_name)
        if path:
            return path
        # Fall through to the bare name; subprocess will raise if missing.
        return bin_name

    def _build_argv(self, claude_session_id: str | None) -> list[str]:
        argv = [
            self._resolve_bin(),
            "-p",
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
        ]
        if self.settings.permission_mode and self.settings.permission_mode != "default":
            argv += ["--permission-mode", self.settings.permission_mode]
        if claude_session_id:
            argv += ["--resume", claude_session_id]
        return argv

    async def stream(
        self,
        message: str,
        *,
        cwd: str,
        claude_session_id: str | None,
        attachments: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        argv = self._build_argv(claude_session_id)

        # Compose user content. Attachments are referenced by absolute path so
        # Claude can read them via its built-in tools (Read, Bash). We do not
        # attempt to inline binary content — that's the agent's job.
        prompt_text = message
        if attachments:
            lines = [message, "", "Attached files (read these from disk):"]
            for p in attachments:
                lines.append(f"  - {p}")
            prompt_text = "\n".join(lines)

        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

        # Send the user message as a single stream-json event, then close stdin.
        user_event = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": prompt_text}],
            },
        }
        try:
            proc.stdin.write((json.dumps(user_event) + "\n").encode())
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

        async for ev in self._read_stream(proc):
            yield ev

        rc = await proc.wait()
        if rc != 0:
            stderr = (await proc.stderr.read()).decode(errors="replace")
            yield AgentEvent(
                type="error",
                data={"message": f"claude exited with code {rc}: {stderr[:500]}"},
            )

    async def _read_stream(
        self, proc: asyncio.subprocess.Process
    ) -> AsyncIterator[AgentEvent]:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                obj = json.loads(line.decode().strip())
            except json.JSONDecodeError:
                continue
            for ev in self._parse_event(obj):
                yield ev

    def _parse_event(self, obj: dict) -> list[AgentEvent]:
        """Translate a Claude stream-json event into AgentEvent(s)."""
        events: list[AgentEvent] = []
        kind = obj.get("type")

        # The init / system event carries the session id.
        if kind == "system" and obj.get("subtype") == "init":
            sid = obj.get("session_id")
            if sid:
                events.append(AgentEvent("session_id", {"session_id": sid}))

        # Assistant tokens arrive as 'assistant' events with content blocks.
        if kind == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []) or []:
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text:
                        events.append(AgentEvent("text", {"text": text}))
                elif btype == "tool_use":
                    events.append(
                        AgentEvent(
                            "tool_use",
                            {
                                "name": block.get("name", ""),
                                "input": block.get("input", {}),
                                "id": block.get("id", ""),
                            },
                        )
                    )

        # Tool results arrive as 'user' messages with tool_result content.
        if kind == "user":
            msg = obj.get("message", {})
            for block in msg.get("content", []) or []:
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        text_parts = [
                            c.get("text", "")
                            for c in content
                            if c.get("type") == "text"
                        ]
                        content = "\n".join(text_parts)
                    events.append(
                        AgentEvent(
                            "tool_result",
                            {
                                "tool_use_id": block.get("tool_use_id", ""),
                                "content": content or "",
                                "is_error": bool(block.get("is_error")),
                            },
                        )
                    )

        # The final 'result' event signals completion.
        if kind == "result":
            events.append(
                AgentEvent(
                    "done",
                    {
                        "duration_ms": obj.get("duration_ms"),
                        "total_cost_usd": obj.get("total_cost_usd"),
                        "num_turns": obj.get("num_turns"),
                    },
                )
            )

        return events


# ── Echo agent (for tests / demos) ──────────────────────────────────────


class EchoAgent:
    """Reflects the user's message back, simulating a streaming response.

    Useful for: running tests without a Claude binary, demo videos, smoke
    tests, and CI environments that can't or shouldn't hit the API.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings

    async def stream(
        self,
        message: str,
        *,
        cwd: str,
        claude_session_id: str | None,
        attachments: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        if claude_session_id is None:
            yield AgentEvent("session_id", {"session_id": f"echo-{int(time.time())}"})

        prefix = f"(echo @ {Path(cwd).name})\n\n"
        words = (prefix + message).split(" ")
        for w in words:
            yield AgentEvent("text", {"text": w + " "})
            await asyncio.sleep(0.01)

        if attachments:
            yield AgentEvent(
                "text",
                {"text": f"\n\nAttachments: {', '.join(attachments)}"},
            )

        yield AgentEvent(
            "done",
            {"duration_ms": 100, "total_cost_usd": 0.0, "num_turns": 1},
        )


def make_agent(settings: Settings):
    """Construct the configured agent (ClaudeAgent or EchoAgent)."""
    if settings.agent == "echo":
        return EchoAgent(settings)
    return ClaudeAgent(settings)
