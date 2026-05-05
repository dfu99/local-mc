"""Shared pytest fixtures for local-mc.

Every test gets an isolated `LMC_HOME` under a temp dir. The `Paths`
helper in `lmc.config` honours the env var, but most code paths take a
`Paths` instance directly so tests don't need to mutate the environment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lmc.config import Paths, Settings
from lmc.projects import Registry
from lmc.store import Store


@pytest.fixture
def lmc_paths(tmp_path: Path) -> Paths:
    paths = Paths(
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
    )
    paths.ensure()
    return paths


@pytest.fixture
def lmc_settings() -> Settings:
    return Settings(agent="echo", max_upload_mb=1)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    p = tmp_path / "demo-project"
    p.mkdir()
    return p


@pytest.fixture
def registry(lmc_paths: Paths) -> Registry:
    return Registry(lmc_paths)


@pytest.fixture
def store(lmc_paths: Paths) -> Store:
    return Store(paths=lmc_paths)
