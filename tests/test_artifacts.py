"""Tests for lmc/artifacts.py — snapshot/diff/Artifact."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from lmc.artifacts import Artifact, diff, snapshot
from lmc.config import Settings


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def project(root: Path) -> str:
    (root / "figures").mkdir()
    return str(root)


def test_snapshot_empty(root: Path) -> None:
    result = snapshot(str(root))
    assert result == {}


def test_snapshot_finds_png(project: str, root: Path) -> None:
    img = root / "figures" / "plot.png"
    img.write_bytes(b"\x89PNG\r\n")
    result = snapshot(project)
    assert any("plot.png" in k for k in result)


def test_snapshot_finds_nested(project: str, root: Path) -> None:
    (root / "figures" / "sub").mkdir()
    nested = root / "figures" / "sub" / "chart.png"
    nested.write_bytes(b"fake png")
    result = snapshot(project)
    assert any("chart.png" in k for k in result)


def test_snapshot_skips_non_matching(project: str, root: Path) -> None:
    txt = root / "notes.txt"
    txt.write_text("hello")
    result = snapshot(project)
    assert all("notes.txt" not in k for k in result)


def test_snapshot_custom_globs(root: Path) -> None:
    (root / "out.csv").write_text("a,b,c")
    result = snapshot(str(root), globs=["*.csv"])
    assert any("out.csv" in k for k in result)


def test_snapshot_records_mtime(project: str, root: Path) -> None:
    img = root / "figures" / "a.png"
    img.write_bytes(b"data")
    result = snapshot(project)
    key = next(k for k in result if "a.png" in k)
    assert result[key] == pytest.approx(img.stat().st_mtime, abs=1e-3)


def test_diff_new_file(project: str, root: Path) -> None:
    before = snapshot(project)
    (root / "figures" / "new.png").write_bytes(b"new")
    results = diff(project, before)
    assert len(results) == 1
    assert "new.png" in results[0].rel_path


def test_diff_no_change(project: str) -> None:
    before = snapshot(project)
    results = diff(project, before, after=before.copy())
    assert results == []


def test_diff_modified_file(project: str, root: Path) -> None:
    img = root / "figures" / "existing.png"
    img.write_bytes(b"v1")
    before = snapshot(project)
    time.sleep(0.02)
    img.write_bytes(b"v2")
    results = diff(project, before)
    assert any("existing.png" in a.rel_path for a in results)


def test_diff_multiple_new_files(project: str, root: Path) -> None:
    before = snapshot(project)
    for i in range(3):
        (root / "figures" / f"img{i}.png").write_bytes(b"data")
    results = diff(project, before)
    assert len(results) == 3


def test_diff_newest_first(project: str, root: Path) -> None:
    before = snapshot(project)
    (root / "figures" / "first.png").write_bytes(b"a")
    time.sleep(0.02)
    (root / "figures" / "second.png").write_bytes(b"b")
    results = diff(project, before)
    assert results[0].mtime >= results[-1].mtime


def test_diff_max_results(project: str, root: Path) -> None:
    before = snapshot(project)
    for i in range(10):
        (root / "figures" / f"p{i}.png").write_bytes(b"x")
    results = diff(project, before, max_results=3)
    assert len(results) == 3


def test_diff_explicit_after(project: str, root: Path) -> None:
    before = snapshot(project)
    (root / "figures" / "x.png").write_bytes(b"x")
    after = snapshot(project)
    results = diff(project, before, after=after)
    assert len(results) == 1


def test_artifact_to_dict(project: str, root: Path) -> None:
    before = snapshot(project)
    p = root / "figures" / "z.png"
    p.write_bytes(b"z")
    results = diff(project, before)
    d = results[0].to_dict()
    assert "path" in d and "rel_path" in d and "mime" in d and "size" in d


def test_artifact_mime_png(project: str, root: Path) -> None:
    before = snapshot(project)
    (root / "figures" / "img.png").write_bytes(b"data")
    results = diff(project, before)
    assert results[0].mime == "image/png"


def test_artifact_mime_pdf(project: str, root: Path) -> None:
    before = snapshot(project, globs=["*.pdf"])
    (root / "doc.pdf").write_bytes(b"%PDF-1.4")
    results = diff(project, before, globs=["*.pdf"])
    assert results[0].mime == "application/pdf"


def test_artifact_includes_size(project: str, root: Path) -> None:
    before = snapshot(project)
    content = b"hello world"
    (root / "figures" / "sz.png").write_bytes(content)
    results = diff(project, before)
    assert results[0].size == len(content)
