# local-mc — Planning

This file is the source of truth for "what to do next" when resuming work on
local-mc, especially on a fresh machine where the original development stack
is not available.

## Vision

`local-mc` is a **reimplementation of `~/Documents/code/development` (Mission
Control)** with one fundamental change: the human interface is a local web
UI instead of Slack. Every workflow that currently routes through
Slack — directives, file uploads, artifact viewing, status checks, AFK
planning — must work entirely on the user's machine, with no third-party
service in the loop.

The motivation is **company-confidentiality**. The original Mission Control
sends project filenames, code snippets, plots, and prompts through Slack.
Slack may not be approved for the data classes the user works with at their
day job. local-mc is for those environments.

## Scope clarification (resolved 2026-05-05)

After back-and-forth in the kickoff session, the agreed scope is:

> **Full reimplementation of `mc`, not just a chat skin.**
> The chat web UI replaces Slack as the human surface. Everything else
> (project registry, session management, AFK queue, status, scheduling,
> batch send, reporting) is either reimplemented locally or explicitly
> deferred. **No tmux dependency** — sessions are managed in-process.

Bundling: should be installable as a single command (`pipx install .` from
the cloned repo, eventually `pipx install local-mc` from PyPI). Distribution
is the cloned repo + an installer, not a pre-built binary.

## v0.1 — Chat interface (smoke-tested green; tests starting)

The minimum thing that makes the product useful: open a browser, see a list
of projects, talk to one, drop in a PDF, watch a plot it generates render
inline.

### Done (verified 2026-05-05)

- Directory layout, `pyproject.toml`, `requirements.txt`, `.gitignore`.
- `lmc/config.py` — XDG config/state paths; `Settings` dataclass.
- `lmc/projects.py` — YAML registry: add / remove / update / list.
- `lmc/store.py` — SQLite schema for sessions / messages / attachments;
  helpers for streaming append.
- `lmc/sessions.py` — `ClaudeAgent` (wraps `claude -p --output-format stream-json
  --input-format stream-json --resume`) and `EchoAgent` (for tests).
- `lmc/artifacts.py` — snapshot/diff a project's file tree to surface
  newly-created plots or PDFs as artifacts.
- `lmc/server.py` — FastAPI REST + WebSocket. Localhost-only CORS.
  `/api/files` is sandboxed to registered project roots.
- `lmc/cli.py`, `bin/lmc` — `lmc init / serve / add / rm / list / settings`.
- `web/index.html`, `web/style.css`, `web/app.js` — single-page UI:
  project sidebar, chat panel, attachment tray, drag-drop, inline image /
  video / PDF rendering, markdown rendering for messages.
- **Smoke test passes end-to-end with `agent: echo`.** REST + WS chat work;
  uploads land in `<proj>/inbox/<sid>/`; `/api/files` returns 200 in-project,
  403 on `/etc/passwd`, 403 on `/proj/../../etc/passwd`, and 403 on a symlink
  pointing outside. `python -m build --wheel` succeeds and bundles `web/`.
  See `tasks/audit-2026-05-05.md` for the matrix.
- **`tests/test_projects.py` (10 tests) + `tests/test_store.py` (13 tests)
  green** — Registry CRUD, duplicate detection, missing-path rejection,
  session round-trips, cascade-delete, 100-delta streaming append.

### Not done (P0/P1 from audit 2026-05-05)

- **(P0) Real `claude` turn never run.** The `--input-format stream-json`
  flag combination is still unverified against the installed binary.
  Audit-blocker; see `tasks/queue.yaml#q04`.
- **(P0) Windows install path untested.** Deploy target is a Windows work
  machine; nothing in the smoke test ran on Windows.
  See `tasks/queue.yaml#q05` and `q08`.
- **(P1) No FastAPI route tests / WS tests.** `q02`, `q03` in queue.
- **(P1) `bin/lmc` is POSIX-only.** Need a `lmc.cmd` shim. `q08`.
- **(P2) No first-run wizard.** Adding a project requires either the CLI
  or the `+` button in the sidebar; no guided setup.
- **(P2) Auth.** Server binds 127.0.0.1 only. If user wants LAN access
  (corporate laptop on Wi-Fi), there's no token auth. Decision deferred.
- **(P3) No daemon / autostart.** Manual launch only.
- **(audit drop-list) `watchfiles` dep is dead** (never imported); the
  `package-data = lmc = ["../web/**/*"]` pattern works but is sketchy on
  Windows; `Settings.artifact_globs` is set but never plumbed through to
  the server's `snapshot()` call. See `q06`, `q07`.

