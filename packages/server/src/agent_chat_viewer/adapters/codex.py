"""Codex CLI adapter.

Reads ``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl``. Each line is a
``RolloutLine``: ``{timestamp, ordinal?, type, payload}``.

Two logs are interleaved in one file. ``response_item`` is the protocol log
(exactly what the model exchanged) and ``event_msg`` is the display log (what
the TUI replays). Most content appears in both, so the transcript is built from
``response_item`` only and ``event_msg`` contributes just what it uniquely
carries: token usage, turn diffs and errors.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..models import (
    ErrorPart,
    FilePart,
    Locator,
    Message,
    PatchPart,
    ReasoningPart,
    Session,
    SessionSummary,
    TextPart,
    TokenUsage,
    ToolPart,
    UnknownPart,
    Warning_,
)
from ..util import timeutil
from ..util.jsonl import as_dict, as_list, iter_jsonl
from ..util.text import derive_title, stringify
from .base import Provider, SessionNotFound, project_name, stat_of, walk_files

ROLLOUT_GLOB = "rollout-*.jsonl*"
HEADER_SCAN_LINES = 20


class CodexProvider(Provider):
    id = "codex"
    name = "Codex CLI"

    def roots(self) -> list[Path]:
        return [self.settings.codex_home / "sessions"]

    def _all_roots(self) -> list[Path]:
        home = self.settings.codex_home
        return [home / "sessions", home / "archived_sessions"]

    def _files(self) -> Iterator[Path]:
        for root in self._all_roots():
            yield from walk_files(root, ROLLOUT_GLOB)

    # -- discovery ---------------------------------------------------------
    def iter_sessions(self) -> Iterator[SessionSummary]:
        for path in self._files():
            summary = self._read_header(path)
            if summary is not None:
                yield summary

    def _read_header(self, path: Path) -> SessionSummary | None:
        meta: dict[str, Any] | None = None
        first_timestamp = None
        try:
            for _lineno, value, error in iter_jsonl(path, limit=HEADER_SCAN_LINES):
                if error or not isinstance(value, dict):
                    continue
                if first_timestamp is None:
                    first_timestamp = timeutil.coerce(value.get("timestamp"))
                if value.get("type") == "session_meta":
                    meta = as_dict(value.get("payload"))
                    break
        except (OSError, RuntimeError):
            return None
        if meta is None:
            # Not a session file (or unreadable); the format requires a header.
            return None

        mtime, size = stat_of(path)
        session_id = str(meta.get("id") or _id_from_filename(path))
        cwd = meta.get("cwd")
        git = as_dict(meta.get("git"))
        parent = meta.get("parent_thread_id") or _subagent_parent(meta.get("source"))
        return SessionSummary(
            provider=self.id,
            id=session_id,
            uid=self.uid(session_id),
            title=meta.get("agent_nickname") or None,
            cwd=cwd,
            project=project_name(cwd),
            created_at=timeutil.coerce(meta.get("timestamp")) or first_timestamp,
            updated_at=timeutil.from_epoch(mtime),
            model=meta.get("model") or meta.get("model_provider"),
            git_branch=git.get("branch"),
            parent_uid=self.uid(str(parent)) if parent else None,
            kind="subagent" if parent else "main",
            source_path=str(path),
            source_mtime=mtime,
            source_size=size,
        )

    def _find(self, session_id: str) -> Path:
        for path in self._files():
            if session_id in path.name:
                return path
        for path in self._files():
            summary = self._read_header(path)
            if summary and summary.id == session_id:
                return path
        raise SessionNotFound(session_id)

    # -- loading -----------------------------------------------------------
    def load_session(self, session_id: str) -> Session:
        path = self._find(session_id)
        summary = self._read_header(path)
        if summary is None:  # pragma: no cover - _find guarantees a header
            raise SessionNotFound(session_id)
        return _parse_rollout(path, summary)

    def raw_records(self, session_id: str) -> Iterator[dict[str, Any]]:
        path = self._find(session_id)
        for lineno, value, error in iter_jsonl(path):
            yield {"line": lineno, "record": value, "error": error}

    def resume_command(self, session_id: str) -> str | None:
        return f"codex resume {session_id}"


def _id_from_filename(path: Path) -> str:
    stem = path.name
    for suffix in (".jsonl", ".gz", ".zst", ".xz"):
        stem = stem.removesuffix(suffix)
    parts = stem.split("-")
    if len(parts) >= 5:
        return "-".join(parts[-5:])
    return stem


def _subagent_parent(source: Any) -> str | None:
    """``source`` is ``"cli"`` for top-level runs, or an object for subagents."""
    spawn = as_dict(as_dict(source).get("subagent")).get("thread_spawn")
    return as_dict(spawn).get("parent_thread_id") or as_dict(spawn).get("parent_id")


class _Builder:
    """Accumulates protocol items into user/assistant messages."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.messages: list[Message] = []
        self.warnings: list[Warning_] = []
        self.tools: dict[str, ToolPart] = {}
        self._current: Message | None = None
        self._seq = 0

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def loc(self, line: int) -> Locator:
        return Locator(source=self.source, line=line)

    def flush(self) -> None:
        self._current = None

    def assistant(self, when) -> Message:
        if self._current is None or self._current.role != "assistant":
            self._current = Message(id=self.next_id("m"), role="assistant", created_at=when)
            self.messages.append(self._current)
        return self._current

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        self._current = message if message.role == "assistant" else None


