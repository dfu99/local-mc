# Existing tools we considered before building

The original question was: "Is there OEM-esque software that already does
this?" Answer: there are several Claude Code wrappers, but none fit the
specific *Mission-Control-without-Slack* shape. This file records what we
looked at and why we still went custom.

| Project                 | What it is                                              | Why it doesn't replace what we want         |
|-------------------------|---------------------------------------------------------|----------------------------------------------|
| **AI Hub** (Vue + Go)   | Self-hosted multi-session Claude Code wrapper           | Closest match. No Mission Control concepts (project registry as first-class, AFK queue, status dashboard, mc workflow). Heavier stack (Vue + Go) means more to vet for IT. |
| **Claude Code Viewer** (d-kimuson) | Web client with image/PDF/text upload preview     | Single-session focused. Doesn't model multiple projects in a sidebar.                                                          |
| **CloudCLI / claudecodeui** (siteboon) | Web/mobile UI for managing Claude Code remotely  | Designed for *remote* control of a development machine. We want local-only.                                                    |
| **Claudito** (comfortablynumb) | Multi-project Claude agent manager with Mermaid, Ralph Loop | Closer to Mission Control conceptually, but ships features we don't need (Ralph Loop, MCP setup UI) and lacks the AFK-queue + status-dashboard pattern. |
| **Claude Code Channels** (Anthropic, Mar 2026) | Telegram/Discord plugin to a local CC session     | Solves the "remote chat into local Claude" problem with a *messaging service* in the loop, which is exactly what we're avoiding for confidentiality reasons. |
| **Claude Code Desktop app** | Anthropic-shipped desktop app                       | Single-project. No mc-style multi-project orchestration.                                                                       |

## Decision

Build custom. The "Mission Control" surface (project registry, multi-session
sidebar, AFK queue, status dashboard, attachment inbox per project, the
specific `mc <verb>` vocabulary the user has internalized) is the value we
need to preserve from the original `~/Documents/code/development`. None of
the off-the-shelf wrappers replicate that surface, and bolting it onto one
of them would be more work than starting clean.

## What we copied conceptually

- **AI Hub's** "persistent subprocess pool" idea is on the table for v0.2
  if per-turn spawn latency turns out to matter. v0.1 deliberately starts
  per-turn-only.
- **Claude Code Viewer's** approach of dedicated preview components per
  MIME type (image, PDF, text) is what `web/app.js`'s `renderArtifact`
  function does.
- **The `--output-format stream-json` protocol** is the standard way to
  parse Claude Code output programmatically — every wrapper above uses it
  and so do we.

## What we deliberately did *not* copy

- **MCP-server-management UI.** Out of scope for v0.1. The user manages
  MCP via Claude Code's own config; local-mc doesn't expose it.
- **Cloud sync.** Some wrappers (CloudCLI) explicitly support tunneling.
  We don't.
- **OpenAI-format API endpoint** (AI Hub exposes one). Not needed for our
  workflow; would expand the audit surface.
