"""Read a SQLite database that another process may be actively writing.

Cursor and opencode keep their stores in WAL mode and hold locks while the app
runs. Opening the live file read-only can return a torn or stale view, so every
adapter goes through :func:`read_only` instead, which works on a private
snapshot. The source database is never opened for writing and never modified.

Two snapshot strategies are attempted, in order:

1. SQLite's online backup API from a read-only connection. This takes a shared
   lock and produces a transactionally consistent copy.
2. A plain file copy of ``db``, ``db-wal`` and ``db-shm`` into a temp dir, then
   opening the *copy* read-write so SQLite can replay the WAL there.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_lock = threading.Lock()
_snapshot_cache: dict[str, Path] = {}


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _backup_snapshot(src: Path, dst: Path) -> bool:
    try:
        source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return False
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
        return True
    except sqlite3.Error:
        dst.unlink(missing_ok=True)
        return False
    finally:
        source.close()


def _copy_snapshot(src: Path, dst: Path) -> None:
    shutil.copyfile(src, dst)
    for suffix in ("-wal", "-shm"):
        sidecar = src.with_name(src.name + suffix)
        if sidecar.exists():
            shutil.copyfile(sidecar, dst.with_name(dst.name + suffix))


def snapshot(path: Path, snapshot_dir: Path) -> Path:
    """Return a path to a private, consistent copy of ``path``."""
    path = Path(path)
    key = _fingerprint(path)
    with _lock:
        cached = _snapshot_cache.get(key)
        if cached and cached.exists():
            return cached

        snapshot_dir.mkdir(parents=True, exist_ok=True)
        dst = snapshot_dir / f"{path.stem}-{key}.db"
        if not dst.exists():
            tmp = dst.with_suffix(".tmp")
            tmp.unlink(missing_ok=True)
            if not _backup_snapshot(path, tmp):
                _copy_snapshot(path, tmp)
            tmp.replace(dst)
            for suffix in ("-wal", "-shm"):
                sidecar = tmp.with_name(tmp.name + suffix)
                if sidecar.exists():
                    sidecar.replace(dst.with_name(dst.name + suffix))

        # Drop older snapshots of the same database so the cache dir cannot grow
        # without bound as the source keeps changing.
        for stale in snapshot_dir.glob(f"{path.stem}-*.db"):
            if stale != dst:
                stale.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    stale.with_name(stale.name + suffix).unlink(missing_ok=True)

        _snapshot_cache[key] = dst
        return dst


@contextmanager
def read_only(path: Path, snapshot_dir: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection to a snapshot of ``path``, with writes disabled."""
    copy = snapshot(path, snapshot_dir)
    conn = sqlite3.connect(copy, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = 1")
        yield conn
    finally:
        conn.close()


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    return {row[0] for row in rows}


def column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except sqlite3.Error:
        return []


def clear_snapshot_cache() -> None:
    with _lock:
        _snapshot_cache.clear()
