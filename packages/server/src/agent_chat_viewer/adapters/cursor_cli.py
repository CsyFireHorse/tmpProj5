"""Cursor CLI (``cursor-agent``) adapter.

Layout::

    ~/.cursor/chats/<md5(workspace path)>/<session-uuid>/
        store.db              blobs(id, data) + meta(key, value)
        meta.json             title / createdAtMs / updatedAtMs
        prompt_history.json
    ~/.cursor/acp-sessions/<session-uuid>/store.db

Two things about this store are worth knowing before reading the code:

* **Ordering is approximate.** The authoritative order lives in protobuf
  "turn graph" blobs that are not decoded here. Messages are ordered by blob
  insertion order, refined by any timestamp the JSON blobs happen to carry.
  Sessions loaded from this provider carry a note saying so, and the UI shows
  it, rather than presenting a guess as fact.
* **The workspace directory name is an MD5 of the absolute path and cannot be
  reversed.** Candidate paths are hashed and matched instead; unmatched
  sessions are still listed with an unknown working directory.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..models import (
    FilePart,
    Locator,
    Message,
    ReasoningPart,
    Session,
    SessionSummary,
    TextPart,
    ToolPart,
    UnknownPart,
    Warning_,
)
from ..util import timeutil
from ..util.jsonl import as_dict, as_list, loads_maybe, read_json
from ..util.sqlite_ro import read_only, table_names
from ..util.text import derive_title
from .base import Provider, SessionNotFound, project_name, stat_of

ORDER_NOTE = (
    "Message order is approximate: Cursor CLI keeps the authoritative turn graph "
    "in protobuf blobs that this viewer does not decode yet."
)


class CursorCliProvider(Provider):
    id = "cursor-cli"
    name = "Cursor CLI"

    def roots(self) -> list[Path]:
        return [self.settings.cursor_home / "chats", self.settings.cursor_home / "acp-sessions"]

    def _session_dirs(self) -> Iterator[tuple[Path, str | None]]:
        """Yield ``(session_dir, workspace_hash)``."""
        chats = self.settings.cursor_home / "chats"
        if chats.exists():
            for bucket in sorted(chats.iterdir()):
                if not bucket.is_dir():
                    continue
                for session_dir in sorted(bucket.iterdir()):
                    if session_dir.is_dir() and (session_dir / "store.db").exists():
                        yield session_dir, bucket.name
        acp = self.settings.cursor_home / "acp-sessions"
        if acp.exists():
            for session_dir in sorted(acp.iterdir()):
                if session_dir.is_dir() and (session_dir / "store.db").exists():
                    yield session_dir, None

    # -- discovery ---------------------------------------------------------
    def iter_sessions(self) -> Iterator[SessionSummary]:
        reverse = self._workspace_index()
        for session_dir, workspace_hash in self._session_dirs():
            yield self._summary(session_dir, workspace_hash, reverse)

    def _summary(
        self, session_dir: Path, workspace_hash: str | None, reverse: dict[str, str]
    ) -> SessionSummary:
        store = session_dir / "store.db"
        mtime, size = stat_of(store)
        meta = as_dict(read_json(session_dir / "meta.json"))
        agent = self._agent_record(store)
        cwd = reverse.get(workspace_hash or "")
        session_id = session_dir.name
        return SessionSummary(
            provider=self.id,
            id=session_id,
            uid=self.uid(session_id),
            title=meta.get("title") or agent.get("name"),
            cwd=cwd,
            project=project_name(cwd) or (f"md5:{workspace_hash[:8]}" if workspace_hash else None),
            created_at=timeutil.coerce(meta.get("createdAtMs") or agent.get("createdAt")),
            updated_at=timeutil.coerce(meta.get("updatedAtMs")) or timeutil.from_epoch(mtime),
            model=agent.get("lastUsedModel"),
            source_path=str(store),
            source_mtime=mtime,
            source_size=size,
        )

    def _agent_record(self, store: Path) -> dict[str, Any]:
        """``meta`` table, key ``"0"``, holds a hex-encoded JSON agent record."""
        try:
            with read_only(store, self.snapshot_dir) as conn:
                if "meta" not in table_names(conn):
                    return {}
                row = conn.execute("SELECT value FROM meta WHERE key = '0'").fetchone()
        except sqlite3.Error:
            return {}
        if not row:
            return {}
        return as_dict(_decode_hex_json(row[0]))

    def _find(self, session_id: str) -> tuple[Path, str | None]:
        for session_dir, workspace_hash in self._session_dirs():
            if session_dir.name == session_id:
                return session_dir, workspace_hash
        raise SessionNotFound(session_id)

    # -- workspace path recovery ------------------------------------------
    def _candidate_paths(self) -> list[str]:
        candidates: set[str] = set()
        cursor_home = self.settings.cursor_home

        # Cursor writes one base64url-encoded absolute path per agent hook dir.
        hooks = cursor_home / "agent-hooks"
        if hooks.exists():
            for entry in hooks.iterdir():
                decoded = _b64_path(entry.name)
                if decoded:
                    candidates.add(decoded)

        for root in self.settings.extra_project_roots:
            candidates.add(str(root))
            if root.exists():
                for child in root.iterdir():
                    if child.is_dir():
                        candidates.add(str(child))

        candidates.add(str(Path.cwd()))
        for binding in _read_bindings(self.settings.state_dir):
            candidates.add(binding)
        return sorted(candidates)

    def _workspace_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for path in self._candidate_paths():
            for variant in {path, path.rstrip("/")}:
                index[hashlib.md5(variant.encode()).hexdigest()] = path
        return index

    def bind_workspace(self, workspace_hash: str, path: str) -> bool:
        """Let the user attach a path to a bucket the reverse index missed."""
        digests = {hashlib.md5(variant.encode()).hexdigest() for variant in (path, path.rstrip("/"))}
        if workspace_hash not in digests:
            return False
        _append_binding(self.settings.state_dir, path)
        return True

    # -- loading -----------------------------------------------------------
    def load_session(self, session_id: str) -> Session:
        session_dir, workspace_hash = self._find(session_id)
        summary = self._summary(session_dir, workspace_hash, self._workspace_index())
        store = session_dir / "store.db"
        warnings: list[Warning_] = []
        counter = _Counter()

        blobs, skipped = _read_blobs(store, self.snapshot_dir, warnings)
        records = [record for record in blobs if isinstance(record.value, dict | list)]
        messages = _build_messages(records, counter, str(store), warnings)

        prompts = read_json(session_dir / "prompt_history.json")
        if not messages and isinstance(prompts, list):
            # Blob decoding failed entirely; at minimum show what the user typed.
            warnings.append(Warning_(message="no JSON message blobs decoded; showing prompt history only"))
            messages = [
                Message(id=f"prompt-{i}", role="user", parts=[TextPart(id=counter.next("p"), text=str(p))])
                for i, p in enumerate(prompts)
                if p
            ]

        summary = summary.model_copy(
            update={
                "message_count": len(messages),
                "title": summary.title or derive_title(messages),
                "parse_status": "partial" if warnings else "ok",
            }
        )
        notes = [ORDER_NOTE]
        if summary.cwd is None and workspace_hash:
            notes.append(
                f"Workspace unknown: the directory name is md5 {workspace_hash} and cannot be reversed. "
                "Bind a path from the session panel to resolve it."
            )
        if skipped:
            notes.append(f"{skipped} non-JSON blob(s) (protobuf turn graph) were not decoded.")
        return Session(
            summary=summary,
            messages=messages,
            warnings=warnings,
            notes=notes,
            metadata={
                k: v
                for k, v in {
                    "workspace_hash": workspace_hash,
                    "prompt_count": len(prompts) if isinstance(prompts, list) else None,
                    "binary_blobs": skipped or None,
                    "order_confidence": "approximate",
                }.items()
                if v is not None
            },
        )

    def raw_records(self, session_id: str) -> Iterator[dict[str, Any]]:
        session_dir, _ = self._find(session_id)
        blobs, _ = _read_blobs(session_dir / "store.db", self.snapshot_dir, [])
        for record in blobs:
            yield {"blob_id": record.blob_id, "rowid": record.rowid, "record": record.value}

    def resume_command(self, session_id: str) -> str | None:
        return f"cursor-agent --resume {session_id}"


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"


class _Blob:
    __slots__ = ("rowid", "blob_id", "value")

    def __init__(self, rowid: int, blob_id: str, value: Any) -> None:
        self.rowid = rowid
        self.blob_id = blob_id
        self.value = value


def _read_blobs(store: Path, snapshot_dir: Path, warnings: list[Warning_]) -> tuple[list[_Blob], int]:
    out: list[_Blob] = []
    skipped = 0
    try:
        with read_only(store, snapshot_dir) as conn:
            if "blobs" not in table_names(conn):
                warnings.append(Warning_(message="store.db has no 'blobs' table"))
                return out, 0
            rows = conn.execute("SELECT rowid, id, data FROM blobs ORDER BY rowid").fetchall()
    except sqlite3.Error as exc:
        warnings.append(Warning_(message=f"store.db unreadable: {exc}"))
        return out, 0

    for rowid, blob_id, data in rows:
        value = _decode_blob(data)
        if value is None:
            skipped += 1
            continue
        out.append(_Blob(rowid, str(blob_id), value))
    return out, skipped


def _decode_blob(data: Any) -> Any:
    if isinstance(data, memoryview):
        data = bytes(data)
    if isinstance(data, bytes | bytearray):
        if data[:1] not in (b"{", b"["):
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    if isinstance(data, str):
        return loads_maybe(data) if data[:1] in ("{", "[") else None
    return None


def _decode_hex_json(value: Any) -> Any:
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes | bytearray):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[:1] in ("{", "["):
        return loads_maybe(text)
    try:
        return json.loads(bytes.fromhex(text).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _iter_message_dicts(value: Any) -> Iterator[dict[str, Any]]:
    """A blob may be one message, a list of them, or an envelope containing them."""
    if isinstance(value, list):
        for entry in value:
            yield from _iter_message_dicts(entry)
        return
    data = as_dict(value)
    if not data:
        return
    if "messages" in data and isinstance(data["messages"], list):
        for entry in data["messages"]:
            yield from _iter_message_dicts(entry)
        return
    if data.get("role") or data.get("content") is not None or data.get("text"):
        yield data


def _build_messages(
    blobs: list[_Blob], counter: _Counter, source: str, warnings: list[Warning_]
) -> list[Message]:
    entries: list[tuple[float, int, dict[str, Any], str]] = []
    for blob in blobs:
        for record in _iter_message_dicts(blob.value):
            when = timeutil.coerce(record.get("timestamp") or record.get("createdAt") or record.get("time"))
            entries.append((when.timestamp() if when else 0.0, blob.rowid, record, blob.blob_id))

    # Insertion order is the primary signal; timestamps only refine it when the
    # whole set carries them.
    if entries and all(entry[0] > 0 for entry in entries):
        entries.sort(key=lambda e: (e[0], e[1]))
    else:
        entries.sort(key=lambda e: e[1])

    messages: list[Message] = []
    tool_index: dict[str, ToolPart] = {}
    for _when, rowid, record, blob_id in entries:
        role = record.get("role") or ("user" if record.get("type") == "user_message" else "assistant")
        if role not in ("user", "assistant", "system", "tool"):
            role = "assistant"
        locator = Locator(source=source, key=blob_id)
        message = Message(
            id=f"{rowid}-{blob_id[:8]}",
            role=role,  # type: ignore[arg-type]
            created_at=timeutil.coerce(record.get("timestamp") or record.get("createdAt")),
        )
        content = record.get("content")
        if content is None:
            content = record.get("text") or record.get("parts")
        message.parts.extend(_content_parts(content, counter, locator, tool_index, warnings))
        if not message.parts:
            continue
        # A standalone tool result is folded into the call it answers.
        if role == "tool" and _fold_tool_result(message, tool_index):
            continue
        messages.append(message)
    return messages


def _content_parts(
    content: Any,
    counter: _Counter,
    locator: Locator,
    tool_index: dict[str, ToolPart],
    warnings: list[Warning_],
) -> list[Any]:
    parts: list[Any] = []
    if content is None:
        return parts
    if isinstance(content, str):
        return [TextPart(id=counter.next("p"), text=content, locator=locator)] if content else []
    for entry in as_list(content):
        if isinstance(entry, str):
            if entry:
                parts.append(TextPart(id=counter.next("p"), text=entry, locator=locator))
            continue
        data = as_dict(entry)
        if not data:
            continue
        kind = data.get("type") or ("text" if data.get("text") else "")
        if kind in ("text", "output_text", "input_text"):
            text = data.get("text") or ""
            if text:
                parts.append(TextPart(id=counter.next("p"), text=text, locator=locator))
        elif kind in ("thinking", "reasoning"):
            text = data.get("text") or data.get("thinking") or ""
            if text:
                parts.append(ReasoningPart(id=counter.next("p"), text=text, locator=locator))
        elif kind in ("tool_use", "tool_call", "function_call"):
            call_id = str(data.get("id") or data.get("toolCallId") or data.get("call_id") or "")
            part = ToolPart(
                id=counter.next("p"),
                name=str(data.get("name") or "tool"),
                call_id=call_id or None,
                input=loads_maybe(data.get("input") or data.get("arguments") or data.get("args")),
                status="pending",
                locator=locator,
                raw=data,
            )
            if call_id:
                tool_index[call_id] = part
            parts.append(part)
        elif kind in ("tool_result", "tool_output", "function_call_output"):
            call_id = str(data.get("tool_use_id") or data.get("toolCallId") or data.get("call_id") or "")
            output = data.get("content") or data.get("output") or data.get("result")
            target = tool_index.get(call_id)
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
            if target is not None:
                target.output = text
                target.status = "error" if data.get("is_error") else "completed"
            else:
                parts.append(
                    ToolPart(
                        id=counter.next("p"),
                        name=str(data.get("name") or "tool"),
                        call_id=call_id or None,
                        output=text,
                        status="error" if data.get("is_error") else "completed",
                        locator=locator,
                        raw=data,
                    )
                )
        elif kind == "image":
            parts.append(FilePart(id=counter.next("p"), mime="image/*", locator=locator, raw=data))
        else:
            parts.append(
                UnknownPart(id=counter.next("p"), kind=str(kind or "content"), data=data, locator=locator)
            )
    return parts


def _fold_tool_result(message: Message, tool_index: dict[str, ToolPart]) -> bool:
    folded = False
    for part in list(message.parts):
        if part.type != "tool" or not part.call_id:
            continue
        target = tool_index.get(part.call_id)
        if target is not None and target is not part:
            target.output = part.output or target.output
            target.status = part.status
            folded = True
    return folded and all(p.type == "tool" for p in message.parts)


@lru_cache(maxsize=256)
def _b64_path(name: str) -> str | None:
    """Cursor encodes absolute paths as unpadded base64url directory names."""
    try:
        padded = name + "=" * (-len(name) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
    except Exception:
        return None
    return decoded if decoded.startswith("/") or ":" in decoded[:3] else None


def _bindings_file(state_dir: Path) -> Path:
    return state_dir / "workspace-bindings.json"


def _read_bindings(state_dir: Path) -> list[str]:
    data = read_json(_bindings_file(state_dir))
    return [str(p) for p in data] if isinstance(data, list) else []


def _append_binding(state_dir: Path, path: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    existing = _read_bindings(state_dir)
    if path in existing:
        return
    existing.append(path)
    _bindings_file(state_dir).write_text(json.dumps(existing, indent=2), encoding="utf-8")
