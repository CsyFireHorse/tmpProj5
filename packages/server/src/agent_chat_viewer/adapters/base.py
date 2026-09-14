"""Provider adapter protocol and shared helpers.

Adding support for another coding agent means writing one module here and
registering it in ``adapters/__init__.py``; nothing else in the app needs to
know the provider exists.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..config import Settings
from ..models import ProviderId, ProviderStatus, Session, SessionSummary


class SessionNotFound(LookupError):
    pass


class Provider(ABC):
    id: ProviderId
    name: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- discovery ---------------------------------------------------------
    @abstractmethod
    def roots(self) -> list[Path]:
        """Directories or files this adapter reads from."""

    def detect(self) -> ProviderStatus:
        roots = [root for root in self.roots() if root.exists()]
        status = ProviderStatus(
            id=self.id,
            name=self.name,
            detected=bool(roots),
            roots=[str(root) for root in roots],
        )
        if not roots:
            status.note = f"not found: {', '.join(str(r) for r in self.roots())}"
            return status
        try:
            status.session_count = sum(1 for _ in self.iter_sessions())
        except Exception as exc:  # pragma: no cover - defensive
            status.error = f"{type(exc).__name__}: {exc}"
        return status

    @abstractmethod
    def iter_sessions(self) -> Iterator[SessionSummary]:
        """Cheap listing: read headers/indexes only, never full transcripts."""

    @abstractmethod
    def load_session(self, session_id: str) -> Session:
        """Fully parse one session."""

    def raw_records(self, session_id: str) -> Iterator[dict[str, Any]]:
        """Original records, for the raw inspector. Optional."""
        session = self.load_session(session_id)
        for message in session.messages:
            for part in message.parts:
                if part.raw is not None:
                    yield {"message_id": message.id, "part_id": part.id, "raw": part.raw}

    def resume_command(self, session_id: str) -> str | None:
        """A command the user can copy to continue the session. Never executed."""
        return None

    # -- helpers -----------------------------------------------------------
    def uid(self, session_id: str) -> str:
        return f"{self.id}:{session_id}"

    @property
    def snapshot_dir(self) -> Path:
        return self.settings.snapshot_dir


def stat_of(path: Path) -> tuple[float | None, int | None]:
    try:
        stat = path.stat()
    except OSError:
        return None, None
    return stat.st_mtime, stat.st_size


def project_name(cwd: str | None) -> str | None:
    if not cwd:
        return None
    return os.path.basename(cwd.rstrip("/\\")) or cwd


def walk_files(root: Path, pattern: str, *, follow_symlinks: bool = False) -> Iterator[Path]:
    """Recursive glob that does not follow directory symlinks (cycle guard)."""
    if not root.exists():
        return
    stack = [root]
    seen: set[Path] = set()
    while stack:
        current = stack.pop()
        try:
            resolved = current.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if follow_symlinks or not entry.is_symlink():
                    stack.append(entry)
            elif entry.match(pattern):
                yield entry
