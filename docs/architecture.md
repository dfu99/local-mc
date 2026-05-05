# Architecture

This document explains *why* local-mc looks the way it does. For *what's
on disk*, see [`v0.1-scaffold.md`](v0.1-scaffold.md). For *what to do next*,
see [`../tasks/planning.md`](../tasks/planning.md).

## Goals

1. **Local-first.** Every byte of project content, chat history, and
   attachments stays on the user's machine. The only outbound network is
   whatever the underlying Claude Code CLI does (which the user's
   organization has presumably already approved separately).
2. **Multi-project.** A single window, one operator, many projects.
   Switching between projects is a click, not a `cd && tmux attach`.
3. **Media-aware.** Plots, screenshots, PDFs, and short videos render
   inline, not as paths to copy-paste into a viewer.
4. **Auditable.** A security-conscious IT team can read the whole
   codebase end-to-end. No bundler-generated minified blobs, no opaque
   binary dependencies.
5. **Portable.** Cloning the repo on a new machine and running two
   commands (install + serve) gets you to a working chat. State lives
   under XDG dirs, never in the repo.

## Non-goals

- **Real-time multi-user collaboration.** One operator, one machine.
- **Cloud sync.** Two installs are independent. If you want shared state,
  that's a v0.4+ conversation about an explicit, opt-in mechanism.
- **Generic LLM frontend.** This wraps Claude Code specifically. We rely
  on its CLI surface (`-p`, `--resume`, `--output-format stream-json`).
  Other models can plug in via the `Agent` interface, but they're not
  the priority.

## Big picture

```
┌──────────────────────┐
│      Browser         │  http://127.0.0.1:8765
│  ─ project sidebar   │
│  ─ chat panel        │
│  ─ attachment tray   │
│  ─ media viewer      │
└──────────┬───────────┘
           │ HTTP + WebSocket
           ▼
┌──────────────────────────────────────────────────────────┐
│              FastAPI server (lmc.server)                 │
│  /api/projects        ─ Registry (YAML)                  │
│  /api/sessions/...    ─ Store (SQLite)                   │
│  /api/sessions/.../upload                                 │
│      → writes into <project>/inbox/<sid>/                 │
│  WS  /api/sessions/.../chat                               │
│      → spawns `claude -p --resume <sid>` per turn         │
│      → streams stream-json events back as WS messages     │
│  /api/files?path=...                                      │
│      → serves files from inside any registered project    │
│        root only (sandboxed)                              │
└──────────────────────────────────────────────────────────┘
           │ subprocess (per turn)
           ▼
┌──────────────────────┐       ┌────────────────────────┐
│   `claude` CLI       │       │ project tree (cwd)     │
│   ─ stream-json out  │ ─────▶│  inbox/<sid>/<file>    │
│   ─ stream-json in   │       │  figures/, results/    │
│   ─ --resume <sid>   │       │  tasks/, src/, ...     │
└──────────────────────┘       └────────────────────────┘
```

## Why a per-turn subprocess

The original Mission Control keeps Claude alive in a tmux pane and uses
`tmux send-keys` to deliver new prompts. That works but it's brittle:

- Pane scraping breaks on resize, ANSI escapes, unexpected output.
- Crashed sessions need detection logic; you can't rely on exit codes.
- State lives in tmux, which is hard to test, back up, or replay.

Per-turn subprocess flips the model:

- Each user message → `claude -p "msg" --resume <claude_session_id>`.
- Output is structured JSON, parsed event-by-event.
- The exit code is meaningful. Crashes propagate cleanly.
- Session continuity comes from Claude Code's own `--resume` mechanism,
  which is its first-class feature for this exact use case.

The downside is per-turn spawn latency. Empirically (on the original
machine) `claude -p` cold-starts in well under a second; with prompt
caching warmed up, follow-up turns are fast. If this turns out to be a
problem on the target hardware, the `Agent` interface in `lmc/sessions.py`
makes it straightforward to swap in a long-lived implementation later.

## Why FastAPI + vanilla JS

**Python on the server.** The user's existing Mission Control is Python
+ bash. Same stack lowers the cognitive cost of switching. FastAPI gives
us async + WebSockets + Pydantic + auto-OpenAPI for free.

