#!/usr/bin/env python3
"""Write the OpenAPI document so the frontend can generate its types from it.

    python scripts/dump_openapi.py [output.json]

The frontend never hand-writes API types; ``npm run gen:types`` turns this file
into ``src/api/schema.d.ts``. CI regenerates it and fails if the checked-in
copy is stale.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "server" / "src"))

from agent_chat_viewer.config import Settings  # noqa: E402
from agent_chat_viewer.main import create_app  # noqa: E402


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "openapi.json"
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        settings = Settings(
            home=home,
            codex_home=home / ".codex",
            cursor_home=home / ".cursor",
            cursor_user_root=home / "Cursor" / "User",
            opencode_data=home / "opencode",
            state_dir=home / "state",
        )
        app = create_app(settings, autoscan=False)
        target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