def _parse_rollout(path: Path, summary: SessionSummary) -> Session:
    builder = _Builder(str(path))
    notes: list[str] = []
    metadata: dict[str, Any] = {}
    tokens: TokenUsage | None = None
    model: str | None = summary.model
    parse_errors = 0

    for lineno, value, error in iter_jsonl(path):
        if error:
            parse_errors += 1
            builder.warnings.append(Warning_(message=error, locator=builder.loc(lineno)))
            continue
        if not isinstance(value, dict):
            continue
        kind = value.get("type")
        payload = value.get("payload")
        when = timeutil.coerce(value.get("timestamp"))

        if kind == "session_meta":
            meta = as_dict(payload)
            instructions = as_dict(meta.get("base_instructions")).get("text")
            metadata.update(
                {
                    "originator": meta.get("originator"),
                    "cli_version": meta.get("cli_version"),
                    "model_provider": meta.get("model_provider"),
                    "git": meta.get("git"),
                    "agent_role": meta.get("agent_role"),
                    "instructions_length": len(instructions) if instructions else None,
                }
            )
        elif kind == "turn_context":
            ctx = as_dict(payload)
            model = ctx.get("model") or model
            metadata.setdefault("approval_policy", ctx.get("approval_policy"))
            metadata.setdefault("sandbox_policy", ctx.get("sandbox_policy"))
        elif kind == "response_item":
            _handle_response_item(builder, as_dict(payload), when, lineno)
        elif kind == "event_msg":
            usage = _handle_event(builder, as_dict(payload), when, lineno)
            if usage:
                tokens = usage.merged(tokens) if tokens is None else tokens.merged(usage)
        elif kind:
            builder.warnings.append(
                Warning_(message=f"unknown rollout type {kind!r}", locator=builder.loc(lineno))
            )

    messages = [m for m in builder.messages if m.parts]
    summary = summary.model_copy(
        update={
            "message_count": len(messages),
            "title": summary.title or derive_title(messages),
            "model": model,
            "tokens": tokens,
            "updated_at": max(
                (m.created_at for m in messages if m.created_at),
                default=summary.updated_at,
            )
            or summary.updated_at,
            "parse_status": "partial" if parse_errors else "ok",
        }
    )
    if parse_errors:
        notes.append(f"{parse_errors} record(s) could not be parsed and were skipped")
    return Session(
        summary=summary,
        messages=messages,
        warnings=builder.warnings,
        notes=notes,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )


def _handle_response_item(builder: _Builder, payload: dict[str, Any], when, lineno: int) -> None:
    item_type = payload.get("type")
    loc = builder.loc(lineno)

    if item_type == "message":
        role = payload.get("role", "assistant")
        parts = _content_parts(builder, payload.get("content"), loc)
        if not parts:
            return
        if role == "user":
            builder.flush()
            builder.add_message(Message(id=builder.next_id("m"), role="user", created_at=when, parts=parts))
        elif role == "system":
            builder.flush()
            builder.add_message(Message(id=builder.next_id("m"), role="system", created_at=when, parts=parts))
        else:
            builder.assistant(when).parts.extend(parts)
        return

    if item_type == "reasoning":
        text = "\n\n".join(
            filter(
                None,
                [
                    _join_texts(payload.get("summary")),
                    _join_texts(payload.get("content")),
                ],
            )
        )
        encrypted = bool(payload.get("encrypted_content"))
        if not text and not encrypted:
            return
        builder.assistant(when).parts.append(
            ReasoningPart(
                id=builder.next_id("p"),
                text=text or "(encrypted reasoning)",
                encrypted=encrypted,
                locator=loc,
                raw=payload,
            )
        )
        return

    if item_type in ("function_call", "custom_tool_call", "local_shell_call", "web_search_call"):
        part = _tool_call_part(builder, payload, when, loc, item_type)
        builder.assistant(when).parts.append(part)
        if part.call_id:
            builder.tools[part.call_id] = part
        return

    if item_type in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
        _apply_tool_output(builder, payload, when, loc)
        return

    builder.assistant(when).parts.append(
        UnknownPart(
            id=builder.next_id("p"),
            kind=str(item_type or "response_item"),
            data=payload,
            locator=loc,
            raw=payload,
        )
    )


