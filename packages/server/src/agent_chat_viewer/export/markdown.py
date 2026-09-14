"""Session export.

These transcripts routinely contain source code, shell arguments and file
paths, so the exporter offers an opt-in redaction pass for anything obviously
credential-shaped before the text leaves the machine.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Message, Part, Session
from ..util.text import stringify

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})"), "sk-***"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,})"), "gh*_***"),
    (re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})"), "xox*-***"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "AKIA***"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "<jwt>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
]

ROLE_LABEL = {"user": "User", "assistant": "Assistant", "system": "System", "tool": "Tool"}


def redact_text(text: str) -> str:
    out = text
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    home = str(Path.home())
    if home and home != "/":
        out = out.replace(home, "~")
    return out


def _fence(text: str, language: str = "") -> str:
    ticks = "```"
    while ticks in text:
        ticks += "`"
    return f"{ticks}{language}\n{text}\n{ticks}"


def _render_part(part: Part) -> str:
    kind = part.type
    if kind == "text":
        return part.text  # type: ignore[union-attr]
    if kind == "reasoning":
        return f"<details><summary>Reasoning</summary>\n\n{part.text}\n\n</details>"  # type: ignore[union-attr]
    if kind == "tool":
        header = f"**Tool `{part.name}`** ({part.status})"  # type: ignore[union-attr]
        blocks = [header]
        if part.input is not None:  # type: ignore[union-attr]
            blocks.append(_fence(stringify(part.input, 4000), "json"))  # type: ignore[union-attr]
        if part.output:  # type: ignore[union-attr]
            blocks.append(_fence(stringify(part.output, 8000)))  # type: ignore[union-attr]
        if part.error:  # type: ignore[union-attr]
            blocks.append(f"> error: {part.error}")  # type: ignore[union-attr]
        return "\n\n".join(blocks)
    if kind == "patch":
        diff = part.unified_diff or "\n".join(  # type: ignore[union-attr]
            f.diff or f"--- {f.path}"
            for f in part.files  # type: ignore[union-attr]
        )
        return _fence(diff, "diff")
    if kind == "file":
        label = part.path or part.mime or "attachment"  # type: ignore[union-attr]
        return f"_attachment: {label}_"
    if kind == "snapshot":
        return f"_workspace snapshot: {part.ref}_"  # type: ignore[union-attr]
    if kind == "step":
        tokens = part.tokens  # type: ignore[union-attr]
        if tokens:
            return f"_step: {tokens.input or 0} in / {tokens.output or 0} out tokens_"
        return ""
    if kind == "todo":
        return "\n".join(f"- [{i.status or ' '}] {i.content}" for i in part.items)  # type: ignore[union-attr]
    if kind == "subtask":
        return f"_subtask: {part.title or part.agent or part.session_uid}_"  # type: ignore[union-attr]
    if kind == "compaction":
        return f"> Context compacted.\n>\n> {part.text or ''}"  # type: ignore[union-attr]
    if kind == "error":
        return f"> **Error:** {part.message}"  # type: ignore[union-attr]
    return _fence(stringify(part.data, 2000), "json")  # type: ignore[union-attr]


def _render_message(message: Message) -> str:
    when = message.created_at.isoformat(timespec="seconds") if message.created_at else ""
    head = f"### {ROLE_LABEL.get(message.role, message.role)}"
    if when:
        head += f"  <sub>{when}</sub>"
    body = "\n\n".join(filter(None, (_render_part(part) for part in message.parts)))
    return f"{head}\n\n{body}"


def render_markdown(session: Session, *, redact: bool = False) -> str:
    summary = session.summary
    lines = [f"# {summary.title or summary.id}", ""]
    facts = [
        ("Provider", summary.provider),
        ("Session", summary.id),
        ("Workspace", summary.cwd or "(unknown)"),
        ("Model", summary.model or "—"),
        ("Created", summary.created_at.isoformat(timespec="seconds") if summary.created_at else "—"),
        ("Updated", summary.updated_at.isoformat(timespec="seconds") if summary.updated_at else "—"),
        ("Messages", str(summary.message_count or len(session.messages))),
    ]
    if summary.tokens:
        facts.append(("Tokens", f"{summary.tokens.input or 0} in / {summary.tokens.output or 0} out"))
    lines += [f"- **{label}:** {value}" for label, value in facts]
    if session.notes:
        lines += ["", "> " + "\n> ".join(session.notes)]
    lines += ["", "---", ""]
    lines += [_render_message(message) for message in session.messages]
    if session.warnings:
        lines += ["", "---", "", "## Parsing warnings", ""]
        lines += [f"- {w.message}" for w in session.warnings]
    text = "\n\n".join(lines)
    return redact_text(text) if redact else text
