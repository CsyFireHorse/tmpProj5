from __future__ import annotations

from pathlib import Path

import pytest

from agent_chat_viewer.adapters import Registry
from agent_chat_viewer.config import Settings
from agent_chat_viewer.demo import build_demo_home
from agent_chat_viewer.util.sqlite_ro import clear_snapshot_cache


@pytest.fixture(autouse=True)
def _clear_snapshots():
    clear_snapshot_cache()
    yield
    clear_snapshot_cache()


@pytest.fixture
def demo_home(tmp_path: Path) -> Path:
    return build_demo_home(tmp_path / "home")


@pytest.fixture
def settings(demo_home: Path, tmp_path: Path) -> Settings:
    return Settings(
        home=demo_home,
        codex_home=demo_home / ".codex",
        cursor_home=demo_home / ".cursor",
        cursor_user_root=demo_home / ".config" / "Cursor" / "User",
        opencode_data=demo_home / ".local" / "share" / "opencode",
        state_dir=tmp_path / "state",
    )


@pytest.fixture
def registry(settings: Settings) -> Registry:
    return Registry(settings)
