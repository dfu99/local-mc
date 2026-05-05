# local-mc — Lessons

Append-mostly. Add a lesson before you forget the why; don't remove unless
proven wrong.

## Process

### Don't ship before testing

The v0.1 scaffold (2026-05-05) was written without ever running. Several
flag choices in `lmc/sessions.py` (specifically `claude -p --input-format
stream-json --output-format stream-json --resume`) were guessed from
recollection of the Claude Code CLI rather than verified against the
installed binary. **Verify CLI flags against the actual `claude` binary on
the target machine before assuming the agent code works.** A 60-second smoke
test would have caught this.

## Architecture

### Per-message subprocess > long-running TTY

The original Mission Control runs Claude in a long-lived tmux pane and
scrapes pane output to detect activity / idle / errors. That's powerful but
brittle — pane-scraping breaks on terminal resize, ANSI sequences,
unexpected output, etc. local-mc deliberately uses `claude -p --resume
<sid>` per turn instead. **Do not be tempted to bring back the long-lived
TTY model** for "performance" without first measuring whether per-turn
spawn latency is actually a problem on this hardware.

**Why:** Robustness, testability (can mock the subprocess in tests),
no-state-in-tmux. **How to apply:** If the v0.2 AFK autochain feels like
it would benefit from a single long-lived process, resist. Spawn per-turn
and let `--resume` carry the session.

### SQLite for chat history, not files

Chat history could be a directory of JSONL files (one per session). It
isn't. It's one SQLite file. **Why:** atomic appends during streaming,
trivial cross-session queries, single-file backup / migration. **How to
apply:** Don't add a "filesystem fallback" mode for environments without
SQLite — every Python ships SQLite.

### Static frontend, no build step

The web/ directory is three files: HTML, CSS, JS. No bundler, no npm.
**Why:** the user's IT may need to audit this for company use. A 600-line
JS file readable in a text editor passes that audit; a Webpack bundle does
not. **How to apply:** Don't add React, Vue, Svelte, or a bundler — even
if the UI needs to grow. If complexity demands it, keep the bundler optional
and ship a pre-built `web/dist` in the repo.

## Security / privacy

### Sandboxed file serving

`/api/files` only serves paths under registered project roots. **Why:** the
browser can't be allowed to ask the local server for arbitrary files just
because the server has filesystem permissions. **How to apply:** if you add
new "show me a file" endpoints, they must validate against the registry.

### Localhost binding by default

The server listens on 127.0.0.1, not 0.0.0.0. **Why:** opening a TCP port
on a corporate machine may need IT approval; loopback doesn't. **How to
apply:** if a future feature needs LAN access, add explicit `--host 0.0.0.0`
opt-in plus token auth in the same commit. Never silently widen the bind.
