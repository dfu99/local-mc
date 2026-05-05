"""Audit figure generator — 2026-05-05.

Produces figures/audit-2026-05-05.png. Four-panel layout:
    1. Done-vs-claimed: what the planning doc says vs. what shipped.
    2. LOC + module risk: bar of file sizes coloured by hand-assessed risk.
    3. Milestone burn-down: v0.1 / v0.2 / v0.3 / v0.4 with completion %.
    4. Blocker map: smoke-test results matrix.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures" / "audit-2026-05-05.png"

# ── Panel 1: Done-vs-claimed ────────────────────────────────────────────
claims = [
    ("Scaffold layout",            1.0, 1.0),
    ("Python pkg modules",         1.0, 1.0),
    ("Static frontend",            1.0, 1.0),
    ("CLI entrypoint",             1.0, 1.0),
    ("Smoke test passing",         0.0, 0.95),  # planning underclaimed
    ("Tests written",              0.10, 0.0),
    ("CI configured",              0.10, 0.0),
    ("Real claude verified",       0.0, 0.0),
    ("Objectives logged",          1.0, 0.0),
    ("Figures generated",          1.0, 0.0),
    ("PyPI published",             0.0, 0.0),
    ("Windows verified",           0.0, 0.0),
]
labels = [c[0] for c in claims]
claimed = np.array([c[1] for c in claims])
shipped = np.array([c[2] for c in claims])

# ── Panel 2: LOC by module (audit risk colour) ──────────────────────────
modules = [
    ("lmc/sessions.py", 276, "high"),     # unverified flags
    ("lmc/server.py",   462, "low"),      # smoke-tested
    ("lmc/store.py",    291, "med"),      # streaming append untested
    ("lmc/cli.py",      204, "low"),
    ("lmc/projects.py", 119, "low"),
    ("lmc/config.py",   114, "low"),
    ("lmc/artifacts.py",103, "med"),      # globs not plumbed from settings
    ("web/app.js",      517, "med"),      # no auto-reconnect, untested
    ("web/style.css",   474, "low"),
    ("web/index.html",   75, "low"),
]
risk_colour = {"high": "#d23f3f", "med": "#e0a020", "low": "#3c8a3a"}

# ── Panel 3: Milestone progress ─────────────────────────────────────────
milestones = [
    ("v0.1 chat UI",            0.85),  # runs end-to-end on echo, missing tests + claude verify
    ("v0.2.0 status panel",     0.0),
    ("v0.2.1 send/batch/steer", 0.0),
    ("v0.2.2 AFK queue",        0.0),
    ("v0.2.3 reports",          0.0),
    ("v0.2.4 objectives",       0.0),
    ("v0.3.0 PyPI",             0.0),
    ("v0.3.1 install.sh",       0.0),
    ("v0.4 integrations",       0.0),
]

# ── Panel 4: Smoke-test matrix ──────────────────────────────────────────
checks = [
    ("`lmc init`",                            "pass"),
    ("`lmc add` / `list`",                    "pass"),
    ("`lmc serve` (uvicorn binds)",           "pass"),
    ("`GET /api/projects`",                   "pass"),
    ("`POST /sessions`",                      "pass"),
    ("`POST /upload` → inbox/<sid>/",         "pass"),
    ("`/api/files` 200 in-project",           "pass"),
    ("`/api/files` 403 outside (rel path)",   "pass"),
    ("`/api/files` 403 outside (symlink)",    "pass"),
    ("WS chat stream (EchoAgent)",            "pass"),
    ("Artifact diff on done",                 "untested"),
    ("`pip wheel` builds + bundles web/",     "pass"),
    ("`ClaudeAgent` real `claude -p`",        "untested"),
    ("Windows install path",                  "untested"),
    ("pytest test suite",                     "absent"),
]
status_colour = {"pass": "#3c8a3a", "untested": "#e0a020", "absent": "#d23f3f"}

# ── Plot ────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(15, 11), constrained_layout=True)
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1])
fig.suptitle(
    "local-mc — Audit 2026-05-05\nscaffold + smoke-test result · "
    "single operator · 24h sprint window",
    fontsize=14, fontweight="bold",
)

# Panel 1
ax1 = fig.add_subplot(gs[0, 0])
y = np.arange(len(labels))
ax1.barh(y - 0.18, claimed, height=0.36, color="#888", alpha=0.6, label="claimed in planning")
ax1.barh(y + 0.18, shipped, height=0.36, color="#1f4d8a", label="actually shipped")
ax1.set_yticks(y)
ax1.set_yticklabels(labels, fontsize=9)
ax1.invert_yaxis()
ax1.set_xlim(0, 1.1)
ax1.set_xlabel("completion (0 = none, 1 = done)")
ax1.set_title("Panel 1 · Done-vs-claimed", fontsize=11, fontweight="bold")
ax1.legend(loc="lower right", fontsize=8)
ax1.grid(axis="x", alpha=0.3)
for i, (c, s) in enumerate(zip(claimed, shipped)):
    if abs(c - s) > 0.3:
        ax1.annotate("Δ", (max(c, s) + 0.02, i), fontsize=10, color="#d23f3f", fontweight="bold")

# Panel 2
ax2 = fig.add_subplot(gs[0, 1])
mlabels = [m[0] for m in modules]
mloc = [m[1] for m in modules]
mcols = [risk_colour[m[2]] for m in modules]
ax2.barh(np.arange(len(mlabels)), mloc, color=mcols)
ax2.set_yticks(np.arange(len(mlabels)))
ax2.set_yticklabels(mlabels, fontsize=9)
ax2.invert_yaxis()
ax2.set_xlabel("lines of code")
ax2.set_title("Panel 2 · LOC by module (colour = audit risk)", fontsize=11, fontweight="bold")
ax2.grid(axis="x", alpha=0.3)
handles = [mpatches.Patch(color=risk_colour[k], label=k) for k in ("high", "med", "low")]
ax2.legend(handles=handles, loc="lower right", fontsize=8, title="risk")
for i, l in enumerate(mloc):
    ax2.text(l + 8, i, str(l), va="center", fontsize=8)

# Panel 3
ax3 = fig.add_subplot(gs[1, 0])
mn = [m[0] for m in milestones]
mp = [m[1] for m in milestones]
colors = ["#3c8a3a" if p > 0.6 else "#e0a020" if p > 0 else "#bbbbbb" for p in mp]
ax3.barh(np.arange(len(mn)), mp, color=colors)
ax3.set_yticks(np.arange(len(mn)))
ax3.set_yticklabels(mn, fontsize=9)
ax3.invert_yaxis()
ax3.set_xlim(0, 1.05)
ax3.set_xlabel("estimated completion")
ax3.set_title("Panel 3 · Milestone burn-down", fontsize=11, fontweight="bold")
ax3.grid(axis="x", alpha=0.3)
for i, p in enumerate(mp):
    ax3.text(p + 0.01, i, f"{int(p*100)}%", va="center", fontsize=8)

# Panel 4
ax4 = fig.add_subplot(gs[1, 1])
ax4.axis("off")
ax4.set_title("Panel 4 · Smoke-test matrix (executed 2026-05-05)",
              fontsize=11, fontweight="bold", loc="left")
table_y = 0.95
for i, (label, status) in enumerate(checks):
    y_pos = table_y - i * 0.06
    ax4.add_patch(mpatches.Rectangle((0.0, y_pos - 0.025), 0.05, 0.04,
                                     color=status_colour[status]))
    ax4.text(0.07, y_pos, label, fontsize=9, va="center", family="monospace")
    ax4.text(0.85, y_pos, status, fontsize=9, va="center",
             color=status_colour[status], fontweight="bold")
ax4.set_xlim(0, 1)
ax4.set_ylim(0, 1)

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"wrote {OUT}")
