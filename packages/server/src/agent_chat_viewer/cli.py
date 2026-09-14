"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .config import build_settings
from .main import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-chat-viewer",
        description="Browse Cursor / Codex / opencode chat histories locally.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--open", action="store_true", help="open a browser once the server is up")
    parser.add_argument("--no-scan", action="store_true", help="do not index at startup")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="browse a synthetic store instead of real history (no agent required)",
    )
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    if args.demo:
        from .demo import build_demo_home

        demo_home = Path(tempfile.gettempdir()) / "agent-chat-viewer-demo"
        build_demo_home(demo_home)
        os.environ["ACV_HOME"] = str(demo_home)
        os.environ["ACV_STATE_DIR"] = str(demo_home / ".state")
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("XDG_DATA_HOME", None)
        os.environ.pop("XDG_STATE_HOME", None)
        os.environ.pop("CODEX_HOME", None)
        print(f"demo mode: synthetic history in {demo_home}")

    settings = build_settings()
    app = create_app(settings, autoscan=not args.no_scan)

    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    if args.host != "127.0.0.1":
        logging.warning("Binding to %s exposes local chat history beyond this machine.", args.host)
    print(f"agent-chat-viewer {__version__} -> {url}")
    print(f"state dir: {settings.state_dir}")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