### How to verify v0.1 (when you resume)

```bash
cd local-mc
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# 1. Smoke-test imports
python -c "from lmc import server; print('ok')"

# 2. Echo-agent server (no claude binary needed)
LMC_HOME=/tmp/lmc-test lmc init
echo 'agent: echo' >> /tmp/lmc-test/config/settings.yaml
mkdir -p /tmp/demo-proj
LMC_HOME=/tmp/lmc-test lmc add demo /tmp/demo-proj
LMC_HOME=/tmp/lmc-test lmc serve --port 8765 --no-open

# 3. In a browser: http://127.0.0.1:8765
#    - sidebar shows "demo"
#    - clicking it opens a session
#    - typing a message echoes back
#    - drag an image in → it stages, sends, renders
#    - check /tmp/demo-proj/inbox/<sid>/ has the upload

# 4. Real claude: change settings.yaml `agent: claude`, restart, retry.
```

If any of those steps fail, fix that step before adding new features.

## v0.2 — Reimplement core mc commands

Once v0.1 is a working chat. The order below reflects the user's actual
workflow priority on the original `mc`.

### v0.2.0 — Project status panel

A second "tab" in the UI (or a top bar) showing all projects: which sessions
are active, last activity time, latest artifact, any flagged errors. Mirrors
`mc status` and the dashboard tmux window.

Design questions:
- Live-updating via Server-Sent Events or polling?
- Where does "needs attention" come from? (mc has heuristics in
  `swarm.sh status` — look-back + idle threshold + error-counter files.)

### v0.2.1 — Send / batch / steer

- "Send" already exists implicitly (the chat input). Add a `lmc send <proj>
  "msg"` CLI command that POSTs into the active session — for scripting
  parity with `mc send`.
- "Batch": send one prompt to every project. Web UI: a "broadcast" composer
  on a global view. CLI: `lmc batch "msg"`.
- "Steer": same as the original — append to `tasks/directives.md` AND inject
  the directive into the live session.

### v0.2.2 — AFK queue + autochain

The most valuable mc feature. Reproduces `mc afk <project> "goal"`:
1. The agent reads the goal, decomposes into 5–20 tasks, writes them to
   `tasks/queue.yaml`.
2. The autochain loop pulls items off the queue and feeds them as new turns.
3. Self-refill policy when the queue empties (up to N refills).
4. UI exposes the queue: each project has a "queue" panel showing pending /
   in-progress / completed.

Reference: `~/Documents/code/development/bin/afk-planner.sh`,
`autochain-hook.sh`, `queue.sh`, `tasks/afk-policy.yaml`.

### v0.2.3 — Morning report / changelog

`mc report` and `mc changelog` — generate an HTML or markdown digest of what
each project did in a window of time. Render in-browser at `/report/today`.

Reference: `bin/morning-report.py`, `bin/daily-changelog.py`.

### v0.2.4 — Per-project objectives + visualizations

The `tasks/objectives.yaml` + figure-QA pipeline from the global CLAUDE.md.
Surface the latest objective at the top of each project's chat header, with
its figure as an inline preview.

Reference: `bin/figure-qa.py`, the `visualize` skill.

## v0.3 — Bundling and distribution

### v0.3.0 — pipx-installable from PyPI

Publish `local-mc` to PyPI so a fresh machine can do `pipx install local-mc`
and then `lmc serve`. Requires:
- Decide on a final package name (collision check: `local-mc` may be taken).
- Set up GitHub Actions to build wheels and publish on tag.
- Vendor the `web/` assets into the wheel (already pointed at via
  `pyproject.toml`'s `package-data`, but verify it actually lands).

### v0.3.1 — One-shot install script

For environments where pipx isn't around (locked-down corporate laptops with
only system Python). A `scripts/install.sh` that:
- Creates a venv under `~/.local/lmc-venv`.
- Installs the package into it.
- Drops a `~/.local/bin/lmc` shim.
- Prints the next step (`lmc init && lmc add <name> <path>`).

### v0.3.2 — Standalone binary (probably skip)

PyInstaller / Nuitka. Likely not worth the build complexity. Document why
not and revisit only if a use case demands it (e.g. air-gapped install).

## v0.4 — Optional integrations

### v0.4.0 — Compatibility shim with original `mc`

For users running both at once: a `lmc bridge` that reads `projects.conf`
from a sibling Mission Control checkout and mirrors its registry into
`projects.yaml`. One source of truth, two UIs.

### v0.4.1 — PACE / SLURM remote integration

