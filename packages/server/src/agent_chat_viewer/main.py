"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .adapters import Registry
from .api import router
from .config import Settings, build_settings
from .index import Index, Scanner

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# The Vite dev server runs on its own origin; the built app is served same-origin.
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app(settings: Settings | None = None, *, autoscan: bool = True) -> FastAPI:
    settings = settings or build_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if autoscan:
            app.state.scanner.start()
        yield
        app.state.index.close()

    app = FastAPI(
        title="Agent Chat Viewer",
        version=__version__,
        summary="Local, read-only viewer for Cursor / Codex / opencode chat histories",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = Registry(settings)
    app.state.index = Index(settings.index_db)
    app.state.scanner = Scanner(app.state.registry, app.state.index)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)

    if (STATIC_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = STATIC_DIR / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app
