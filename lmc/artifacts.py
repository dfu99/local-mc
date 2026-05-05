"""Artifact discovery — find files the agent created or modified during a turn.

Strategy: snapshot a project's matching files before the turn, run the turn,
then diff the snapshot. Anything new or modified is reported as an artifact
the UI should preview (image, PDF, CSV, etc.).

We deliberately do NOT use a long-running file watcher. Snapshots are O(n)
in the file count and cheap; a watcher introduces lifecycle complexity (start,
stop, missed events on heavy fs activity) that isn't worth it for the small
number of files a typical turn touches.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GLOBS = [
    "figures/**/*",
    "results/**/*",
    "plots/**/*",
    "outputs/**/*",
    "*.png",
    "*.svg",
    "*.pdf",
    "*.html",
]


@dataclass
class Artifact:
    path: str  # absolute
    rel_path: str  # relative to project root
    mime: str
    size: int
    mtime: float

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "rel_path": self.rel_path,
            "mime": self.mime,
            "size": self.size,
            "mtime": self.mtime,
        }


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def snapshot(project_root: str, globs: list[str] | None = None) -> dict[str, float]:
    """Map of absolute path → mtime for every file matching any glob."""
    root = Path(project_root)
    globs = globs or DEFAULT_GLOBS
    out: dict[str, float] = {}
    for pattern in globs:
        for p in root.glob(pattern):
            if p.is_file():
                try:
                    out[str(p.resolve())] = p.stat().st_mtime
                except OSError:
                    continue
    return out


def diff(
    project_root: str,
    before: dict[str, float],
    after: dict[str, float] | None = None,
    globs: list[str] | None = None,
    max_results: int = 50,
) -> list[Artifact]:
    """Files added or modified between snapshots."""
    if after is None:
        after = snapshot(project_root, globs)
    root = Path(project_root)
    changed: list[Artifact] = []
    for p, mtime in after.items():
        prev = before.get(p)
        if prev is None or mtime > prev + 1e-6:
            try:
                size = Path(p).stat().st_size
            except OSError:
                continue
            try:
                rel = str(Path(p).relative_to(root.resolve()))
            except ValueError:
                rel = p
            changed.append(
                Artifact(
                    path=p,
                    rel_path=rel,
                    mime=_guess_mime(Path(p)),
                    size=size,
                    mtime=mtime,
                )
            )
    # Newest first
    changed.sort(key=lambda a: a.mtime, reverse=True)
    return changed[:max_results]
