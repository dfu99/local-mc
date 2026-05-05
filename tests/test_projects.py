"""Registry CRUD + edge cases."""
from __future__ import annotations

from pathlib import Path

import pytest

from lmc.projects import ProjectError, Registry


def test_empty_registry_returns_empty_list(registry: Registry):
    assert registry.load() == []


def test_add_project_round_trips(registry: Registry, project_dir: Path):
    p = registry.add(
        "demo", str(project_dir), tags=["test", "research"], description="hi"
    )
    assert p.name == "demo"
    assert Path(p.path) == project_dir.resolve()
    assert p.tags == ["test", "research"]
    assert p.description == "hi"

    reloaded = registry.load()
    assert len(reloaded) == 1
    assert reloaded[0].name == "demo"


def test_add_duplicate_raises(registry: Registry, project_dir: Path):
    registry.add("demo", str(project_dir))
    with pytest.raises(ProjectError, match="already exists"):
        registry.add("demo", str(project_dir))


def test_add_nonexistent_path_raises(registry: Registry, tmp_path: Path):
    with pytest.raises(ProjectError, match="not a directory"):
        registry.add("ghost", str(tmp_path / "does-not-exist"))


def test_remove_project(registry: Registry, project_dir: Path):
    registry.add("demo", str(project_dir))
    registry.remove("demo")
    assert registry.load() == []


def test_remove_unknown_raises(registry: Registry):
    with pytest.raises(ProjectError, match="not found"):
        registry.remove("ghost")


def test_update_project_fields(registry: Registry, project_dir: Path, tmp_path: Path):
    registry.add("demo", str(project_dir), tags=["a"])
    moved = tmp_path / "moved"
    moved.mkdir()
    updated = registry.update(
        "demo", path=str(moved), tags=["b", "c"], description="moved"
    )
    assert Path(updated.path) == moved.resolve()
    assert updated.tags == ["b", "c"]
    assert updated.description == "moved"


def test_get_project(registry: Registry, project_dir: Path):
    registry.add("demo", str(project_dir))
    p = registry.get("demo")
    assert p is not None and p.name == "demo"
    assert registry.get("nope") is None


def test_exists_on_disk_reflects_filesystem(registry: Registry, project_dir: Path):
    registry.add("demo", str(project_dir))
    p = registry.get("demo")
    assert p is not None
    assert p.exists_on_disk()
    project_dir.rmdir()
    assert not p.exists_on_disk()


def test_yaml_file_format_is_stable(registry: Registry, project_dir: Path):
    registry.add("demo", str(project_dir), tags=["t1"], description="d")
    raw = registry.file.read_text()
    # Order matters for diffing; YAML keys should be the dataclass field order.
    assert "projects:" in raw
    assert "name: demo" in raw
    assert "path:" in raw
    assert "tags:" in raw
    assert "description: d" in raw
