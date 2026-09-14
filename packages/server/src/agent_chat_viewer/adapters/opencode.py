"""opencode adapter.

opencode has two storage eras and both are supported:

* 1.2.0+ keeps everything in ``~/.local/share/opencode/opencode.db`` with
  ``session`` / ``message`` / ``part`` tables whose ``data`` column holds the
  same JSON payloads the old files held.
* Older versions write one JSON file per record under ``storage/``.

Because the payload shape is identical, only the I/O layer differs; the
normalization below is shared.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..models import (
    CompactionPart,
    ErrorPart,
    FilePart,
    Locator,
    Message,
    PatchFile,
    PatchPart,
    ReasoningPart,
    Session,
    SessionSummary,
    SnapshotPart,
    StepPart,
    SubtaskPart,
    TextPart,
    TodoItem,
    TodoPart,
    TokenUsage,
    ToolPart,
    UnknownPart,
    Warning_,
)
from ..util import timeutil
from ..util.jsonl import as_dict, as_list, read_json
from ..util.sqlite_ro import column_names, read_only, table_names
from ..util.text import derive_title
from .base import Provider, SessionNotFound, project_name, stat_of


class _Store(ABC):
    """Minimal read interface shared by the SQLite and JSON-tree backends."""

    source_path: Path

    @abstractmethod
    def sessions(self) -> Iterator[dict[str, Any]]: ...

    @abstractmethod
    def messages(self, session_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def parts(self, session_id: str, message_id: str) -> list[dict[str, Any]]: ...


class _DbStore(_Store):
    def __init__(self, db_path: Path, snapshot_dir: Path) -> None:
        self.source_path = db_path
        self._snapshot_dir = snapshot_dir

    def _rows(self, conn: sqlite3.Connection, table: str, where: str = "", args: tuple = ()) -> list[dict]:
        if table not in table_names(conn):
            return []
        cols = column_names(conn, table)
        sql = f"SELECT * FROM {table}"  # noqa: S608 - table name is from a fixed allowlist
        if where:
            sql += f" WHERE {where}"
        out: list[dict[str, Any]] = []
        for row in conn.execute(sql, args).fetchall():
            record = {col: row[col] for col in cols}
            payload = record.pop("data", None)
            merged: dict[str, Any] = {}
            if isinstance(payload, str | bytes):
                try:
                    decoded = json.loads(payload)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    decoded = None
                if isinstance(decoded, dict):
                    merged.update(decoded)
            merged.update({k: v for k, v in record.items() if v is not None})
            out.append(merged)
        return out

    def sessions(self) -> Iterator[dict[str, Any]]:
        with read_only(self.source_path, self._snapshot_dir) as conn:
            yield from self._rows(conn, "session")

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        with read_only(self.source_path, self._snapshot_dir) as conn:
            rows = self._rows(conn, "message", "session_id = ?", (session_id,))
        return rows

    def parts(self, session_id: str, message_id: str) -> list[dict[str, Any]]:
        with read_only(self.source_path, self._snapshot_dir) as conn:
            rows = self._rows(conn, "part", "message_id = ?", (message_id,))
        return rows


class _JsonStore(_Store):
    def __init__(self, storage_root: Path) -> None:
        self.source_path = storage_root

    def sessions(self) -> Iterator[dict[str, Any]]:
        session_dir = self.source_path / "session"
        if not session_dir.exists():
            return
        for path in sorted(session_dir.rglob("*.json")):
            info = read_json(path)
            if isinstance(info, dict) and info.get("id"):
                info.setdefault("_source", str(path))
                yield info

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        message_dir = self.source_path / "message" / session_id
        out: list[dict[str, Any]] = []
        if not message_dir.exists():
            return out
        for path in sorted(message_dir.glob("*.json")):
            info = read_json(path)
            if isinstance(info, dict):
                info.setdefault("id", path.stem)
                info.setdefault("_source", str(path))
                out.append(info)
        return out

    def parts(self, session_id: str, message_id: str) -> list[dict[str, Any]]:
        # Layout moved between versions: part/<messageID>/ in most builds,
        # part/<sessionID>/<messageID>/ in some.
        candidates = [
            self.source_path / "part" / message_id,
            self.source_path / "part" / session_id / message_id,
        ]
        out: list[dict[str, Any]] = []
        for directory in candidates:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                info = read_json(path)
                if isinstance(info, dict):
                    info.setdefault("id", path.stem)
                    info.setdefault("_source", str(path))
                    out.append(info)
            break
        return out


class OpencodeProvider(Provider):
    id = "opencode"
    name = "opencode"

    def roots(self) -> list[Path]:
        data = self.settings.opencode_data
        return [data / "opencode.db", data / "storage", data / "project"]

    def _stores(self) -> list[_Store]:
        data = self.settings.opencode_data
        stores: list[_Store] = []
        db = data / "opencode.db"
        if db.exists():
            stores.append(_DbStore(db, self.snapshot_dir))
        storage = data / "storage"
        if storage.exists():
            stores.append(_JsonStore(storage))
        project_dir = data / "project"
        if project_dir.exists():
            for child in sorted(project_dir.iterdir()):
                nested = child / "storage"
                if nested.exists():
                    stores.append(_JsonStore(nested))
                nested_db = child / "opencode.db"
                if nested_db.exists():
                    stores.append(_DbStore(nested_db, self.snapshot_dir))
        return stores

    def detect(self):
        status = super().detect()
        stores = self._stores()
        status.detected = bool(stores)
        status.roots = [str(store.source_path) for store in stores]
        if stores:
            kinds = {"sqlite" if isinstance(s, _DbStore) else "json-files" for s in stores}
            status.note = f"storage: {', '.join(sorted(kinds))}"
        else:
            status.note = f"not found under {self.settings.opencode_data}"
            status.session_count = None
        return status

    # -- discovery ---------------------------------------------------------
    def iter_sessions(self) -> Iterator[SessionSummary]:
        for store in self._stores():
            try:
                infos = list(store.sessions())
            except (sqlite3.Error, OSError):
                continue
            for info in infos:
                yield self._summary(store, info)

    def _summary(self, store: _Store, info: dict[str, Any]) -> SessionSummary:
        source = Path(info.get("_source") or store.source_path)
        mtime, size = stat_of(source)
        session_id = str(info.get("id"))
        cwd = info.get("directory") or info.get("path") or info.get("cwd")
        parent = info.get("parentID") or info.get("parent_id")
        time_info = as_dict(info.get("time"))
        created = timeutil.coerce(time_info.get("created")) or timeutil.coerce(info.get("time_created"))
        updated = timeutil.coerce(time_info.get("updated")) or timeutil.coerce(info.get("time_updated"))
        return SessionSummary(
            provider=self.id,
            id=session_id,
            uid=self.uid(session_id),
            title=info.get("title"),
            cwd=cwd if isinstance(cwd, str) else None,
            project=project_name(cwd if isinstance(cwd, str) else None),
            created_at=created,
            updated_at=updated or created,
            model=info.get("model"),
            parent_uid=self.uid(str(parent)) if parent else None,
            kind="subagent" if parent else "main",
            source_path=str(source),
            source_mtime=mtime,
            source_size=size,
        )

    def _locate(self, session_id: str) -> tuple[_Store, dict[str, Any]]:
        for store in self._stores():
            for info in store.sessions():
                if str(info.get("id")) == session_id:
                    return store, info
        raise SessionNotFound(session_id)

    # -- loading -----------------------------------------------------------
    def load_session(self, session_id: str) -> Session:
        store, info = self._locate(session_id)
        summary = self._summary(store, info)
        warnings: list[Warning_] = []
        messages: list[Message] = []
        tokens: TokenUsage | None = None
        cost = 0.0
        model: str | None = summary.model
        counter = _Counter()

        raw_messages = store.messages(session_id)
        raw_messages.sort(key=lambda m: (_message_sort_key(m), str(m.get("id"))))
        for raw in raw_messages:
            message_id = str(raw.get("id"))
            try:
                raw_parts = store.parts(session_id, message_id)
            except (sqlite3.Error, OSError) as exc:
                warnings.append(Warning_(message=f"parts unreadable for {message_id}: {exc}"))
                raw_parts = []
            raw_parts.sort(key=lambda p: str(p.get("id")))
            message = _build_message(raw, raw_parts, counter, warnings)
            if message.tokens:
                tokens = message.tokens if tokens is None else tokens.merged(message.tokens)
            cost += message.cost or 0.0
            model = message.model or model
            messages.append(message)

        summary = summary.model_copy(
            update={
                "message_count": len(messages),
                "title": summary.title or derive_title(messages),
                "model": model,
                "tokens": tokens,
                "cost": cost or None,
            }
        )
        return Session(
            summary=summary,
            messages=messages,
            warnings=warnings,
            metadata={
                k: v
                for k, v in {
                    "agent": info.get("agent"),
                    "mode": info.get("mode"),
                    "share_url": info.get("share_url") or info.get("shareURL"),
                    "projectID": info.get("projectID"),
                }.items()
                if v is not None
            },
        )

    def raw_records(self, session_id: str) -> Iterator[dict[str, Any]]:
        store, info = self._locate(session_id)
        yield {"kind": "session", "record": _strip_private(info)}
        for raw in store.messages(session_id):
            message_id = str(raw.get("id"))
            yield {"kind": "message", "record": _strip_private(raw)}
            for part in store.parts(session_id, message_id):
                yield {"kind": "part", "message_id": message_id, "record": _strip_private(part)}

    def resume_command(self, session_id: str) -> str | None:
        return f"opencode --session {session_id}"


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"


def _strip_private(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def _message_sort_key(raw: dict[str, Any]) -> float:
    when = timeutil.coerce(as_dict(raw.get("time")).get("created")) or timeutil.coerce(
        raw.get("time_created")
    )
    return when.timestamp() if when else 0.0


def _tokens_from(raw: Any) -> TokenUsage | None:
    data = as_dict(raw)
    if not data:
        return None
    return TokenUsage(
        input=data.get("input"),
        output=data.get("output"),
        cache_read=as_dict(data.get("cache")).get("read") or data.get("cacheRead"),
        cache_write=as_dict(data.get("cache")).get("write") or data.get("cacheWrite"),
        reasoning=data.get("reasoning"),
    )


def _build_message(
    raw: dict[str, Any],
    raw_parts: list[dict[str, Any]],
    counter: _Counter,
    warnings: list[Warning_],
) -> Message:
    role = raw.get("role") if raw.get("role") in ("user", "assistant", "system", "tool") else "assistant"
    time_info = as_dict(raw.get("time"))
    error = as_dict(raw.get("error"))
    message = Message(
        id=str(raw.get("id")),
        role=role,  # type: ignore[arg-type]
        created_at=timeutil.coerce(time_info.get("created")) or timeutil.coerce(raw.get("time_created")),
        tokens=_tokens_from(raw.get("tokens")),
        cost=raw.get("cost") if isinstance(raw.get("cost"), int | float) else None,
        model=raw.get("modelID") or raw.get("model"),
        error=error.get("message") or (error.get("name") if error else None),
    )
    for raw_part in raw_parts:
        try:
            part = _build_part(raw_part, counter)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(Warning_(message=f"part {raw_part.get('id')}: {type(exc).__name__}: {exc}"))
            continue
        if part is not None:
            message.parts.append(part)
    if message.error and not any(p.type == "error" for p in message.parts):
        message.parts.append(ErrorPart(id=counter.next("p"), message=message.error))
    return message


def _build_part(raw: dict[str, Any], counter: _Counter) -> Any:
    part_id = str(raw.get("id") or counter.next("p"))
    loc = Locator(source=str(raw.get("_source") or ""), key=part_id) if raw.get("_source") else None
    kind = raw.get("type")

    if kind == "text":
        text = raw.get("text") or ""
        return TextPart(id=part_id, text=text, locator=loc, raw=raw) if text else None

    if kind == "reasoning":
        text = raw.get("text") or ""
        return ReasoningPart(id=part_id, text=text, locator=loc, raw=raw) if text else None

    if kind == "tool":
        state = as_dict(raw.get("state"))
        status = state.get("status") or "completed"
        time_state = as_dict(state.get("time"))
        return ToolPart(
            id=part_id,
            name=str(raw.get("tool") or raw.get("name") or "tool"),
            call_id=raw.get("callID") or raw.get("call_id"),
            input=state.get("input"),
            output=_as_text(state.get("output")),
            status=status if status in ("pending", "running", "completed", "error") else "completed",
            error=state.get("error"),
            title=state.get("title"),
            started_at=timeutil.coerce(time_state.get("start")),
            ended_at=timeutil.coerce(time_state.get("end")),
            metadata=as_dict(state.get("metadata")) or None,
            locator=loc,
            raw=raw,
        )

    if kind == "file":
        return FilePart(
            id=part_id,
            path=raw.get("filename") or raw.get("path") or raw.get("url"),
            mime=raw.get("mime"),
            text=raw.get("text"),
            data_url=raw.get("url") if str(raw.get("url", "")).startswith("data:") else None,
            locator=loc,
            raw=raw,
        )

    if kind in ("step-start", "step-finish"):
        return StepPart(
            id=part_id,
            phase="start" if kind == "step-start" else "finish",
            tokens=_tokens_from(raw.get("tokens")),
            cost=raw.get("cost") if isinstance(raw.get("cost"), int | float) else None,
            locator=loc,
            raw=raw,
        )

    if kind == "snapshot":
        return SnapshotPart(id=part_id, ref=raw.get("snapshot") or raw.get("hash"), locator=loc, raw=raw)

    if kind == "patch":
        files = []
        for entry in as_list(raw.get("files")):
            if isinstance(entry, str):
                files.append(PatchFile(path=entry))
            elif isinstance(entry, dict):
                files.append(
                    PatchFile(
                        path=str(entry.get("path") or entry.get("file") or "?"),
                        status=entry.get("status"),
                        diff=entry.get("diff") or entry.get("patch"),
                        additions=entry.get("additions"),
                        deletions=entry.get("deletions"),
                    )
                )
        return PatchPart(
            id=part_id,
            files=files,
            unified_diff=raw.get("diff") or raw.get("unified_diff"),
            locator=loc,
            raw=raw,
        )

    if kind in ("agent", "subtask"):
        child = raw.get("targetSessionID") or raw.get("childSessionID") or raw.get("subSessionID")
        return SubtaskPart(
            id=part_id,
            session_uid=f"opencode:{child}" if child else None,
            title=raw.get("name") or raw.get("description") or raw.get("title"),
            agent=raw.get("agent") or raw.get("name"),
            locator=loc,
            raw=raw,
        )

    if kind == "compaction":
        return CompactionPart(id=part_id, text=raw.get("summary") or raw.get("text"), locator=loc, raw=raw)

    if kind == "todo":
        items = [
            TodoItem(content=str(as_dict(i).get("content") or i), status=as_dict(i).get("status"))
            for i in as_list(raw.get("todos") or raw.get("items"))
        ]
        return TodoPart(id=part_id, items=items, locator=loc, raw=raw)

    return UnknownPart(id=part_id, kind=str(kind or "part"), data=raw, locator=loc, raw=raw)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return str(value)
