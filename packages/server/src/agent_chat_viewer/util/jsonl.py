"""Tolerant JSON / JSONL helpers.

A truncated or invalid record must never abort a whole session: callers get the
records that did parse plus a list of warnings describing the ones that did not.
"""

from __future__ import annotations

import gzip
import json
import lzma
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def open_maybe_compressed(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if suffix in (".xz", ".lzma"):
        return lzma.open(path, "rt", encoding="utf-8", errors="replace")
    if suffix == ".zst":
        try:
            import zstandard  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("zstd rollout requires the 'zstandard' package") from exc
        fh = path.open("rb")
        reader = zstandard.ZstdDecompressor().stream_reader(fh)
        import io

        return io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def iter_jsonl(path: Path, *, limit: int | None = None) -> Iterator[tuple[int, Any, str | None]]:
    """Yield ``(line_number, value, error)``. ``value`` is None when ``error`` is set."""
    with open_maybe_compressed(path) as fh:
        for lineno, line in enumerate(fh, start=1):
            if limit is not None and lineno > limit:
                return
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield lineno, json.loads(stripped), None
            except json.JSONDecodeError as exc:
                yield lineno, None, f"line {lineno}: {exc.msg}"


def read_json(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def loads_maybe(value: Any) -> Any:
    """Parse ``value`` if it looks like JSON text, otherwise return it as-is."""
    if isinstance(value, bytes | bytearray):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "[", '"') or stripped in ("true", "false", "null"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
        return value
    return value


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
