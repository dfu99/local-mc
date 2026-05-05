"""Tests for lmc/projects.py — Registry CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from lmc.config import Paths
from lmc.projects import Project, ProjectError, Registry


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    cfg.mkdir()
    state.mkdir()
    return Paths(config_dir=cfg, state_dir=state)


@pytest.fixture
def reg(paths: Paths) -> Registry:
    return Registry(paths)


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    d = tmp_path / "myproject"
    d.mkdir()
    return d


def test_empty_registry(reg: Registry) -> None:
    assert reg.load() == []


def test_add_and_get(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    p = reg.get("demo")
    assert p is not None
    assert p.name == "demo"
    assert p.path == str(proj_dir)


def test_add_with_tags_and_description(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir), tags=["ml", "exp"], description="A test project")
    p = reg.get("demo")
    assert p is not None
    assert p.tags == ["ml", "exp"]
    assert p.description == "A test project"


def test_load_persists_across_instances(reg: Registry, paths: Paths, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    reg2 = Registry(paths)
    assert reg2.get("demo") is not None


def test_duplicate_raises(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    with pytest.raises(ProjectError, match="already exists"):
        reg.add("demo", str(proj_dir))


def test_nonexistent_path_raises(reg: Registry, tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="not a directory"):
        reg.add("ghost", str(tmp_path / "does_not_exist"))


def test_remove(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    reg.remove("demo")
    assert reg.get("demo") is None


def test_remove_missing_raises(reg: Registry) -> None:
    with pytest.raises(ProjectError, match="not found"):
        reg.remove("nope")


def test_update_description(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    reg.update("demo", description="updated")
    assert reg.get("demo").description == "updated"


def test_update_tags(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    reg.update("demo", tags=["new"])
    assert reg.get("demo").tags == ["new"]


def test_update_path(reg: Registry, proj_dir: Path, tmp_path: Path) -> None:
    reg.add("demo", str(proj_dir))
    new_dir = tmp_path / "newloc"
    new_dir.mkdir()
    reg.update("demo", path=str(new_dir))
    assert reg.get("demo").path == str(new_dir.resolve())


def test_update_missing_raises(reg: Registry) -> None:
    with pytest.raises(ProjectError, match="not found"):
        reg.update("ghost", description="x")


def test_project_exists_on_disk(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    p = reg.get("demo")
    assert p is not None
    assert p.exists_on_disk()


def test_project_not_exists_on_disk(reg: Registry, proj_dir: Path) -> None:
    reg.add("demo", str(proj_dir))
    proj_dir.rmdir()
    p = reg.get("demo")
    assert p is not None
    assert not p.exists_on_disk()


def test_project_round_trip_dict(proj_dir: Path) -> None:
    p = Project(name="x", path=str(proj_dir), tags=["a"], description="d")
    p2 = Project.from_dict(p.to_dict())
    assert p2.name == p.name
    assert p2.tags == p.tags
    assert p2.description == p.description


def test_list_multiple_projects(reg: Registry, tmp_path: Path) -> None:
    for i in range(3):
        d = tmp_path / f"proj{i}"
        d.mkdir()
        reg.add(f"proj{i}", str(d))
    projects = reg.load()
    assert len(projects) == 3
    names = {p.name for p in projects}
    assert names == {"proj0", "proj1", "proj2"}
