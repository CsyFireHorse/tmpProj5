"""Turning normalized parts back into plain text, for titles and search."""

from __future__ import annotations

import json
from typing import Any

from ..models import Message, Part


def part_text(part: Part) -> str:
    kind = getattr(part, "type", "")
    if kind in ("text", "reasoning"):
        return getattr(part, "text", "") or ""
    if kind == "tool":
        pieces = [f"[tool:{part.name}]"]  # type: ignore[union-attr]
        if part.input is not None:  # type: ignore[union-attr]
            pieces.append(stringify(part.input))  # type: ignore[union-attr]
        if part.output:  # type: ignore[union-attr]
            pieces.append(part.output)  # type: ignore[union-attr]
        return "\n".join(pieces)
    if kind == "patch":
        return part.unified_diff or "\n".join(f.diff or f.path for f in part.files)  # type: ignore[union-attr]
    if kind == "file":
        return part.text or part.path or ""  # type: ignore[union-attr]
    if kind == "compaction":
        return part.text or ""  # type: ignore[union-attr]
    if kind == "error":
        return part.message  # type: ignore[union-attr]
    if kind == "todo":
        return "\n".join(item.content for item in part.items)  # type: ignore[union-attr]
    return ""


def message_text(message: Message) -> str:
    return "\n".join(filter(None, (part_text(part) for part in message.parts)))


def stringify(value: Any, limit: int = 20_000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"


def derive_title(messages: list[Message], fallback: str | None = None) -> str | None:
    for message in messages:
        if message.role != "user":
            continue
        text = message_text(message).strip()
        if text:
            first_line = next((line for line in text.splitlines() if line.strip()), "")
            return truncate(first_line.strip(), 120)
    return fallback


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