**No frontend framework.** The whole UI is three files. An IT auditor can
read every line in an afternoon. There's no `node_modules` to vet, no
supply-chain attack surface for npm packages, no transpiler-generated
output to chase. If complexity grows past what's tractable in vanilla JS,
the migration target is preact-via-CDN or Lit (web-components), not React.

**SQLite.** Single file, ships with Python, ACID, no server. Replays a
session = `cp lmc.db backup.db`.

## Storage layout

Two roots, both under XDG defaults (override with `LMC_HOME`):

```
~/.config/lmc/
  ├── projects.yaml      project registry
  └── settings.yaml      runtime settings (host, port, agent, etc.)

~/.local/share/lmc/
  ├── lmc.db             SQLite: sessions, messages, attachments
  ├── attachments/       (reserved — currently unused)
  └── logs/              (reserved — currently unused)
```

Per-project state lives in the project's own tree, never under
`~/.local/share/lmc`:

```
<project>/
  └── inbox/
      └── <session_id>/
          ├── 1714938273-a8b3c1-screenshot.png
          └── 1714938301-d4e2f0-spec.pdf
```

This is intentional. It means:
- Backing up a project carries its conversation context with it.
- The agent's `Read` tool can see attachments because they're under cwd.
- Wiping a session = `rm -rf <project>/inbox/<sid>`.

## Streaming chat protocol

The WebSocket carries JSON messages in both directions.

**Client → server:**

```json
{ "type": "message", "text": "regenerate the loss curve",
  "attachments": [{ "filename": "...", "path": "...", ... }] }
```

(Attachments are uploaded via REST `POST /api/sessions/.../upload`
*before* sending the message; the message references them by path so
the agent can `Read` them.)

**Server → client:**

```json
{ "type": "user_message", "message": { ... } }
{ "type": "assistant_start", "message_id": 42 }
{ "type": "delta", "message_id": 42, "text": "Sure, " }
{ "type": "delta", "message_id": 42, "text": "let me " }
{ "type": "tool_use", "message_id": 42, "data": { "name": "Read", ... } }
{ "type": "tool_result", "message_id": 42, "data": { ... } }
{ "type": "delta", "message_id": 42, "text": "...done." }
{ "type": "done", "message_id": 42, "artifacts": [...], "stats": { ... } }
```

`done` includes any new files the agent created during the turn,
discovered via the artifact-snapshot mechanism (see below).

## Artifact discovery

When a turn starts, the server takes a snapshot — `{abs_path: mtime}` for
every file in the project matching configured globs (`figures/**/*`,
`results/**/*`, `*.png`, `*.pdf`, etc.).

When the turn finishes, it diffs against the current state. Anything new
or modified is reported as an artifact in the `done` event. The browser
renders each artifact inline based on MIME type (image / video / PDF /
fallback link).

This is intentionally not a long-running file-watcher (`watchfiles` /
`inotify`). Reasons:
- Watchers have lifecycle (start, stop, restart on glob change).
- Heavy filesystem activity (e.g. a build) can drop events.
- The cost of one snapshot is microseconds for a project with hundreds
  of matched files. Not worth optimizing.

## Security boundaries

- **Bind address.** 127.0.0.1 by default. To expose on the LAN, the user
  must explicitly set `host: 0.0.0.0` *and* (when implemented) supply a
  token. We will never silently widen the bind.
- **CORS.** Allowed origins are localhost-only.
- **File serving.** `/api/files?path=...` resolves the requested path and
  refuses if it's outside any registered project root. This prevents the
  browser from extracting arbitrary files just because the server has
  read access.
- **Upload paths.** Filenames are stripped of path separators and
  sanitized; uploads land in `<project>/inbox/<sid>/<safe-name>`, never
  outside the project.
- **No code execution endpoints.** The server does not expose `POST
  /api/exec` or similar. The agent runs commands; the user runs the
  agent. There is no path for the browser to ask the server to shell out
  directly.

## What this is *not* doing right

- **Tests.** None yet. The `EchoAgent` is set up specifically to make
  testing without a real Claude binary straightforward, but the tests
  haven't been written.
- **Verified CLI invocation.** The exact flag combination passed to
  `claude` was specified from memory and not run end-to-end. See
  `tasks/lessons.md`. Verify before deploying.
- **Resilience to crashed turns.** If `claude` exits mid-stream, the
  server records an error event. There's no auto-retry, no partial-state
  cleanup beyond what SQLite gives for free.

These are explicitly punted to v0.2 — see `../tasks/planning.md`.
