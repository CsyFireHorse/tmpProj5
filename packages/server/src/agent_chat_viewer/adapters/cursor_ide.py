"""Cursor IDE (Composer / Agent panel) adapter.

Content lives in ``<UserRoot>/globalStorage/state.vscdb``, in a
``cursorDiskKV(key, value)`` table:

* ``composerData:<composerId>``          -> thread metadata + message order
* ``bubbleId:<composerId>:<bubbleId>``   -> one message
* ``checkpointId:<composerId>:<id>``     -> workspace snapshot for a turn

Which workspace a thread belongs to is only recorded per workspace, in
``workspaceStorage/<hash>/state.vscdb``; roughly a fifth of threads match no
workspace at all and are still listed, just without a cwd.

The schema version (``_v``) churns across releases, so every field read here is
optional and a missing one never fails the session.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..models import (
    Locator,
    Message,
    ReasoningPart,
    Session,
    SessionSummary,
    SnapshotPart,
    TextPart,
    TokenUsage,
    ToolPart,
    UnknownPart,
    Warning_,
)
from ..util import timeutil
from ..util.jsonl import as_dict, as_list, loads_maybe, read_json
from ..util.sqlite_ro import read_only, table_names
from ..util.text import derive_title, truncate
from .base import Provider, SessionNotFound, project_name, stat_of

LEGACY_CHAT_KEY = "workbench.panel.aichat.view.aichat.chatdata"


class CursorIdeProvider(Provider):
    id = "cursor-ide"
    name = "Cursor IDE"

    def roots(self) -> list[Path]:
        return [self.global_db, self.settings.cursor_user_root / "workspaceStorage"]

    @property
    def global_db(self) -> Path:
        return self.settings.cursor_user_root / "globalStorage" / "state.vscdb"

    # -- workspace mapping -------------------------------------------------
    def _workspace_map(self) -> tuple[dict[str, str], list[tuple[Path, str | None]]]:
        """Return ``composerId -> cwd`` plus the list of workspace databases."""
        mapping: dict[str, str] = {}
        databases: list[tuple[Path, str | None]] = []
        root = self.settings.cursor_user_root / "workspaceStorage"
        if not root.exists():
            return mapping, databases
        for directory in sorted(root.iterdir()):
            db = directory / "state.vscdb"
            if not db.exists():
                continue
            cwd = _workspace_folder(directory / "workspace.json")
            databases.append((db, cwd))
            try:
                with read_only(db, self.snapshot_dir) as conn:
                    if "ItemTable" not in table_names(conn):
                        continue
                    row = conn.execute(
                        "SELECT value FROM ItemTable WHERE key = ?", ("composer.composerData",)
                    ).fetchone()
            except sqlite3.Error:
                continue
            if not row:
                continue
            data = as_dict(loads_maybe(row[0]))
            for entry in as_list(data.get("allComposers")):
                composer_id = as_dict(entry).get("composerId")
                if composer_id and cwd:
                    mapping[str(composer_id)] = cwd
        return mapping, databases

    # -- discovery ---------------------------------------------------------
    def iter_sessions(self) -> Iterator[SessionSummary]:
        mapping, databases = self._workspace_map()
        yield from self._global_sessions(mapping)
        for db, cwd in databases:
            yield from self._legacy_sessions(db, cwd)

    def _global_sessions(self, mapping: dict[str, str]) -> Iterator[SessionSummary]:
        db = self.global_db
        if not db.exists():
            return
        mtime, size = stat_of(db)
        try:
            with read_only(db, self.snapshot_dir) as conn:
                if "cursorDiskKV" not in table_names(conn):
                    return
                rows = conn.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
                ).fetchall()
        except sqlite3.Error:
            return
        for key, value in rows:
            data = as_dict(loads_maybe(value))
            if not data:
                continue
            composer_id = str(data.get("composerId") or key.split(":", 1)[-1])
            cwd = mapping.get(composer_id)
            headers = as_list(data.get("fullConversationHeadersOnly")) or as_list(data.get("conversation"))
            yield SessionSummary(
                provider=self.id,
                id=composer_id,
                uid=self.uid(composer_id),
                title=data.get("name") or None,
                cwd=cwd,
                project=project_name(cwd),
                created_at=timeutil.from_epoch(data.get("createdAt")),
                updated_at=timeutil.from_epoch(data.get("lastUpdatedAt")),
                message_count=len(headers) or None,
                model=as_dict(data.get("latestModel")).get("modelName") or data.get("model"),
                source_path=str(db),
                source_mtime=mtime,
                source_size=size,
            )

    def _legacy_sessions(self, db: Path, cwd: str | None) -> Iterator[SessionSummary]:
        """Pre-composer Cursor kept chats inside the workspace database."""
        try:
            with read_only(db, self.snapshot_dir) as conn:
                if "ItemTable" not in table_names(conn):
                    return
                row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (LEGACY_CHAT_KEY,)).fetchone()
        except sqlite3.Error:
            return
        if not row:
            return
        mtime, size = stat_of(db)
        data = as_dict(loads_maybe(row[0]))
        workspace_hash = db.parent.name
        for tab in as_list(data.get("tabs")):
            tab_data = as_dict(tab)
            tab_id = str(tab_data.get("tabId") or tab_data.get("id") or "")
            if not tab_id:
                continue
            session_id = f"legacy:{workspace_hash}:{tab_id}"
            bubbles = as_list(tab_data.get("bubbles"))
            yield SessionSummary(
                provider=self.id,
                id=session_id,
                uid=self.uid(session_id),
                title=tab_data.get("chatTitle") or tab_data.get("title"),
                cwd=cwd,
                project=project_name(cwd),
                created_at=timeutil.coerce(tab_data.get("lastSendTime")),
                updated_at=timeutil.coerce(tab_data.get("lastSendTime")) or timeutil.from_epoch(mtime),
                message_count=len(bubbles) or None,
                source_path=str(db),
                source_mtime=mtime,
                source_size=size,
            )

    # -- loading -----------------------------------------------------------
    def load_session(self, session_id: str) -> Session:
        if session_id.startswith("legacy:"):
            return self._load_legacy(session_id)
        return self._load_composer(session_id)

    def _load_composer(self, composer_id: str) -> Session:
        db = self.global_db
        if not db.exists():
            raise SessionNotFound(composer_id)
        mapping, _ = self._workspace_map()
        warnings: list[Warning_] = []
        with read_only(db, self.snapshot_dir) as conn:
            row = conn.execute(
                "SELECT value FROM cursorDiskKV WHERE key = ?", (f"composerData:{composer_id}",)
            ).fetchone()
            if not row:
                raise SessionNotFound(composer_id)
            data = as_dict(loads_maybe(row[0]))
            bubbles = {
                key.rsplit(":", 1)[-1]: as_dict(loads_maybe(value))
                for key, value in conn.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?",
                    (f"bubbleId:{composer_id}:%",),
                ).fetchall()
            }
            checkpoints = [
                key.rsplit(":", 1)[-1]
                for (key,) in conn.execute(
                    "SELECT key FROM cursorDiskKV WHERE key LIKE ?",
                    (f"checkpointId:{composer_id}:%",),
                ).fetchall()
            ]

        headers = as_list(data.get("fullConversationHeadersOnly"))
        if not headers:
            # Older `_v` inlines the conversation instead of pointing at bubbles.
            headers = [
                {"bubbleId": as_dict(b).get("bubbleId") or f"inline-{i}", "type": as_dict(b).get("type")}
                for i, b in enumerate(as_list(data.get("conversation")))
            ]
            for i, inline in enumerate(as_list(data.get("conversation"))):
                bubble = as_dict(inline)
                bubbles.setdefault(str(bubble.get("bubbleId") or f"inline-{i}"), bubble)

        counter = _Counter()
        messages: list[Message] = []
        tokens: TokenUsage | None = None
        created = timeutil.from_epoch(data.get("createdAt"))
        for position, header in enumerate(headers):
            head = as_dict(header)
            bubble_id = str(head.get("bubbleId") or "")
            bubble = bubbles.get(bubble_id)
            if bubble is None:
                warnings.append(
                    Warning_(
                        message=f"bubble {bubble_id} referenced but missing from globalStorage",
                        locator=Locator(source=str(db), key=f"bubbleId:{composer_id}:{bubble_id}"),
                    )
                )
                continue
            message = _bubble_to_message(
                bubble,
                bubble_id or f"b{position}",
                head.get("type"),
                counter,
                Locator(source=str(db), key=f"bubbleId:{composer_id}:{bubble_id}"),
                fallback_time=created if position == 0 else None,
            )
            if message.tokens:
                tokens = message.tokens if tokens is None else tokens.merged(message.tokens)
            if message.parts:
                messages.append(message)

        cwd = mapping.get(composer_id)
        mtime, size = stat_of(db)
        summary = SessionSummary(
            provider=self.id,
            id=composer_id,
            uid=self.uid(composer_id),
            title=data.get("name") or derive_title(messages),
            cwd=cwd,
            project=project_name(cwd),
            created_at=created,
            updated_at=timeutil.from_epoch(data.get("lastUpdatedAt")),
            message_count=len(messages),
            model=as_dict(data.get("latestModel")).get("modelName") or data.get("model"),
            tokens=tokens,
            source_path=str(db),
            source_mtime=mtime,
            source_size=size,
            parse_status="partial" if warnings else "ok",
        )
        notes = []
        if cwd is None:
            notes.append("No workspace is linked to this thread, so its working directory is unknown.")
        return Session(
            summary=summary,
            messages=messages,
            warnings=warnings,
            notes=notes,
            metadata={
                k: v
                for k, v in {
                    "schema_version": data.get("_v"),
                    "status": data.get("status"),
                    "isAgentic": data.get("isAgentic"),
                    "unifiedMode": data.get("unifiedMode"),
                    "checkpoints": len(checkpoints) or None,
                    "summary": as_dict(data.get("latestConversationSummary")).get("summary"),
                }.items()
                if v is not None
            },
        )

    def _load_legacy(self, session_id: str) -> Session:
        _, workspace_hash, tab_id = session_id.split(":", 2)
        db = self.settings.cursor_user_root / "workspaceStorage" / workspace_hash / "state.vscdb"
        if not db.exists():
            raise SessionNotFound(session_id)
        cwd = _workspace_folder(db.parent / "workspace.json")
        with read_only(db, self.snapshot_dir) as conn:
            row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (LEGACY_CHAT_KEY,)).fetchone()
        if not row:
            raise SessionNotFound(session_id)
        data = as_dict(loads_maybe(row[0]))
        tab = next(
            (t for t in (as_dict(x) for x in as_list(data.get("tabs"))) if str(t.get("tabId")) == tab_id),
            None,
        )
        if tab is None:
            raise SessionNotFound(session_id)

        counter = _Counter()
        messages: list[Message] = []
        for index, entry in enumerate(as_list(tab.get("bubbles"))):
            bubble = as_dict(entry)
            text = bubble.get("text") or ""
            role = "user" if bubble.get("type") == "user" else "assistant"
            if not text:
                continue
            messages.append(
                Message(
                    id=f"{tab_id}-{index}",
                    role=role,  # type: ignore[arg-type]
                    parts=[TextPart(id=counter.next("p"), text=text, raw=bubble)],
                )
            )
        mtime, size = stat_of(db)
        summary = SessionSummary(
            provider=self.id,
            id=session_id,
            uid=self.uid(session_id),
            title=tab.get("chatTitle") or derive_title(messages),
            cwd=cwd,
            project=project_name(cwd),
            updated_at=timeutil.from_epoch(mtime),
            message_count=len(messages),
            source_path=str(db),
            source_mtime=mtime,
            source_size=size,
        )
        return Session(
            summary=summary,
            messages=messages,
            notes=["Legacy pre-composer chat, read from the workspace database."],
        )

    def raw_records(self, session_id: str) -> Iterator[dict[str, Any]]:
        if session_id.startswith("legacy:"):
            session = self._load_legacy(session_id)
            for message in session.messages:
                for part in message.parts:
                    yield {"message_id": message.id, "record": part.raw}
            return
        db = self.global_db
        with read_only(db, self.snapshot_dir) as conn:
            for key, value in conn.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key = ? OR key LIKE ? ORDER BY key",
                (f"composerData:{session_id}", f"bubbleId:{session_id}:%"),
            ).fetchall():
                yield {"key": key, "record": loads_maybe(value)}

    def resume_command(self, session_id: str) -> str | None:
        return None


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"


def _workspace_folder(workspace_json: Path) -> str | None:
    data = read_json(workspace_json)
    if not isinstance(data, dict):
        return None
    uri = data.get("folder") or data.get("workspace")
    if not isinstance(uri, str):
        return None
    if uri.startswith("file://"):
        return unquote(urlparse(uri).path)
    return uri


def _lexical_text(node: Any) -> str:
    """Pull plain text out of a Lexical editor state tree."""
    chunks: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop(0)
        if isinstance(current, dict):
            text = current.get("text")
            if isinstance(text, str):
                chunks.append(text)
            children = current.get("children") or current.get("root")
            if children is not None:
                stack.insert(0, children)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                stack.insert(index, child)
    return "".join(chunks)


def _bubble_to_message(
    bubble: dict[str, Any],
    bubble_id: str,
    header_type: Any,
    counter: _Counter,
    locator: Locator,
    fallback_time=None,
) -> Message:
    bubble_type = bubble.get("type", header_type)
    role = "user" if bubble_type == 1 else "assistant"
    message = Message(
        id=bubble_id,
        role=role,  # type: ignore[arg-type]
        created_at=timeutil.coerce(bubble.get("timestamp")) or fallback_time,
    )

    thinking = as_dict(bubble.get("thinking")).get("text")
    if thinking:
        message.parts.append(ReasoningPart(id=counter.next("p"), text=thinking, locator=locator))

    text = bubble.get("text") or bubble.get("rawText") or ""
    if not text:
        rich = loads_maybe(bubble.get("richText"))
        if rich:
            text = _lexical_text(rich)
    if text:
        message.parts.append(TextPart(id=counter.next("p"), text=text, locator=locator, raw=None))

    tool = as_dict(bubble.get("toolFormerData"))
    if tool:
        message.parts.append(_tool_part(tool, counter, locator))

    for block in as_list(bubble.get("codeBlocks")):
        block_data = as_dict(block)
        content = block_data.get("content") or block_data.get("code")
        if content:
            language = block_data.get("languageId") or ""
            uri = as_dict(block_data.get("uri")).get("path") or block_data.get("uri")
            header = f"`{uri}`\n" if isinstance(uri, str) else ""
            message.parts.append(
                TextPart(
                    id=counter.next("p"),
                    text=f"{header}```{language}\n{content}\n```",
                    locator=locator,
                )
            )

    checkpoint = bubble.get("checkpointId")
    if checkpoint:
        message.parts.append(SnapshotPart(id=counter.next("p"), ref=str(checkpoint), locator=locator))

    token_count = as_dict(bubble.get("tokenCount"))
    if token_count:
        message.tokens = TokenUsage(
            input=token_count.get("inputTokens"), output=token_count.get("outputTokens")
        )

    if not message.parts and bubble:
        message.parts.append(
            UnknownPart(id=counter.next("p"), kind="bubble", data=_compact(bubble), locator=locator)
        )
    return message


def _tool_part(tool: dict[str, Any], counter: _Counter, locator: Locator) -> ToolPart:
    result = tool.get("result")
    error = tool.get("error")
    status = "error" if error else ("completed" if result is not None else "pending")
    return ToolPart(
        id=counter.next("p"),
        name=str(tool.get("name") or tool.get("tool") or "tool"),
        call_id=tool.get("toolCallId"),
        input=loads_maybe(tool.get("rawArgs")) or tool.get("params"),
        output=result if isinstance(result, str) else (None if result is None else str(result)),
        status=status,  # type: ignore[arg-type]
        error=error if isinstance(error, str) else None,
        locator=locator,
    )


def _compact(bubble: dict[str, Any], limit: int = 4000) -> dict[str, Any]:
    """Drop the bulky context fields before handing a bubble to the raw viewer."""
    skip = {"context", "attachedFoldersNew", "attachedCodeChunks", "relevantFiles", "richText"}
    out: dict[str, Any] = {}
    for key, value in bubble.items():
        if key in skip:
            continue
        if isinstance(value, str) and len(value) > limit:
            out[key] = truncate(value, limit)
        else:
            out[key] = value
    return out
