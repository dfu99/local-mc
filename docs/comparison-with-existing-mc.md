# Comparison: local-mc vs the original Mission Control

## TL;DR

`~/Documents/code/development` (the original) is a **bash + tmux + Slack**
stack tuned for an open-source / personal workflow. local-mc is a
**Python + browser** rewrite tuned for a workflow where Slack is off the
table because of company-data-sensitivity rules.

The user-facing concepts (projects, sessions, attachments, artifacts,
directives, AFK queue, status dashboard) are the same. The plumbing is
different.

## Side-by-side

| Concept              | original `mc`                          | local-mc                                |
|----------------------|----------------------------------------|-----------------------------------------|
| Process manager      | tmux session `swarm`, one window/proj  | Per-turn `claude` subprocess            |
| Project registry     | `projects.conf` (pipe-delimited)       | `projects.yaml`                         |
| Human interface      | Slack channels + tmux dashboard        | Browser at http://127.0.0.1:8765        |
| Attachments          | Slack file uploads → `inbox/`          | Drag-drop in chat → `<proj>/inbox/<sid>/` |
| Artifacts            | Slack-uploaded plots / `mc qa`         | Inline preview in chat                  |
| Status dashboard     | tmux `dashboard` window + watch        | _v0.2 — not built yet_                  |
| Send / batch / steer | `mc send`, `mc batch`, `mc steer`      | _CLI v0.2; chat input works in v0.1_    |
| AFK / autochain      | `mc afk`, `tasks/queue.yaml`, hooks    | _v0.2 — planned_                        |
| Reports              | `mc report`, `mc changelog`            | _v0.2 — planned_                        |
| Cluster integration  | `mc sync / submit / fetch` (PACE)      | _v0.4 — generic SLURM, optional_        |
| Chat history         | tmux pane logs in `logs/<proj>.log`    | SQLite at `~/.local/share/lmc/lmc.db`   |
| Frontend stack       | bash + tmux ANSI                       | HTML + CSS + ES module (no bundler)     |
| External services    | Slack, Anthropic API                   | Anthropic API only                      |
| Daemon footprint     | tmux + ~6 systemd timers (overseer,    | One FastAPI process, started manually   |
|                      | proactive, etc.)                       |                                         |
| Auth assumption      | personal laptop, single user           | personal/work laptop, single user       |
| IT-audit surface     | Many bash scripts + Slack OAuth        | One Python pkg + 3 static files         |

## Why the differences

### Why drop Slack

The whole reason local-mc exists. Two angles:

- **Confidentiality.** Code, plots, and prompts at the day job may not
  leave the machine. Slack routes all of that through their cloud, even
  if the workspace is private.
- **Friction at work.** A second Slack workspace just for personal mc
  feels like the wrong tool for a work device.

### Why drop tmux

Tmux is great for personal use but a pain in three ways for this rewrite:

- **State in tmux is opaque.** No structured chat history, just pane
  output. Hard to back up, harder to query.
- **Pane scraping is brittle.** ANSI escapes, resize events, terminal
  emulation all conspire against you.
- **It's hard to render media.** A plot in tmux is "open this PNG path
  in a viewer" — that's the gap the Slack frontend filled. Once Slack
  goes, the browser is the obvious replacement.

### Why drop systemd timers (for now)

The original mc has timers for the overseer, the proactive Slack monitor,
runpod watchdog, head scientist, etc. local-mc starts with **none**.
Reasons:

- v0.1 is a chat UI. No background daemons needed for that.
- Each new daemon is another IT-review checkbox.
- v0.2 will revisit on a per-feature basis: AFK autochain probably wants
  a worker, the morning report can be on-demand instead of cron.

### Why drop bash for Python

Two-line answer: the original was bash because that's what scripts-glued-
to-tmux-glued-to-Slack-CLI naturally fit. This rewrite has no shell-glue
needs — it's one process serving HTTP. Python is the lower-friction choice
for everything else (FastAPI, SQLite stdlib, async I/O, type hints).

## What local-mc keeps from the original

- **The project-registry-as-source-of-truth pattern.** One file
  (`projects.yaml`) lists every project and its path. Everything else
  consumes that file.
- **Inbox-per-project for attachments.** Same convention as `mc`'s
  `inbox/<project>/<session>/`. Plays nicely with the Slack flow if the
  user ever runs both side-by-side.
- **`tasks/`-driven planning.** The user's global CLAUDE.md mandates
  `tasks/planning.md`, `tasks/lessons.md`, `tasks/objectives.yaml`. We
  keep that convention.
- **AFK queue + autochain (planned).** The single best feature of the
  original; v0.2 will reproduce it.
- **Project tags.** Same `research`, `product`, `admin`, `archived`
  vocabulary, expressed as YAML lists.

## When to use which

| Situation                                      | Tool             |
|------------------------------------------------|------------------|
| Personal projects on the home laptop, Slack OK | original `mc`    |
| Day job, sensitive data, no Slack              | local-mc         |
| Both at once on the same machine               | _v0.4 bridge_    |
| You want media-rich chat with a single project | local-mc         |
| You want the full cron / daemon / AFK stack    | original `mc` (v0.2 to add) |
| You want IT to review the codebase             | local-mc         |

## Migration path between them

If you outgrow one and want to move:

- **mc → local-mc:** copy `projects.conf` entries into `projects.yaml`
  (planned `lmc bridge import` command in v0.4). Chat history doesn't
  migrate — Slack history stays in Slack.
- **local-mc → mc:** opposite direction. Same constraint.

For now both stacks are independent. They share the project tree
convention (`inbox/`, `tasks/`, `figures/`, `results/`) so the *project
content* moves between them at zero cost; only the orchestration layer
is per-tool.
