"""HTTP API.

Everything the frontend needs is here; the frontend never touches the file
system itself. Endpoints are read-only with two exceptions that only write to
this app's own state directory: rescan and workspace binding.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from ..adapters import Registry, SessionNotFound
from ..adapters.cursor_cli import CursorCliProvider
from ..export import render_markdown
from ..models import (
    IndexStatus,
    ProjectSummary,
    ProviderStatus,
    ResumeCommand,
    SearchResult,
    Session,
    SessionPage,
    SessionSummary,
    Stats,
)

router = APIRouter(prefix="/api")


def _registry(request: Request) -> Registry:
    return request.app.state.registry


def _index(request: Request):
    return request.app.state.index


def _scanner(request: Request):
    return request.app.state.scanner


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class AppStatus(BaseModel):
    version: str
    index: IndexStatus
    state_dir: str
    provider_counts: dict[str, int]


class BindWorkspaceRequest(BaseModel):
    workspace_hash: str
    path: str


class ActionResult(BaseModel):
    ok: bool
    detail: str | None = None


class RevealRequest(BaseModel):
    path: str


@router.get("/health", response_model=Health)
def health() -> Health:
    from .. import __version__

    return Health(version=__version__)


@router.get("/status", response_model=AppStatus)
def status(request: Request) -> AppStatus:
    from .. import __version__

    return AppStatus(
        version=__version__,
        index=_scanner(request).status,
        state_dir=str(request.app.state.settings.state_dir),
        provider_counts=_index(request).provider_counts(),
    )


@router.get("/providers", response_model=list[ProviderStatus])
def providers(request: Request) -> list[ProviderStatus]:
    counts = _index(request).provider_counts()
    out = []
    for provider in _registry(request).all():
        status = provider.detect()
        if status.session_count is None:
            status.session_count = counts.get(provider.id)
        out.append(status)
    return out


@router.get("/projects", response_model=list[ProjectSummary])
def projects(request: Request) -> list[ProjectSummary]:
    return [ProjectSummary(**row) for row in _index(request).projects()]


@router.get("/sessions", response_model=SessionPage)
def list_sessions(
    request: Request,
    provider: Annotated[list[str] | None, Query()] = None,
    project: str | None = None,
    q: str | None = None,
    kind: Literal["main", "subagent"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    sort: Literal["updated", "created", "messages", "title"] = "updated",
    offset: int = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> SessionPage:
    items, total = _index(request).list_sessions(
        providers=provider,
        project=project,
        query=q,
        kind=kind,
        since=since,
        until=until,
        sort=sort,
        offset=offset,
        limit=limit,
    )
    return SessionPage(items=items, total=total, offset=offset, limit=limit)


@router.get("/search", response_model=SearchResult)
def search(
    request: Request,
    q: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SearchResult:
    return _index(request).search(q, limit)


@router.get("/stats", response_model=Stats)
def stats(request: Request) -> Stats:
    return _index(request).stats()


@router.post("/index/rescan", response_model=ActionResult)
def rescan(request: Request, force: bool = False) -> ActionResult:
    started = _scanner(request).start(force=force)
    return ActionResult(ok=started, detail=None if started else "a scan is already running")


def _load(request: Request, uid: str) -> Session:
    provider, session_id = _registry(request).split_uid(uid)
    try:
        return provider.load_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {uid}") from exc
    except Exception as exc:  # a broken store must not look like a server bug
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/sessions/{uid}", response_model=Session)
def get_session(request: Request, uid: str, raw: bool = False) -> Session:
    session = _load(request, uid)
    if not raw:
        # The raw payloads roughly double the response; the inspector fetches
        # them separately from /raw when the user asks for them.
        for message in session.messages:
            for part in message.parts:
                part.raw = None
    session.summary.parent_uid = session.summary.parent_uid
    return session


@router.get("/sessions/{uid}/children", response_model=list[SessionSummary])
def session_children(request: Request, uid: str) -> list[SessionSummary]:
    return _index(request).children(uid)


@router.get("/sessions/{uid}/raw")
def session_raw(request: Request, uid: str, limit: Annotated[int, Query(ge=1, le=20000)] = 2000) -> Any:
    provider, session_id = _registry(request).split_uid(uid)
    try:
        records = []
        for i, record in enumerate(provider.raw_records(session_id)):
            if i >= limit:
                break
            records.append(record)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {uid}") from exc
    return {"uid": uid, "records": records, "truncated": len(records) >= limit}


@router.get("/sessions/{uid}/export", response_class=PlainTextResponse)
def export_session(
    request: Request,
    uid: str,
    format: Literal["md", "json"] = "md",
    redact: bool = False,
) -> PlainTextResponse:
    session = _load(request, uid)
    stem = (session.summary.title or session.summary.id)[:60].strip().replace("/", "-") or session.summary.id
    if format == "json":
        body = session.model_dump_json(indent=2)
        media, ext = "application/json", "json"
    else:
        body = render_markdown(session, redact=redact)
        media, ext = "text/markdown; charset=utf-8", "md"
    return PlainTextResponse(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'},
    )


@router.get("/sessions/{uid}/resume-command", response_model=ResumeCommand)
def resume_command(request: Request, uid: str) -> ResumeCommand:
    provider, session_id = _registry(request).split_uid(uid)
    command = provider.resume_command(session_id)
    if not command:
        raise HTTPException(status_code=404, detail=f"{provider.name} has no resume command")
    summary = _index(request).get(uid)
    cwd = summary.cwd if summary else None
    return ResumeCommand(
        command=f"cd {cwd} && {command}" if cwd else command,
        cwd=cwd,
        note="Copy and run this yourself; the viewer never executes it.",
    )


@router.post("/actions/bind-workspace", response_model=ActionResult)
def bind_workspace(request: Request, body: BindWorkspaceRequest) -> ActionResult:
    provider = _registry(request).get("cursor-cli")
    assert isinstance(provider, CursorCliProvider)
    if not provider.bind_workspace(body.workspace_hash, body.path):
        return ActionResult(ok=False, detail="path does not hash to that workspace bucket")
    _scanner(request).start(force=True)
    return ActionResult(ok=True, detail="bound; rescanning")


@router.post("/actions/reveal", response_model=ActionResult)
def reveal(request: Request, body: RevealRequest) -> ActionResult:
    """Open the OS file manager at a source file. Confined to detected roots."""
    target = Path(body.path).expanduser()
    allowed = [root for provider in _registry(request).all() for root in provider.roots()]
    if not any(_is_within(target, root) for root in allowed):
        raise HTTPException(status_code=403, detail="path is outside the detected provider roots")
    if not target.exists():
        raise HTTPException(status_code=404, detail="path does not exist")
    command = {
        "darwin": ["open", "-R", str(target)],
        "win32": ["explorer", "/select,", str(target)],
    }.get(sys.platform, ["xdg-open", str(target.parent)])
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return ActionResult(ok=False, detail=str(exc))
    return ActionResult(ok=True)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events: index progress and session updates."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
    loop = asyncio.get_running_loop()
    scanner = _scanner(request)

    def listener(event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
        loop.call_soon_threadsafe(_offer, queue, payload)

    unsubscribe = scanner.subscribe(listener)

    async def stream():
        try:
            yield f"event: index\ndata: {scanner.status.model_dump_json()}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _offer(queue: asyncio.Queue[str], payload: str) -> None:
    # A client too slow to keep up loses progress events, not the connection.
    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(payload)