The original mc has `mc sync / mc submit / mc fetch` for the GT PACE cluster.
At work the user may have an analogous internal cluster. Punt on naming, but
the design pattern (rsync up, submit script, poll, rsync results back) is
generic.

## Architecture decisions (locked)

- **No tmux.** Each user message spawns a fresh `claude -p` subprocess
  resumed against the saved session id. Pros: no zombie processes, no
  state-in-tmux to lose, easier to test. Con: slightly slower per turn.
  Mitigated by Claude Code's prompt caching + `--resume`.
- **SQLite.** Chat history is a single file. Easy to back up, copy to another
  machine, or wipe.
- **Static frontend.** No bundler, no npm. The whole UI is three files. Easy
  to audit for IT review.
- **Localhost-only by default.** No IT exception needed for opening a port.
- **EchoAgent for tests.** Avoids the real Claude API in CI / on machines
  without the binary.

## Open questions / decisions needed

- **Auth for non-localhost access.** If the user wants to attach from a
  phone on the same LAN, do we add token auth? Or stay strictly localhost
  and require SSH-tunnel for remote access? Current default: strictly
  localhost. Revisit when a real need arises.
- **MCP servers.** The original mc relies on Claude Code's MCP setup for
  some skills. Should `lmc serve` ship a curated set of MCP servers?
  Probably yes for: filesystem, git. Probably no for: Slack, Gmail, anything
  cloud-touching.
- **Multi-user.** v0.1 assumes one operator on one machine. Don't scope
  multi-user until a stakeholder asks.
- **Telemetry.** None for now. Don't add any without explicit consent —
  the whole point of this project is "stays on the machine."

## Resume checklist (for the next session)

When you sit down on the new machine and want to continue:

1. `git clone git@github.com:dfu99/local-mc.git && cd local-mc`
2. Read this file (`tasks/planning.md`) end-to-end.
3. Read `docs/architecture.md` for the design rationale.
4. Read `docs/v0.1-scaffold.md` for what's literally on disk and what's
   not yet wired up.
5. Run the v0.1 verification steps above. Do not start v0.2 work until
   v0.1 is green end-to-end.
6. Check `tasks/lessons.md` before touching any subsystem covered there.

## Recently completed

- 2026-05-05 01:50 — q06: dropped `watchfiles` dep (was unused) and
  threaded `Settings.artifact_globs` through both `snapshot()` and
  `diff()` in `lmc/server.py`. New test pins it: set globs to
  `['figures/*.png']`, plant a `.png` and a `.csv`, only the `.png`
  surfaces in the `done` event. Suite: 55 passing.
- 2026-05-05 01:46 — q05: `.github/workflows/test.yml` written —
  3×3 matrix (ubuntu+windows+macos × py3.10/3.11/3.12) plus a
  `build-wheel` job that grep-asserts `web/{index.html,app.js,style.css}`
  in the wheel. Real-`claude` test cleanly skips in CI.
- 2026-05-05 01:42 — q04: tests/test_claude_agent.py (3 tests) green
  against real `claude` v2.1.128 on Linux. **The audit's P0 blocker is
  partially resolved:** flag combo `-p --output-format stream-json
  --input-format stream-json --verbose` works as written; `_parse_event`
  decodes `text + session_id + done` correctly. Windows verification
  still pending (the same test will execute there once on the target).
  Total: 54 tests passing in 15.16s.
- 2026-05-05 01:38 — q03: tests/test_chat_ws.py (7 tests) green;
  WebSocket protocol order (`user_message → assistant_start → delta+ →
  done`), attachments persisted, delta-concat matches store content,
  artifact-diff picks up files written between assistant_start and done,
  ping/pong, error on bad message type. Total: 51 tests passing.
- 2026-05-05 01:35 — q02: tests/test_server.py (21 tests) green;
  REST + /api/files sandbox (200/403/404 cases incl. symlink-pointing-out,
  POSIX-only) + upload happy/413 cap + safe-filename strip. Total
  pytest suite: 44 passing in 2.84s.
- 2026-05-05 01:30 — q01: tests/test_projects.py (10) + tests/test_store.py
  (13) green; covers Registry CRUD + Store streaming append (100-delta).
- 2026-05-05 01:22 — Audit (`tasks/audit-2026-05-05.md`,
  `figures/audit-2026-05-05.png`); seeded `tasks/queue.yaml` (q01–q13);
  logged obj-001 in `tasks/objectives.yaml`. Headline finding: v0.1 is
  *runnable*, not the "scaffold-only / not runnable" the prior version of
  this file claimed. Single biggest blocker is verified `claude` turn on
  Windows.
- 2026-05-05 — Initial scaffold + planning.
