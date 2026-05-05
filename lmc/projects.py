"""Project registry — YAML-backed list of project name → working directory.

Mirrors the role of ``projects.conf`` in the existing Mission Control bash
stack, but with a richer schema (description, tags) and a YAML format that's
friendlier for hand-editing and diffing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .config import Paths, get_paths


class ProjectError(Exception):
    """Raised for invalid registry operations (duplicate, missing, bad path)."""


@dataclass
class Project:
    name: str
    path: str
    tags: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        return cls(
            name=str(d["name"]),
            path=str(d["path"]),
            tags=list(d.get("tags") or []),
            description=str(d.get("description") or ""),
        )

    def exists_on_disk(self) -> bool:
        return Path(self.path).expanduser().is_dir()


class Registry:
    """Read/write the project registry. Single YAML file, list of projects."""

    def __init__(self, paths: Paths | None = None) -> None:
        self.paths = paths or get_paths()

    @property
    def file(self) -> Path:
        return self.paths.projects_yaml

    def load(self) -> list[Project]:
        if not self.file.exists():
            return []
        raw = yaml.safe_load(self.file.read_text()) or {}
        return [Project.from_dict(p) for p in raw.get("projects", [])]

    def save(self, projects: list[Project]) -> None:
        self.paths.ensure()
        data = {"projects": [p.to_dict() for p in projects]}
        self.file.write_text(yaml.safe_dump(data, sort_keys=False))

    def get(self, name: str) -> Project | None:
        for p in self.load():
            if p.name == name:
                return p
        return None

    def add(
        self,
        name: str,
        path: str,
        tags: list[str] | None = None,
        description: str = "",
    ) -> Project:
        projects = self.load()
        if any(p.name == name for p in projects):
            raise ProjectError(f"project '{name}' already exists")
        path_obj = Path(path).expanduser().resolve()
        if not path_obj.is_dir():
            raise ProjectError(f"path is not a directory: {path_obj}")
        project = Project(
            name=name, path=str(path_obj), tags=tags or [], description=description
        )
        projects.append(project)
        self.save(projects)
        return project

    def remove(self, name: str) -> None:
        projects = self.load()
        new = [p for p in projects if p.name != name]
        if len(new) == len(projects):
            raise ProjectError(f"project '{name}' not found")
        self.save(new)

    def update(
        self,
        name: str,
        *,
        path: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
    ) -> Project:
        projects = self.load()
        for i, p in enumerate(projects):
            if p.name == name:
                if path is not None:
                    p.path = str(Path(path).expanduser().resolve())
                if tags is not None:
                    p.tags = tags
                if description is not None:
                    p.description = description
                projects[i] = p
                self.save(projects)
                return p
        raise ProjectError(f"project '{name}' not found")
