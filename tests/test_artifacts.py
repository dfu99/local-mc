"""Tests for lmc/artifacts.py — snapshot, diff, mime detection."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from lmc import artifacts as artmod
from lmc.artifacts import Artifact, diff, snapshot


@pytest.fixture
def root(tmp_path):
    return tmp_path / "project"


@pytest.fixture
def project(root):
    root.mkdir()
    return root


# ── snapshot ──────────────────────────────────────────────────────────────


def test_snapshot_empty(project):
    snap = snapshot(str(project))
    assert snap == {}


def test_snapshot_finds_png(project):
    (project / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    snap = snapshot(str(project))
    assert len(snap) == 1
    assert any("plot.png" in k for k in snap)


def test_snapshot_finds_nested(project):
    (project / "figures").mkdir()
    (project / "figures" / "result.png").write_bytes(b"PNG")
    snap = snapshot(str(project))
    assert any("result.png" in k for k in snap)


def test_snapshot_skips_non_matching(project):
    (project / "readme.txt").write_text("hello")
    snap = snapshot(str(project))
    assert snap == {}


def test_snapshot_custom_globs(project):
    (project / "data.csv").write_text("a,b")
    snap = snapshot(str(project), globs=["*.csv"])
    assert any("data.csv" in k for k in snap)


def test_snapshot_records_mtime(project):
    p = project / "plot.png"
    p.write_bytes(b"PNG")
    snap = snapshot(str(project))
    key = str(p.resolve())
    assert snap[key] == pytest.approx(p.stat().st_mtime)


# ── diff ──────────────────────────────────────────────────────────────────


def test_diff_new_file(project):
    before = snapshot(str(project))
    (project / "new.png").write_bytes(b"PNG")
    changed = diff(str(project), before)
    assert len(changed) == 1
    assert changed[0].rel_path == "new.png"


def test_diff_no_change(project):
    (project / "existing.png").write_bytes(b"PNG")
    before = snapshot(str(project))
    changed = diff(str(project), before)
    assert changed == []


def test_diff_modified_file(project):
    p = project / "plot.png"
    p.write_bytes(b"PNG old")
    before = snapshot(str(project))
    time.sleep(0.02)  # ensure mtime changes
    p.write_bytes(b"PNG new")
    changed = diff(str(project), before)
    assert len(changed) == 1
    assert changed[0].rel_path == "plot.png"


def test_diff_multiple_new_files(project):
    before = snapshot(str(project))
    for name in ["a.png", "b.png", "c.png"]:
        (project / name).write_bytes(b"PNG")
    changed = diff(str(project), before)
    assert len(changed) == 3
    assert {a.rel_path for a in changed} == {"a.png", "b.png", "c.png"}


def test_diff_newest_first(project):
    before = snapshot(str(project))
    (project / "old.png").write_bytes(b"PNG")
    time.sleep(0.02)
    (project / "new.png").write_bytes(b"PNG")
    changed = diff(str(project), before)
    assert changed[0].rel_path == "new.png"


def test_diff_max_results(project):
    before = snapshot(str(project))
    for i in range(10):
        (project / f"plot{i}.png").write_bytes(b"PNG")
    changed = diff(str(project), before, max_results=3)
    assert len(changed) == 3


def test_diff_explicit_after(project):
    (project / "a.png").write_bytes(b"PNG")
    before = snapshot(str(project))
    (project / "b.png").write_bytes(b"PNG")
    after = snapshot(str(project))
    changed = diff(str(project), before, after=after)
    assert len(changed) == 1
    assert changed[0].rel_path == "b.png"


# ── Artifact dataclass ────────────────────────────────────────────────────


def test_artifact_to_dict():
    a = Artifact(
        path="/abs/plot.png",
        rel_path="plot.png",
        mime="image/png",
        size=100,
        mtime=1234567890.0,
    )
    d = a.to_dict()
    assert d["path"] == "/abs/plot.png"
    assert d["rel_path"] == "plot.png"
    assert d["mime"] == "image/png"
    assert d["size"] == 100
    assert d["mtime"] == 1234567890.0


def test_artifact_mime_png(project):
    (project / "img.png").write_bytes(b"PNG")
    before = snapshot(str(project), globs=["*.png"])
    # File already existed; touch it to change mtime
    time.sleep(0.02)
    p = project / "img.png"
    p.write_bytes(b"PNG2")
    changed = diff(str(project), before, globs=["*.png"])
    assert changed[0].mime == "image/png"


def test_artifact_mime_pdf(project):
    (project / "report.pdf").write_bytes(b"%PDF")
    before: dict[str, float] = {}
    changed = diff(str(project), before, globs=["*.pdf"])
    assert changed[0].mime == "application/pdf"


def test_artifact_includes_size(project):
    data = b"PNG" * 10
    before: dict[str, float] = {}
    (project / "sized.png").write_bytes(data)
    changed = diff(str(project), before, globs=["*.png"])
    assert changed[0].size == len(data)
