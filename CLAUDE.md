# CLAUDE.md — local-mc

This file provides guidance to Claude Code sessions working in this repo.

## What this is

`local-mc` is a planned reimplementation of the Mission Control system at
`~/Documents/code/development`, with two important differences:

1. **No Slack.** The human interface is a local web UI (FastAPI + browser),
   for environments where Slack-routed data is not company-approved.
2. **Bundled installer.** Designed to be cloned + `pipx install`-ed on a
   different machine.

## Status

**Scaffold only — not runnable yet.** Read `tasks/planning.md` end-to-end
before doing anything else. The most important sections:

- **v0.1 — Chat interface (scaffolded, not finished)** — what's on disk
  and what's missing.
- **How to verify v0.1** — the smoke-test sequence.
- **Architecture decisions (locked)** — non-negotiable design constraints
  (no tmux, no bundler, localhost-only, EchoAgent for tests).

## Task files

| File                                  | When to consult                                            |
|---------------------------------------|------------------------------------------------------------|
| `tasks/planning.md`                   | Always, when starting a session                            |
| `tasks/lessons.md`                    | Before modifying `lmc/sessions.py` or the WS protocol      |
| `tasks/objectives.yaml`               | When marking a task complete (per global CLAUDE.md)        |
| `docs/architecture.md`                | When designing new endpoints / data model                  |
| `docs/v0.1-scaffold.md`               | When picking up the existing code                          |
| `docs/migration.md`                   | When bringing this up on a new machine                     |
| `docs/comparison-with-existing-mc.md` | When you want context on what we kept vs. dropped          |
| `docs/oem-options.md`                 | When considering whether to swap in a third-party tool     |

## Running

The package isn't set up yet — see `tasks/planning.md` § "How to verify v0.1"
for the exact commands once dependencies are installed.

## Editing conventions

- Python ≥ 3.10. Type hints everywhere. Dataclasses over Pydantic for
  internal types; Pydantic only at HTTP boundaries.
- No new runtime dependencies without updating `pyproject.toml` and
  documenting the reason in `tasks/lessons.md`.
- Frontend: vanilla JS, no bundler, no CDN. If you find yourself wanting
  React, write down why in `tasks/lessons.md` first and decide later.
- Server: localhost-only by default. Adding `0.0.0.0` requires token auth
  in the same change.

## Slack

This repo deliberately does **not** integrate with Slack. If a future task
asks "send a message to Slack" or "post to a channel," that's a sign the
task belongs in the *original* Mission Control, not here.
