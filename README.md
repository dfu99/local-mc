# local-mc

> A local-first reimplementation of Mission Control (`mc`) with a chat-style
> web UI in place of Slack. Designed for environments where company data
> cannot leave the machine (no Slack, no third-party services).

**Status:** planning + scaffold. Not runnable yet. See [`tasks/planning.md`](tasks/planning.md)
for the full roadmap and [`docs/v0.1-scaffold.md`](docs/v0.1-scaffold.md) for what's
already on disk.

## Why this exists

The author runs a multi-project [Mission Control system](docs/comparison-with-existing-mc.md)
(`mc launch`, `mc send`, `mc afk`, `mc status`, ...) that drives many Claude Code
sessions in tmux and uses Slack as the human interface — viewing artifacts,
sending directives, sharing files.

That stack is great at home. At work, it can't be used:

- **Slack is not approved for sensitive company data.** Any directive, any
  attached PDF, any plot would route through Slack's servers. That's a
  non-starter for confidential codebases.
- **Raw terminal is not enough.** Reviewing an experiment plot, scrubbing a
  PDF, or scrolling a long markdown report is awkward in a tmux pane.

`local-mc` is the answer: same Mission Control workflow, but every byte stays
on the machine. The browser is the UI; SQLite holds chat history; uploads
live in the project tree; the only outbound network is whatever the Claude
Code CLI itself does (which the company's existing API approval already
covers).

## Design at a glance

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (localhost:8765)        ◀── chat UI, media viewer  │
│   ▲                                                          │
│   │ WebSocket + REST                                         │
│   ▼                                                          │
│  FastAPI server (lmc.server)                                 │
│   ├── projects.yaml      (registry — like projects.conf)     │
│   ├── lmc.db (SQLite)    (chat history per session)          │
│   └── per-turn `claude`  (subprocess, stream-json output)    │
│                                                              │
│  Project tree (no changes)                                   │
│   ├── inbox/<session>/   (uploaded attachments land here)    │
│   ├── figures/, results/ (artifact glob — auto-detected)     │
│   └── tasks/             (mc-style task files, untouched)    │
└─────────────────────────────────────────────────────────────┘
```

No tmux. No Slack. No daemons (other than the FastAPI server you run
yourself). No external services.

## Migration plan (this is the point)

This repo is meant to be cloned onto a different machine and brought up there
with that machine's projects. The flow:

```bash
# On the target machine
git clone git@github.com:dfu99/local-mc.git
cd local-mc
pipx install .                           # or: pip install -e .
lmc init                                  # creates ~/.config/lmc, ~/.local/share/lmc
lmc add backend  /work/backend            # register projects
lmc add data     /work/data-pipeline
lmc serve                                 # opens http://127.0.0.1:8765
```

Nothing in this repo references the author's local paths or projects. All
machine-specific state lives under `$XDG_CONFIG_HOME/lmc` and
`$XDG_DATA_HOME/lmc`, never inside the repo.

See [`docs/migration.md`](docs/migration.md) for the full migration checklist
including: what to copy, what to recreate, IT-approval talking points, and how
to verify nothing leaks outside the machine.

## What's in the repo today

- `lmc/` — Python package skeleton: config, projects, store, sessions,
  artifacts, server, CLI. **Scaffold-stage; not yet tested end-to-end.**
- `web/` — vanilla HTML/CSS/JS chat UI. Renders images, video, PDF, markdown.
  No CDN deps.
- `bin/lmc` — wrapper script for running without `pip install`.
- `tests/` — empty (intentionally — see planning).
- `docs/` — architecture, migration, comparison with existing `mc`.
- `tasks/` — planning, lessons.

## What's NOT in the repo yet

The chat interface is the v0.1 target. The full `mc` feature surface
(project status dashboard, AFK queue, batch send, session scheduler, head
scientist, morning report, ...) is planned but not started. See the
roadmap in [`tasks/planning.md`](tasks/planning.md).

## License

MIT (see [`LICENSE`](LICENSE)).
