"""Round-trip tests for lmc/projects.py."""
from __future__ import annotations

import pytest

from lmc.config import Paths
from lmc.projects import Project, ProjectError, Registry


@pytest.fixture
def paths(tmp_path):
    p = Paths(config_dir=tmp_path / "config", state_dir=tmp_path / "state")
    p.ensure()
    return p


@pytest.fixture
def reg(paths):
    return Registry(paths)


@pytest.fixture
def proj_dir(tmp_path):
    d = tmp_path / "myproj"
    d.mkdir()
    return d


# ── basic CRUD ────────────────────────────────────────────────────────────


def test_empty_registry(reg):
    assert reg.load() == []


def test_add_and_get(reg, proj_dir):
    p = reg.add("myproj", str(proj_dir))
    assert p.name == "myproj"
    assert p.path == str(proj_dir)
    assert reg.get("myproj") is not None


def test_add_with_tags_and_description(reg, proj_dir):
    p = reg.add("tagproj", str(proj_dir), tags=["ml", "cv"], description="A test project")
    got = reg.get("tagproj")
    assert got is not None
    assert got.tags == ["ml", "cv"]
    assert got.description == "A test project"


def test_load_persists_across_instances(paths, proj_dir):
    Registry(paths).add("persisted", str(proj_dir))
    # New instance reads the same YAML
    loaded = Registry(paths).load()
    assert any(p.name == "persisted" for p in loaded)


def test_duplicate_raises(reg, proj_dir):
    reg.add("dup", str(proj_dir))
    with pytest.raises(ProjectError, match="already exists"):
        reg.add("dup", str(proj_dir))


def test_nonexistent_path_raises(reg, tmp_path):
    with pytest.raises(ProjectError, match="not a directory"):
        reg.add("ghost", str(tmp_path / "does_not_exist"))


def test_remove(reg, proj_dir):
    reg.add("removeme", str(proj_dir))
    reg.remove("removeme")
    assert reg.get("removeme") is None


def test_remove_missing_raises(reg):
    with pytest.raises(ProjectError, match="not found"):
        reg.remove("nope")


def test_update_description(reg, proj_dir):
    reg.add("upd", str(proj_dir))
    p = reg.update("upd", description="new desc")
    assert p.description == "new desc"
    assert reg.get("upd").description == "new desc"


def test_update_tags(reg, proj_dir):
    reg.add("tagged", str(proj_dir))
    p = reg.update("tagged", tags=["a", "b"])
    assert p.tags == ["a", "b"]


def test_update_path(reg, proj_dir, tmp_path):
    reg.add("moveme", str(proj_dir))
    new_dir = tmp_path / "newloc"
    new_dir.mkdir()
    p = reg.update("moveme", path=str(new_dir))
    assert p.path == str(new_dir)


def test_update_missing_raises(reg):
    with pytest.raises(ProjectError, match="not found"):
        reg.update("ghost", description="x")


# ── Project dataclass helpers ─────────────────────────────────────────────


def test_project_exists_on_disk(proj_dir):
    p = Project(name="x", path=str(proj_dir))
    assert p.exists_on_disk() is True


def test_project_not_exists_on_disk(tmp_path):
    p = Project(name="x", path=str(tmp_path / "nowhere"))
    assert p.exists_on_disk() is False


def test_project_round_trip_dict(proj_dir):
    p = Project(name="rt", path=str(proj_dir), tags=["x"], description="desc")
    d = p.to_dict()
    p2 = Project.from_dict(d)
    assert p2.name == p.name
    assert p2.path == p.path
    assert p2.tags == p.tags
    assert p2.description == p.description


def test_list_multiple_projects(reg, tmp_path):
    for i in range(3):
        d = tmp_path / f"proj{i}"
        d.mkdir()
        reg.add(f"proj{i}", str(d))
    projects = reg.load()
    assert len(projects) == 3
    names = {p.name for p in projects}
    assert names == {"proj0", "proj1", "proj2"}
