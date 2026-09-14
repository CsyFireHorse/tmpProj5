"""Unified data model shared by every provider adapter.

Every adapter maps its native records into these types. Two rules are enforced
by convention across all adapters:

1. Anything that cannot be classified becomes an ``UnknownPart`` that keeps the
   original payload, so format drift degrades rendering instead of losing data.
2. ``raw`` / ``locator`` let the UI show the original record next to the
   normalized view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

ProviderId = Literal["codex", "cursor-cli", "cursor-ide", "opencode"]

PROVIDER_IDS: tuple[ProviderId, ...] = ("codex", "cursor-cli", "cursor-ide", "opencode")

Role = Literal["user", "assistant", "system", "tool"]
ToolStatus = Literal["pending", "running", "completed", "error"]
ParseStatus = Literal["ok", "partial", "error"]


class TokenUsage(BaseModel):
    input: int | None = None
    output: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    reasoning: int | None = None

    @property
    def total(self) -> int:
        return (self.input or 0) + (self.output or 0)

    def merged(self, other: TokenUsage | None) -> TokenUsage:
        if other is None:
            return self

        def pick(a: int | None, b: int | None) -> int | None:
            # Providers report either per-step deltas or a running total; the
            # max is correct for totals and a safe lower bound for deltas.
            if a is None:
                return b
            if b is None:
                return a
            return max(a, b)

        return TokenUsage(
            input=pick(self.input, other.input),
            output=pick(self.output, other.output),
            cache_read=pick(self.cache_read, other.cache_read),
            cache_write=pick(self.cache_write, other.cache_write),
            reasoning=pick(self.reasoning, other.reasoning),
        )


class Locator(BaseModel):
    """Where a normalized record came from, for the raw inspector."""

    source: str
    line: int | None = None
    key: str | None = None


class PartBase(BaseModel):
    id: str
    locator: Locator | None = None
    raw: Any | None = None


class TextPart(PartBase):
    type: Literal["text"] = "text"
    text: str


class ReasoningPart(PartBase):
    type: Literal["reasoning"] = "reasoning"
    text: str
    encrypted: bool = False


class ToolPart(PartBase):
    type: Literal["tool"] = "tool"
    name: str
    call_id: str | None = None
    input: Any | None = None
    output: str | None = None
    status: ToolStatus = "completed"
    error: str | None = None
    title: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class FilePart(PartBase):
    type: Literal["file"] = "file"
    path: str | None = None
    mime: str | None = None
    size: int | None = None
    text: str | None = None
    data_url: str | None = None


class PatchFile(BaseModel):
    path: str
    status: str | None = None
    diff: str | None = None
    additions: int | None = None
    deletions: int | None = None


class PatchPart(PartBase):
    type: Literal["patch"] = "patch"
    files: list[PatchFile] = Field(default_factory=list)
    unified_diff: str | None = None


class SnapshotPart(PartBase):
    type: Literal["snapshot"] = "snapshot"
    ref: str | None = None
    files_changed: int | None = None


class StepPart(PartBase):
    type: Literal["step"] = "step"
    phase: Literal["start", "finish"] = "finish"
    tokens: TokenUsage | None = None
    cost: float | None = None
    duration_ms: int | None = None


class TodoItem(BaseModel):
    content: str
    status: str | None = None


class TodoPart(PartBase):
    type: Literal["todo"] = "todo"
    items: list[TodoItem] = Field(default_factory=list)


class SubtaskPart(PartBase):
    type: Literal["subtask"] = "subtask"
    session_uid: str | None = None
    title: str | None = None
    agent: str | None = None


class CompactionPart(PartBase):
    type: Literal["compaction"] = "compaction"
    text: str | None = None


class ErrorPart(PartBase):
    type: Literal["error"] = "error"
    message: str


class UnknownPart(PartBase):
    type: Literal["unknown"] = "unknown"
    kind: str
    data: Any | None = None


Part = Annotated[
    TextPart
    | ReasoningPart
    | ToolPart
    | FilePart
    | PatchPart
    | SnapshotPart
    | StepPart
    | TodoPart
    | SubtaskPart
    | CompactionPart
    | ErrorPart
    | UnknownPart,
    Field(discriminator="type"),
]


class Message(BaseModel):
    id: str
    role: Role
    created_at: datetime | None = None
    parts: list[Part] = Field(default_factory=list)
    tokens: TokenUsage | None = None
    cost: float | None = None
    model: str | None = None
    error: str | None = None


class SessionSummary(BaseModel):
    provider: ProviderId
    id: str
    uid: str
    title: str | None = None
    cwd: str | None = None
    project: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    message_count: int | None = None
    model: str | None = None
    git_branch: str | None = None
    parent_uid: str | None = None
    kind: Literal["main", "subagent"] = "main"
    tokens: TokenUsage | None = None
    cost: float | None = None
    source_path: str
    source_mtime: float | None = None
    source_size: int | None = None
    parse_status: ParseStatus = "ok"


class Warning_(BaseModel):
    """A non-fatal parsing problem. Surfaced in the UI, never raised."""

    message: str
    locator: Locator | None = None


class Session(BaseModel):
    summary: SessionSummary
    messages: list[Message] = Field(default_factory=list)
    warnings: list[Warning_] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderStatus(BaseModel):
    id: ProviderId
    name: str
    detected: bool
    roots: list[str] = Field(default_factory=list)
    session_count: int | None = None
    error: str | None = None
    note: str | None = None


class ProjectSummary(BaseModel):
    cwd: str | None
    name: str
    session_count: int
    providers: list[ProviderId] = Field(default_factory=list)
    updated_at: datetime | None = None


class SessionPage(BaseModel):
    items: list[SessionSummary] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class SearchHit(BaseModel):
    uid: str
    provider: ProviderId
    title: str | None = None
    project: str | None = None
    role: Role | None = None
    message_id: str | None = None
    snippet: str = ""
    updated_at: datetime | None = None


class SearchResult(BaseModel):
    items: list[SearchHit] = Field(default_factory=list)
    total: int = 0
    query: str = ""


class IndexStatus(BaseModel):
    running: bool = False
    scanned: int = 0
    total: int = 0
    indexed_sessions: int = 0
    last_error: str | None = None
    last_finished_at: datetime | None = None


class StatsBucket(BaseModel):
    key: str
    sessions: int = 0
    messages: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0


class Stats(BaseModel):
    total_sessions: int = 0
    total_messages: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0
    by_provider: list[StatsBucket] = Field(default_factory=list)
    by_model: list[StatsBucket] = Field(default_factory=list)
    by_day: list[StatsBucket] = Field(default_factory=list)


class ResumeCommand(BaseModel):
    """A command the user can copy. The server never runs it."""

    command: str
    cwd: str | None = None
    note: str | None = None
