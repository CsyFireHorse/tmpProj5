"""The source stores belong to another process. Reading must not disturb them."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time

from agent_chat_viewer.adapters.cursor_ide import CursorIdeProvider
from agent_chat_viewer.util.sqlite_ro import read_only, snapshot


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reading_leaves_the_source_file_untouched(settings, tmp_path):
    db = settings.cursor_user_root / "globalStorage" / "state.vscdb"
    before = (_digest(db), db.stat().st_size)
    list(CursorIdeProvider(settings).iter_sessions())
    CursorIdeProvider(settings).load_session("3f1c8c9e-0000-4a00-9000-composer0001")
    assert (_digest(db), db.stat().st_size) == before


def test_snapshot_is_a_separate_file(settings):
    db = settings.cursor_user_root / "globalStorage" / "state.vscdb"
    copy = snapshot(db, settings.snapshot_dir)
    assert copy != db
    assert copy.parent == settings.snapshot_dir


def test_snapshot_is_reused_until_the_source_changes(settings):
    db = settings.cursor_user_root / "globalStorage" / "state.vscdb"
    first = snapshot(db, settings.snapshot_dir)
    assert snapshot(db, settings.snapshot_dir) == first


def test_connection_rejects_writes(settings):
    db = settings.cursor_user_root / "globalStorage" / "state.vscdb"
    with read_only(db, settings.snapshot_dir) as conn:
        try:
            conn.execute("INSERT INTO ItemTable VALUES ('x','y')")
        except sqlite3.OperationalError as exc:
            assert "readonly" in str(exc).lower() or "query_only" in str(exc).lower()
        else:  # pragma: no cover - would mean the guard is gone
            raise AssertionError("write should have been refused")


def test_reading_while_another_process_writes(settings, tmp_path):
    """A WAL-mode database under concurrent writes must still be readable."""
    live = tmp_path / "live.db"
    conn = sqlite3.connect(live)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (i INTEGER)")
    conn.commit()

    stop = threading.Event()

    def writer():
        writer_conn = sqlite3.connect(live)
        i = 0
        while not stop.is_set():
            writer_conn.execute("INSERT INTO t VALUES (?)", (i,))
            writer_conn.commit()
            i += 1
            time.sleep(0.001)
        writer_conn.close()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        for _ in range(10):
            with read_only(live, tmp_path / "snap") as ro:
                count = ro.execute("SELECT COUNT(*) FROM t").fetchone()[0]
                assert count >= 0
    finally:
        stop.set()
        thread.join(timeout=2)
        conn.close()
