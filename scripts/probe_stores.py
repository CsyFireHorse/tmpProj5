#!/usr/bin/env python3
"""Probe the real stores on this machine and report what is actually there.

This is the tool that turns ``docs/storage-formats.md`` from reverse-engineered
notes into verified facts. It is strictly read-only: it opens SQLite databases
through the same snapshot path the adapters use and never writes to a store.

    python scripts/probe_stores.py            # summary per provider
    python scripts/probe_stores.py --fields   # also print field histograms
    python scripts/probe_stores.py --sample 3 # print N sample records per kind
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "server" / "src"))

from agent_chat_viewer.adapters import Registry  # noqa: E402
from agent_chat_viewer.config import build_settings  # noqa: E402
from agent_chat_viewer.util.jsonl import iter_jsonl, loads_maybe  # noqa: E402
from agent_chat_viewer.util.sqlite_ro import read_only, table_names  # noqa: E402


def heading(text: str) -> None:
    print(f"\n{text}\n{'=' * len(text)}")


def probe_codex(settings, args) -> None:
    heading("codex")
    root = settings.codex_home / "sessions"
    print(f"root: {root} (exists={root.exists()})")
    if not root.exists():
        return
    files = sorted(root.rglob("rollout-*.jsonl"))
    print(f"rollout files: {len(files)}")
    kinds: Counter[str] = Counter()
    item_types: Counter[str] = Counter()
    meta_fields: Counter[str] = Counter()
    samples: dict[str, list[Any]] = {}
    for path in files[:200]:
        for _lineno, value, error in iter_jsonl(path):
            if error or not isinstance(value, dict):
                continue
            kind = str(value.get("type"))
            kinds[kind] += 1
            payload = value.get("payload")
            if isinstance(payload, dict):
                if kind == "session_meta":
                    meta_fields.update(payload.keys())
                item_type = f"{kind}/{payload.get('type')}"
                item_types[item_type] += 1
                if args.sample and len(samples.setdefault(item_type, [])) < args.sample:
                    samples[item_type].append(payload)
    print("line types:", dict(kinds))
    print("item types:", dict(item_types.most_common(30)))
    if args.fields:
        print("session_meta fields:", dict(meta_fields))
    _dump_samples(samples, args)


def probe_cursor_ide(settings, args) -> None:
    heading("cursor-ide")
    db = settings.cursor_user_root / "globalStorage" / "state.vscdb"
    print(f"globalStorage: {db} (exists={db.exists()})")
    if db.exists():
        try:
            with read_only(db, settings.snapshot_dir) as conn:
                print("tables:", sorted(table_names(conn)))
                if "cursorDiskKV" in table_names(conn):
                    prefixes: Counter[str] = Counter()
                    for (key,) in conn.execute("SELECT key FROM cursorDiskKV"):
                        prefixes[str(key).split(":", 1)[0]] += 1
                    print("cursorDiskKV key prefixes:", dict(prefixes.most_common(20)))
                    if args.fields:
                        row = conn.execute(
                            "SELECT value FROM cursorDiskKV WHERE key LIKE 'composerData:%' LIMIT 1"
                        ).fetchone()
                        if row:
                            data = loads_maybe(row[0])
                            print("composerData fields:", sorted(data) if isinstance(data, dict) else "?")
                        row = conn.execute(
                            "SELECT value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%' LIMIT 1"
                        ).fetchone()
                        if row:
                            data = loads_maybe(row[0])
                            print("bubble fields:", sorted(data) if isinstance(data, dict) else "?")
        except sqlite3.Error as exc:
            print(f"  unreadable: {exc}")
    ws_root = settings.cursor_user_root / "workspaceStorage"
    if ws_root.exists():
        print(f"workspaceStorage: {len(list(ws_root.iterdir()))} workspaces")


def probe_cursor_cli(settings, args) -> None:
    heading("cursor-cli")
    chats = settings.cursor_home / "chats"
    print(f"chats: {chats} (exists={chats.exists()})")
    if not chats.exists():
        return
    buckets = [d for d in chats.iterdir() if d.is_dir()]
    sessions = [s for b in buckets for s in b.iterdir() if (s / "store.db").exists()]
    print(f"workspace buckets: {len(buckets)}, sessions: {len(sessions)}")
    if not sessions:
        return
    store = sessions[0] / "store.db"
    with read_only(store, settings.snapshot_dir) as conn:
        print("tables:", sorted(table_names(conn)))
        if "blobs" in table_names(conn):
            total = conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
            json_like = 0
            shapes: Counter[str] = Counter()
            for (data,) in conn.execute("SELECT data FROM blobs"):
                raw = bytes(data) if isinstance(data, memoryview) else data
                if isinstance(raw, bytes | bytearray) and raw[:1] in (b"{", b"["):
                    json_like += 1
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        shapes[",".join(sorted(parsed)[:8])] += 1
            print(f"blobs: {total} total, {json_like} json-like")
            print("json blob shapes:", dict(shapes.most_common(10)))


def probe_opencode(settings, args) -> None:
    heading("opencode")
    data = settings.opencode_data
    print(f"data dir: {data} (exists={data.exists()})")
    db = data / "opencode.db"
    if db.exists():
        with read_only(db, settings.snapshot_dir) as conn:
            tables = sorted(table_names(conn))
            print("sqlite tables:", tables)
            for table in ("session", "message", "part"):
                if table in tables:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                    print(f"  {table}: {count} rows")
    storage = data / "storage"
    if storage.exists():
        for kind in ("session", "message", "part"):
            directory = storage / kind
            if directory.exists():
                print(f"  json {kind}: {sum(1 for _ in directory.rglob('*.json'))} files")


def _dump_samples(samples: dict[str, list[Any]], args) -> None:
    if not args.sample:
        return
    for kind, records in sorted(samples.items()):
        for record in records:
            print(f"\n--- sample {kind} ---")
            print(json.dumps(record, ensure_ascii=False, indent=2)[: args.max_chars])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fields", action="store_true", help="print field histograms")
    parser.add_argument("--sample", type=int, default=0, help="print N sample records per item type")
    parser.add_argument("--max-chars", type=int, default=2000)
    args = parser.parse_args()

    settings = build_settings()
    print(f"home: {settings.home}")
    probe_codex(settings, args)
    probe_cursor_ide(settings, args)
    probe_cursor_cli(settings, args)
    probe_opencode(settings, args)

    heading("adapter detection")
    for provider in Registry(settings).all():
        status = provider.detect()
        print(
            f"{status.id:<12} detected={status.detected!s:<5} "
            f"sessions={status.session_count} {status.note or status.error or ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
