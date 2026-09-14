"""Incremental scanner.

Walks every detected provider, fully parses the sessions whose source file
changed since last time, and writes them into the index. Runs on a background
thread at startup so the first request does not block on a cold cache.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from ..adapters import Registry
from ..models import IndexStatus, Session
from .store import Index

log = logging.getLogger(__name__)

Listener = Callable[[str, dict], None]


class Scanner:
    def __init__(self, registry: Registry, index: Index) -> None:
        self.registry = registry
        self.index = index
        self.status = IndexStatus()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._listeners: list[Listener] = []

    # -- events ------------------------------------------------------------
    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _emit(self, event: str, data: dict) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, data)
            except Exception:  # pragma: no cover - a bad listener must not stop a scan
                log.exception("scan listener failed")

    # -- scanning ----------------------------------------------------------
    def start(self, *, force: bool = False) -> bool:
        """Kick off a background scan. Returns False if one is already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._thread = threading.Thread(target=self._run, kwargs={"force": force}, daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)

    def _run(self, *, force: bool) -> None:
        try:
            self.scan(force=force)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("scan failed")
            self.status.running = False
            self.status.last_error = f"{type(exc).__name__}: {exc}"
            self._emit("index", self.status.model_dump(mode="json"))

    def scan(self, *, force: bool = False) -> IndexStatus:
        self.status = IndexStatus(running=True)
        self._emit("index", self.status.model_dump(mode="json"))

        discovered: list[tuple[str, object]] = []
        for provider in self.registry.all():
            if not any(root.exists() for root in provider.roots()):
                continue
            try:
                summaries = list(provider.iter_sessions())
            except Exception as exc:
                self.status.last_error = f"{provider.id}: {type(exc).__name__}: {exc}"
                log.warning("listing failed for %s: %s", provider.id, exc)
                continue
            discovered.append((provider.id, summaries))
            self.status.total += len(summaries)
        self._emit("index", self.status.model_dump(mode="json"))

        for provider_id, summaries in discovered:
            provider = self.registry.get(provider_id)
            known = self.index.fingerprints(provider_id)
            seen: set[str] = set()
            for summary in summaries:  # type: ignore[union-attr]
                seen.add(summary.uid)
                self.status.scanned += 1
                cached = known.get(summary.uid)
                unchanged = (
                    cached is not None
                    and cached[0] == summary.source_mtime
                    and cached[1] == summary.source_size
                    and cached[2] != "error"
                )
                if unchanged and not force:
                    continue
                try:
                    session = provider.load_session(summary.id)
                except Exception as exc:
                    log.warning("failed to load %s: %s", summary.uid, exc)
                    session = Session(
                        summary=summary.model_copy(update={"parse_status": "error"}),
                        notes=[f"Could not be parsed: {type(exc).__name__}: {exc}"],
                    )
                self.index.upsert(session)
                self.status.indexed_sessions += 1
                self._emit(
                    "session",
                    {"uid": summary.uid, "provider": provider_id, "title": session.summary.title},
                )
                if self.status.scanned % 25 == 0:
                    self._emit("index", self.status.model_dump(mode="json"))

            stale = [uid for uid in known if uid not in seen]
            self.index.delete(stale)

        self.status.running = False
        self.status.last_finished_at = datetime.now(tz=UTC)
        self._emit("index", self.status.model_dump(mode="json"))
        return self.status
