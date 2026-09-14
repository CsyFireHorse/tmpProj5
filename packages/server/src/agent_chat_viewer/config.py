"""Path resolution for every supported store.

Every default can be overridden with an environment variable. ``ACV_HOME``
re-roots all of them at once, which is how the test fixtures work: point it at
a synthetic home and no adapter ever touches the real machine.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _first_existing(candidates: list[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return fallback


@dataclass(frozen=True)
class Settings:
    home: Path
    codex_home: Path
    cursor_home: Path
    cursor_user_root: Path
    opencode_data: Path
    state_dir: Path
    extra_project_roots: list[Path] = field(default_factory=list)

    @property
    def index_db(self) -> Path:
        return self.state_dir / "index.db"

    @property
    def snapshot_dir(self) -> Path:
        return self.state_dir / "snapshots"


def _cursor_user_root(home: Path) -> Path:
    """Cursor's VS Code-style user directory, which is platform specific."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    candidates = [
        home / "Library" / "Application Support" / "Cursor" / "User",
        home / ".config" / "Cursor" / "User",
        home / "AppData" / "Roaming" / "Cursor" / "User",
    ]
    if xdg:
        candidates.insert(0, Path(xdg).expanduser() / "Cursor" / "User")
    if sys.platform == "darwin":
        default = candidates[0]
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        default = Path(appdata) / "Cursor" / "User" if appdata else candidates[2]
    else:
        default = Path(xdg).expanduser() / "Cursor" / "User" if xdg else candidates[1]
    return _first_existing(candidates, default)


def _opencode_data(home: Path) -> Path:
    xdg_data = os.environ.get("XDG_DATA_HOME")
    candidates = [
        home / ".local" / "share" / "opencode",
        home / "Library" / "Application Support" / "opencode",
    ]
    if xdg_data:
        candidates.insert(0, Path(xdg_data).expanduser() / "opencode")
    return _first_existing(candidates, candidates[0])


def _state_dir(home: Path) -> Path:
    override = _env_path("ACV_STATE_DIR")
    if override:
        return override
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "agent-chat-viewer"
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).expanduser() / "agent-chat-viewer"
    return home / ".local" / "state" / "agent-chat-viewer"


def build_settings() -> Settings:
    home = _env_path("ACV_HOME") or Path.home()
    extra = [Path(p).expanduser() for p in os.environ.get("ACV_PROJECT_ROOTS", "").split(os.pathsep) if p]
    return Settings(
        home=home,
        codex_home=_env_path("ACV_CODEX_HOME") or _env_path("CODEX_HOME") or home / ".codex",
        cursor_home=_env_path("ACV_CURSOR_HOME") or home / ".cursor",
        cursor_user_root=_env_path("ACV_CURSOR_USER_ROOT") or _cursor_user_root(home),
        opencode_data=_env_path("ACV_OPENCODE_DATA") or _opencode_data(home),
        state_dir=_state_dir(home),
        extra_project_roots=extra,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