def _tool_call_part(builder: _Builder, payload: dict[str, Any], when, loc, item_type: str) -> ToolPart:
    call_id = payload.get("call_id") or payload.get("id")
    if item_type == "local_shell_call":
        action = as_dict(payload.get("action"))
        name = "shell"
        tool_input: Any = action.get("command") or action
    elif item_type == "web_search_call":
        name = "web_search"
        tool_input = payload.get("action") or payload.get("query")
    else:
        name = payload.get("name") or item_type
        tool_input = _parse_arguments(payload.get("arguments") or payload.get("input"))
    return ToolPart(
        id=builder.next_id("p"),
        name=str(name),
        call_id=str(call_id) if call_id else None,
        input=tool_input,
        status="completed" if payload.get("status") == "completed" else "pending",
        started_at=when,
        locator=loc,
        raw=payload,
    )


def _apply_tool_output(builder: _Builder, payload: dict[str, Any], when, loc) -> None:
    call_id = payload.get("call_id") or payload.get("id")
    raw_output = payload.get("output")
    text, metadata = _split_output(raw_output)
    target = builder.tools.get(str(call_id)) if call_id else None
    if target is None:
        target = ToolPart(
            id=builder.next_id("p"),
            name="unknown",
            call_id=str(call_id) if call_id else None,
            locator=loc,
            raw=payload,
        )
        builder.assistant(when).parts.append(target)
    target.output = text
    target.ended_at = when
    exit_code = metadata.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        target.status = "error"
        target.error = f"exit code {exit_code}"
    else:
        target.status = "completed"
    if metadata:
        target.metadata = {**(target.metadata or {}), **metadata}


def _split_output(raw_output: Any) -> tuple[str, dict[str, Any]]:
    """Codex wraps command output in a JSON envelope with metadata."""
    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            return raw_output, {}
    else:
        parsed = raw_output
    if isinstance(parsed, dict) and ("output" in parsed or "metadata" in parsed):
        return stringify(parsed.get("output", "")), as_dict(parsed.get("metadata"))
    return stringify(parsed), {}


def _parse_arguments(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _join_texts(value: Any) -> str:
    chunks: list[str] = []
    for entry in as_list(value):
        if isinstance(entry, str):
            chunks.append(entry)
        elif isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunk for chunk in chunks if chunk)


def _content_parts(builder: _Builder, content: Any, loc: Locator) -> list[Any]:
    parts: list[Any] = []
    if isinstance(content, str):
        return [TextPart(id=builder.next_id("p"), text=content, locator=loc)]
    for entry in as_list(content):
        if isinstance(entry, str):
            parts.append(TextPart(id=builder.next_id("p"), text=entry, locator=loc))
            continue
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type", "")
        if entry_type in ("input_text", "output_text", "text", "summary_text", "reasoning_text"):
            text = entry.get("text") or ""
            if text:
                parts.append(TextPart(id=builder.next_id("p"), text=text, locator=loc, raw=entry))
        elif entry_type in ("input_image", "image", "output_image"):
            url = entry.get("image_url") or entry.get("url")
            parts.append(
                FilePart(
                    id=builder.next_id("p"),
                    mime="image/*",
                    data_url=url if isinstance(url, str) else None,
                    path=entry.get("path"),
                    locator=loc,
                    raw=entry if not isinstance(url, str) else None,
                )
            )
        elif entry_type in ("input_file", "file"):
            parts.append(
                FilePart(
                    id=builder.next_id("p"),
                    path=entry.get("filename") or entry.get("path"),
                    locator=loc,
                    raw=entry,
                )
            )
        else:
            parts.append(
                UnknownPart(
                    id=builder.next_id("p"),
                    kind=str(entry_type or "content"),
                    data=entry,
                    locator=loc,
                )
            )
    return parts


def _handle_event(builder: _Builder, payload: dict[str, Any], when, lineno: int) -> TokenUsage | None:
    """``event_msg`` only contributes what ``response_item`` does not carry."""
    event_type = payload.get("type")
    loc = builder.loc(lineno)

    if event_type == "token_count":
        info = as_dict(payload.get("info"))
        usage = as_dict(info.get("total_token_usage")) or as_dict(payload.get("total_token_usage"))
        if not usage:
            return None
        return TokenUsage(
            input=usage.get("input_tokens"),
            output=usage.get("output_tokens"),
            cache_read=usage.get("cached_input_tokens"),
            reasoning=usage.get("reasoning_output_tokens"),
        )

    if event_type == "turn_diff":
        diff = payload.get("unified_diff")
        if diff:
            builder.assistant(when).parts.append(
                PatchPart(id=builder.next_id("p"), unified_diff=diff, locator=loc, raw=payload)
            )
        return None

    if event_type in ("error", "stream_error"):
        message = payload.get("message") or stringify(payload)
        target = builder.assistant(when)
        target.parts.append(ErrorPart(id=builder.next_id("p"), message=message, locator=loc, raw=payload))
        target.error = message
        return None

    return None
