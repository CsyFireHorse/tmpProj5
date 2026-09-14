#!/usr/bin/env python3
"""Generate the synthetic provider stores used by the tests.

    python scripts/make_fixtures.py [output-dir]

Defaults to ``fixtures/home``. The tests build their own copy in a temp
directory; this script exists for poking at the fixtures by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "server" / "src"))

from agent_chat_viewer.demo import build_demo_home  # noqa: E402


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "fixtures" / "home"
    build_demo_home(target)
    print(f"fixtures written to {target}")
    for path in sorted(target.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(target)}  ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
