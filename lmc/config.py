"""Filesystem layout and config loading for local-mc.

By default everything lives under ``~/.local/share/lmc`` (state) and
``~/.config/lmc`` (config). Override with the ``LMC_HOME`` env var, which
collapses both into a single directory — handy for tests and isolated demos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


def _xdg(name: str, default: Path) -> Path:
    val = os.environ.get(name)
    return Path(val).expanduser() if val else default


@dataclass(frozen=True)
class Paths:
    """All filesystem paths used by local-mc."""

    config_dir: Path
    state_dir: Path

    @property
    def projects_yaml(self) -> Path:
        return self.config_dir / "projects.yaml"

    @property
    def settings_yaml(self) -> Path:
        return self.config_dir / "settings.yaml"

    @property
    def db_path(self) -> Path:
        return self.state_dir / "lmc.db"

    @property
    def attachments_dir(self) -> Path:
        return self.state_dir / "attachments"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    def ensure(self) -> None:
        for d in (
            self.config_dir,
            self.state_dir,
            self.attachments_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_paths() -> Paths:
    """Resolve config + state directories.

    LMC_HOME takes precedence (single dir for both). Otherwise XDG defaults.
    """
    lmc_home = os.environ.get("LMC_HOME")
    if lmc_home:
        root = Path(lmc_home).expanduser()
        return Paths(config_dir=root / "config", state_dir=root / "state")

    config = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "lmc"
    state = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "lmc"
    return Paths(config_dir=config, state_dir=state)


@dataclass
class Settings:
    """User-tunable settings (loaded from settings.yaml)."""

    host: str = "127.0.0.1"
    port: int = 8765
    agent: str = "claude"  # 'claude' | 'echo'
    claude_bin: str = "claude"
    permission_mode: str = "default"  # 'default' | 'acceptEdits' | 'bypassPermissions'
    auto_open_browser: bool = True
    max_upload_mb: int = 100
    artifact_globs: list[str] | None = None

    def __post_init__(self) -> None:
        if self.artifact_globs is None:
            self.artifact_globs = [
                "figures/**/*.png",
                "figures/**/*.svg",
                "figures/**/*.pdf",
                "results/**/*.png",
                "results/**/*.csv",
                "results/**/*.json",
                "*.png",
                "*.pdf",
            ]


def load_settings(paths: Paths | None = None) -> Settings:
    paths = paths or get_paths()
    if not paths.settings_yaml.exists():
        return Settings()
    raw = yaml.safe_load(paths.settings_yaml.read_text()) or {}
    known = {f for f in Settings.__dataclass_fields__}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(settings: Settings, paths: Paths | None = None) -> None:
    paths = paths or get_paths()
    paths.ensure()
    data = {f: getattr(settings, f) for f in Settings.__dataclass_fields__}
    paths.settings_yaml.write_text(yaml.safe_dump(data, sort_keys=True))
