# Migration — bringing local-mc up on a new machine

This is the playbook for taking the repo onto your work machine (or any
fresh environment) and getting it productive. Written for a future-you who
hasn't seen the code in weeks.

## What you're moving

- **The code.** Clone-only; no machine-specific data is in the repo.
- **Per-project chat history.** Optionally — the SQLite file at
  `~/.local/share/lmc/lmc.db` on the source machine. Most users will start
  fresh on the new machine; copy the DB only if you have a specific
  conversation you want to preserve.
- **Project registry.** `~/.config/lmc/projects.yaml`. You will likely
  rewrite this from scratch on the new machine — the projects there are
  different.

## What you're *not* moving

- The Claude Code installation itself — install separately on the new
  machine via the standard process (`npm i -g @anthropic-ai/claude-code`
  or whatever the current install method is).
- API keys / Claude auth — handled by Claude Code's own flow.
- Anything from the original `~/Documents/code/development` Mission
  Control. local-mc is a clean slate; it doesn't read that repo.

## On the source machine

If you want to carry chat history forward (skip if starting fresh):

```bash
# Snapshot config + data
tar czf lmc-backup-$(date +%F).tgz \
    -C ~ .config/lmc .local/share/lmc

# Move the tarball however you normally move files at work
# (scp, encrypted USB, sanctioned file-transfer service)
```

## On the target machine — first run

### Prereqs

- Python 3.10+
- `pipx` (or `pip` + a venv) — confirm with IT this is OK if you're on
  a managed corporate laptop
- Claude Code CLI installed and authenticated (`claude --version` should
  work)
- Git

### Install

```bash
git clone git@github.com:dfu99/local-mc.git
cd local-mc

# Option A: pipx (preferred — isolated, single command for upgrades)
pipx install .

# Option B: pip + venv (when pipx isn't available)
python3 -m venv ~/.local/lmc-venv
source ~/.local/lmc-venv/bin/activate
pip install -e .

# Option C: no install at all — run from the checkout
./bin/lmc --help
```

### Configure

```bash
# Create config + state dirs with defaults
lmc init

# Register your projects (paths must exist)
lmc add backend  /work/backend
lmc add data     /work/data-pipeline
lmc add scratch  ~/scratch
lmc list
```

If you want to restore a backup from the source machine:

```bash
tar xzf lmc-backup-2026-05-05.tgz -C ~
lmc list                    # confirms it picked up the old projects
```

### Run

```bash
lmc serve
# → opens http://127.0.0.1:8765 in your default browser
```

That's the install complete. From here, the browser is the working
surface — pick a project from the sidebar, type a message, attach files
via drag-drop or the paperclip button.

## Verification (do this before relying on it)

The scaffold has not been end-to-end tested. Run through this on the new
machine before treating it as working:

```bash
# 1. Imports resolve
python -c "from lmc.server import create_app; print('imports ok')"

# 2. Echo agent path works (no Claude API hit)
LMC_HOME=/tmp/lmc-test lmc init
cat >> /tmp/lmc-test/config/settings.yaml <<EOF
agent: echo
EOF
mkdir -p /tmp/demo-project
LMC_HOME=/tmp/lmc-test lmc add demo /tmp/demo-project
LMC_HOME=/tmp/lmc-test lmc serve --port 8765 --no-open &
SERVER_PID=$!
sleep 2

# 3. API responds
curl -s http://127.0.0.1:8765/api/projects | python -m json.tool

# 4. Cleanup
kill $SERVER_PID
rm -rf /tmp/lmc-test /tmp/demo-project
```

Then test in the browser:
- Drop a PNG into the chat — it should appear in the attachment tray.
- Send the message — the echo agent should reflect it back.
- Confirm the file landed under `<project>/inbox/<session-id>/`.

Once those pass, switch `agent: claude` and repeat with a real prompt
("list the files in this directory and show me their sizes"). If Claude
runs and tool calls render in the chat — v0.1 works on this machine.

## IT-approval talking points

If you need to justify this to a security review at work, the design
choices that matter:

- **Localhost-only network bind.** No inbound port is opened to the
  network. Confirmable with `ss -ltn | grep 8765`.
- **No third-party services.** No Slack, no analytics, no telemetry,
  no auto-update. Confirmable with `tcpdump` while a session runs —
  the only outbound traffic should be to Anthropic's API endpoints,
  which are already covered by your existing Claude Code approval.
- **No bundled minified JS.** The web frontend is three plain text
  files, ~600 lines total, hand-readable in a text editor.
- **Open source.** Audit the diff against the public repo at
  https://github.com/dfu99/local-mc.
- **No daemon / autostart.** Runs only when explicitly launched.
- **Project data stays in the project tree.** Uploaded attachments land
  in `<project>/inbox/`, not in a hidden global location, so backup and
  retention policies for the project tree carry over automatically.
- **SQLite chat history is local-only.** Single file at
  `~/.local/share/lmc/lmc.db`, no replication.

## Uninstall / cleanup

```bash
pipx uninstall local-mc          # or pip uninstall + delete the venv
rm -rf ~/.config/lmc ~/.local/share/lmc
# Per-project inbox/ dirs persist with the project (intentional)
```

## When something is broken

- **Server doesn't start, missing imports** → confirm Python ≥3.10,
  re-run `pipx install .`
- **Browser shows 502 / Disconnected** → check the terminal where you
  ran `lmc serve`; FastAPI logs go there.
- **Claude doesn't respond** → run `claude -p "hello"` in a terminal
  separately. If that fails, fix Claude Code first; local-mc just
  shells out to it.
- **Stream-json parse errors in logs** → Claude Code's CLI surface may
  have shifted since the scaffold was written. See
  `lmc/sessions.py:_parse_event` and adapt to whatever the current
  schema is.
- **Anything else** → `tasks/lessons.md` is where to add the lesson once
  you've fixed it.
