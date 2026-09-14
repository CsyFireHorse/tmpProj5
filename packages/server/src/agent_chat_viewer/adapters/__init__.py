"""Provider registry. Adding an agent means adding one entry here."""

from __future__ import annotations

from ..config import Settings
from ..models import ProviderId
from .base import Provider, SessionNotFound
from .codex import CodexProvider
from .cursor_cli import CursorCliProvider
from .cursor_ide import CursorIdeProvider
from .opencode import OpencodeProvider

PROVIDER_CLASSES: tuple[type[Provider], ...] = (
    CodexProvider,
    CursorIdeProvider,
    CursorCliProvider,
    OpencodeProvider,
)


class Registry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, Provider] = {cls.id: cls(settings) for cls in PROVIDER_CLASSES}

    def all(self) -> list[Provider]:
        return list(self._providers.values())

    def get(self, provider_id: str) -> Provider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise SessionNotFound(f"unknown provider {provider_id!r}") from exc

    def split_uid(self, uid: str) -> tuple[Provider, str]:
        provider_id, _, session_id = uid.partition(":")
        return self.get(provider_id), session_id


__all__ = [
    "PROVIDER_CLASSES",
    "Provider",
    "ProviderId",
    "Registry",
    "SessionNotFound",
]
