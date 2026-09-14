"""Synthetic stores for every supported provider.

Two uses:

* tests run against this instead of real chat history, which contains private
  data and does not exist on CI machines;
* ``agent-chat-viewer --demo`` builds one in a temp directory so the UI can be
  explored on a machine with no coding agent installed.

The generator deliberately includes broken records (a truncated JSONL line, an
unknown item type, a dangling bubble reference, a non-JSON blob) so tolerant
parsing is exercised by default rather than as an afterthought.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BASE = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)
WORKSPACE = "/home/demo/projects/checkout-api"
WORKSPACE_2 = "/home/demo/projects/design-system"


def _iso(offset_seconds: int) -> str:
    return (BASE + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _ms(offset_seconds: int) -> int:
    return int((BASE + timedelta(seconds=offset_seconds)).timestamp() * 1000)


def build_demo_home(root: Path) -> Path:
    """Create a complete synthetic home under ``root`` and return it."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _build_codex(root / ".codex")
    _build_opencode(root / ".local" / "share" / "opencode")
    _build_cursor_ide(root / ".config" / "Cursor" / "User")
    _build_cursor_cli(root / ".cursor")
    return root


# ---------------------------------------------------------------- codex ----
def _rollout_line(kind: str, payload: dict[str, Any], offset: int) -> str:
    return json.dumps({"timestamp": _iso(offset), "type": kind, "payload": payload})


def _build_codex(home: Path) -> None:
    day = home / "sessions" / "2026" / "09" / "12"
    day.mkdir(parents=True, exist_ok=True)

    main_id = "0199a1f0-1111-7000-8000-000000000001"
    sub_id = "0199a1f0-2222-7000-8000-000000000002"

    lines = [
        _rollout_line(
            "session_meta",
            {
                "id": main_id,
                "timestamp": _iso(0),
                "cwd": WORKSPACE,
                "originator": "codex-tui",
                "cli_version": "0.121.0",
                "source": "cli",
                "model_provider": "openai",
                "base_instructions": {"text": "You are Codex, a coding agent."},
                "git": {
                    "commit_hash": "a1b2c3d",
                    "branch": "feature/idempotency",
                    "repository_url": "git@github.com:demo/checkout-api.git",
                },
            },
            0,
        ),
        _rollout_line("turn_context", {"model": "gpt-5-codex", "approval_policy": "on-request"}, 1),
        _rollout_line(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Payments can be charged twice on retry. Add an idempotency key to "
                        "`POST /charges` and cover it with a test.",
                    }
                ],
            },
            2,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "reasoning",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": "Find the charge handler, then decide where the key should be stored.",
                    }
                ],
            },
            3,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "function_call",
                "name": "shell",
                "call_id": "call_1",
                "arguments": json.dumps({"command": ["rg", "-n", "def create_charge", "src"]}),
            },
            4,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": json.dumps(
                    {
                        "output": "src/payments/charges.py:42:def create_charge(request: ChargeRequest):",
                        "metadata": {"exit_code": 0, "duration_seconds": 0.11},
                    }
                ),
            },
            5,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "function_call",
                "name": "apply_patch",
                "call_id": "call_2",
                "arguments": json.dumps({"patch": "*** Update File: src/payments/charges.py"}),
            },
            6,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "call_2",
                "output": json.dumps({"output": "Applied patch", "metadata": {"exit_code": 0}}),
            },
            7,
        ),
        _rollout_line(
            "event_msg",
            {
                "type": "turn_diff",
                "unified_diff": (
                    "--- a/src/payments/charges.py\n"
                    "+++ b/src/payments/charges.py\n"
                    "@@ -40,6 +40,11 @@\n"
                    " def create_charge(request: ChargeRequest):\n"
                    "+    key = request.idempotency_key\n"
                    "+    existing = repo.find_by_key(key)\n"
                    "+    if existing:\n"
                    "+        return existing\n"
                    "     return repo.charge(request)\n"
                ),
            },
            8,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "`POST /charges` now takes an `Idempotency-Key` header. A repeat "
                        "request with the same key returns the original charge instead of "
                        "creating a second one, and `tests/test_charges.py::test_retry_is_idempotent`"
                        " covers it.",
                    }
                ],
            },
            9,
        ),
        _rollout_line(
            "event_msg",
            {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 18432,
                        "cached_input_tokens": 12000,
                        "output_tokens": 2110,
                        "reasoning_output_tokens": 640,
                    }
                },
            },
            10,
        ),
        # Tolerance: an item type this build does not know about.
        _rollout_line("response_item", {"type": "future_item_kind", "note": "added in a later release"}, 11),
    ]
    main_file = day / f"rollout-2026-09-12T10-00-00-{main_id}.jsonl"
    main_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # A subagent run: separate file, linked back through parent_thread_id.
    sub_lines = [
        _rollout_line(
            "session_meta",
            {
                "id": sub_id,
                "timestamp": _iso(4),
                "cwd": WORKSPACE,
                "originator": "codex-tui",
                "cli_version": "0.121.0",
                "parent_thread_id": main_id,
                "agent_nickname": "Hubble",
                "agent_role": "explorer",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": main_id}}},
            },
            4,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Where is the retry logic for payments?"}],
            },
            5,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "`src/payments/retry.py` wraps every gateway call."}
                ],
            },
            6,
        ),
    ]
    (day / f"rollout-2026-09-12T10-00-04-{sub_id}.jsonl").write_text(
        "\n".join(sub_lines) + "\n", encoding="utf-8"
    )

    # Tolerance: a truncated final line must not lose the rest of the session.
    broken_id = "0199a1f0-3333-7000-8000-000000000003"
    broken = [
        _rollout_line(
            "session_meta",
            {"id": broken_id, "timestamp": _iso(20), "cwd": WORKSPACE_2, "cli_version": "0.121.0"},
            20,
        ),
        _rollout_line(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Rename the Button size tokens."}],
            },
            21,
        ),
        '{"timestamp": "2026-09-12T10:00:22Z", "type": "response_item", "payload": {"type": "mess',
    ]
    (day / f"rollout-2026-09-12T10-00-20-{broken_id}.jsonl").write_text(
        "\n".join(broken) + "\n", encoding="utf-8"
    )

    # Not a session: no session_meta header, must be ignored silently.
    (day / "rollout-2026-09-12T10-00-30-not-a-session.jsonl").write_text(
        json.dumps({"timestamp": _iso(30), "type": "event_msg", "payload": {"type": "task_started"}}) + "\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------- opencode ----
def _opencode_records() -> tuple[dict, list[dict], dict[str, list[dict]]]:
    session = {
        "id": "ses_demo0001",
        "projectID": "prj_demo",
        "directory": WORKSPACE_2,
        "parentID": None,
        "title": "Migrate Button to the new size scale",
        "agent": "build",
        "model": "claude-sonnet-4",
        "time": {"created": _ms(0), "updated": _ms(300)},
    }
    messages = [
        {
            "id": "msg_0001",
            "sessionID": session["id"],
            "role": "user",
            "time": {"created": _ms(0)},
        },
        {
            "id": "msg_0002",
            "sessionID": session["id"],
            "role": "assistant",
            "parentID": "msg_0001",
            "modelID": "claude-sonnet-4",
            "providerID": "anthropic",
            "cost": 0.0412,
            "tokens": {"input": 9120, "output": 1440, "cache": {"read": 8000, "write": 512}},
            "time": {"created": _ms(5), "completed": _ms(60)},
        },
    ]
    parts = {
        "msg_0001": [
            {
                "id": "prt_0001",
                "messageID": "msg_0001",
                "sessionID": session["id"],
                "type": "text",
                "text": "Button still uses sm/md/lg. Move it to the numeric scale and update every "
                "call site.",
            }
        ],
        "msg_0002": [
            {
                "id": "prt_0002",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "step-start",
            },
            {
                "id": "prt_0003",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "reasoning",
                "text": "Check how many call sites there are before changing the component API.",
            },
            {
                "id": "prt_0004",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "tool",
                "tool": "grep",
                "callID": "toolu_01",
                "state": {
                    "status": "completed",
                    "title": "grep size= in src",
                    "input": {"pattern": 'size="(sm|md|lg)"', "path": "src"},
                    "output": "src/pages/Checkout.tsx:18\nsrc/pages/Settings.tsx:44\n"
                    "src/components/Toolbar.tsx:9",
                    "time": {"start": _ms(10), "end": _ms(11)},
                    "metadata": {"matches": 3},
                },
            },
            {
                "id": "prt_0005",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "patch",
                "files": [
                    {
                        "path": "src/components/Button.tsx",
                        "status": "modified",
                        "additions": 6,
                        "deletions": 4,
                        "diff": "--- a/src/components/Button.tsx\n+++ b/src/components/Button.tsx\n"
                        "@@\n-type Size = 'sm' | 'md' | 'lg'\n+type Size = 100 | 200 | 300\n",
                    }
                ],
            },
            {
                "id": "prt_0006",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "text",
                "text": "Done. `Size` is now `100 | 200 | 300` and the three call sites were updated. "
                "The old string values throw a type error rather than silently falling back.",
            },
            {
                "id": "prt_0007",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "step-finish",
                "cost": 0.0412,
                "tokens": {"input": 9120, "output": 1440},
            },
            # Tolerance: a part type from a newer opencode release.
            {
                "id": "prt_0008",
                "messageID": "msg_0002",
                "sessionID": session["id"],
                "type": "some-new-part",
                "payload": {"hello": "world"},
            },
        ],
    }
    return session, messages, parts


def _build_opencode(data_dir: Path) -> None:
    session, messages, parts = _opencode_records()

    # New era: a single SQLite database.
    data_dir.mkdir(parents=True, exist_ok=True)
    db = data_dir / "opencode.db"
    db.unlink(missing_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, title TEXT,
                              time_created INTEGER, time_updated INTEGER, data TEXT);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT);
        """
    )
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?)",
        (
            session["id"],
            session["directory"],
            session["title"],
            session["time"]["created"],
            session["time"]["updated"],
            json.dumps(session),
        ),
    )
    for message in messages:
        conn.execute(
            "INSERT INTO message VALUES (?,?,?,?)",
            (message["id"], session["id"], message["time"]["created"], json.dumps(message)),
        )
        for part in parts.get(message["id"], []):
            conn.execute(
                "INSERT INTO part VALUES (?,?,?,?)",
                (part["id"], message["id"], session["id"], json.dumps(part)),
            )
    conn.commit()
    conn.close()

    # Old era: the same payloads as individual JSON files, under a project dir.
    storage = data_dir / "project" / "prj_legacy" / "storage"
    legacy_id = "ses_legacy01"
    legacy_session = {
        **session,
        "id": legacy_id,
        "title": "Add dark mode tokens (pre-1.2 storage)",
        "directory": WORKSPACE_2,
    }
    _write_json(storage / "session" / "prj_legacy" / f"{legacy_id}.json", legacy_session)
    _write_json(
        storage / "message" / legacy_id / "msg_l001.json",
        {"id": "msg_l001", "sessionID": legacy_id, "role": "user", "time": {"created": _ms(0)}},
    )
    _write_json(
        storage / "part" / "msg_l001" / "prt_l001.json",
        {"id": "prt_l001", "messageID": "msg_l001", "type": "text", "text": "Add dark mode tokens."},
    )
    _write_json(
        storage / "message" / legacy_id / "msg_l002.json",
        {
            "id": "msg_l002",
            "sessionID": legacy_id,
            "role": "assistant",
            "time": {"created": _ms(30)},
            "tokens": {"input": 500, "output": 120},
        },
    )
    _write_json(
        storage / "part" / "msg_l002" / "prt_l002.json",
        {
            "id": "prt_l002",
            "messageID": "msg_l002",
            "type": "text",
            "text": "Added `--surface-raised` and `--surface-sunken` for both themes.",
        },
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ----------------------------------------------------------- cursor IDE ----
def _build_cursor_ide(user_root: Path) -> None:
    global_dir = user_root / "globalStorage"
    global_dir.mkdir(parents=True, exist_ok=True)
    db = global_dir / "state.vscdb"
    db.unlink(missing_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB);
        CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB);
        """
    )

    composer_id = "3f1c8c9e-0000-4a00-9000-composer0001"
    bubbles = [
        (
            "bub-0001",
            {
                "_v": 8,
                "bubbleId": "bub-0001",
                "type": 1,
                "text": "The session cookie is dropped on Safari. Figure out why and fix it.",
                "timestamp": _ms(0),
            },
        ),
        (
            "bub-0002",
            {
                "_v": 8,
                "bubbleId": "bub-0002",
                "type": 2,
                "thinking": {"text": "SameSite=None without Secure is rejected by Safari."},
                "text": "The cookie is set with `SameSite=None` but without `Secure`, so Safari "
                "discards it. Setting both fixes it.",
                "toolFormerData": {
                    "name": "read_file",
                    "toolCallId": "tool-1",
                    "rawArgs": json.dumps({"path": "src/auth/session.ts"}),
                    "result": "res.cookie('sid', token, { sameSite: 'none' })",
                },
                "tokenCount": {"inputTokens": 6120, "outputTokens": 480},
                "checkpointId": "ckpt-0001",
                "timestamp": _ms(45),
            },
        ),
        (
            "bub-0003",
            {
                "_v": 8,
                "bubbleId": "bub-0003",
                "type": 1,
                # No plain text: only the Lexical editor state, as Cursor stores
                # it when the message came from the composer input.
                "richText": json.dumps(
                    {
                        "root": {
                            "children": [
                                {"children": [{"text": "Ship it, and add a regression test."}]},
                            ]
                        }
                    }
                ),
                "timestamp": _ms(90),
            },
        ),
    ]
    for bubble_id, payload in bubbles:
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES (?,?)",
            (f"bubbleId:{composer_id}:{bubble_id}", json.dumps(payload)),
        )
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        (f"checkpointId:{composer_id}:ckpt-0001", json.dumps({"files": ["src/auth/session.ts"]})),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        (
            f"composerData:{composer_id}",
            json.dumps(
                {
                    "_v": 8,
                    "composerId": composer_id,
                    "name": "Safari drops the session cookie",
                    "createdAt": _ms(0),
                    "lastUpdatedAt": _ms(120),
                    "status": "completed",
                    "isAgentic": True,
                    "latestModel": {"modelName": "claude-4.5-sonnet"},
                    "fullConversationHeadersOnly": [
                        {"bubbleId": "bub-0001", "type": 1},
                        {"bubbleId": "bub-0002", "type": 2},
                        {"bubbleId": "bub-0003", "type": 1},
                        # Tolerance: a header whose bubble row is gone.
                        {"bubbleId": "bub-missing", "type": 2},
                    ],
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    workspace_hash = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    ws_dir = user_root / "workspaceStorage" / workspace_hash
    ws_dir.mkdir(parents=True, exist_ok=True)
    _write_json(ws_dir / "workspace.json", {"folder": f"file://{WORKSPACE}"})
    ws_db = ws_dir / "state.vscdb"
    ws_db.unlink(missing_ok=True)
    conn = sqlite3.connect(ws_db)
    conn.executescript("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB);")
    conn.execute(
        "INSERT INTO ItemTable VALUES (?,?)",
        (
            "composer.composerData",
            json.dumps(
                {
                    "allComposers": [
                        {
                            "composerId": composer_id,
                            "name": "Safari drops the session cookie",
                            "createdAt": _ms(0),
                        }
                    ]
                }
            ),
        ),
    )
    # A pre-composer chat, which older Cursor stored in the workspace database.
    conn.execute(
        "INSERT INTO ItemTable VALUES (?,?)",
        (
            "workbench.panel.aichat.view.aichat.chatdata",
            json.dumps(
                {
                    "tabs": [
                        {
                            "tabId": "tab-legacy-1",
                            "chatTitle": "Explain the webpack config",
                            "lastSendTime": _ms(-86400),
                            "bubbles": [
                                {"type": "user", "text": "Why do we need two webpack configs?"},
                                {
                                    "type": "ai",
                                    "text": "One targets the browser bundle, the other the SSR "
                                    "server build; they differ in `target` and `externals`.",
                                },
                            ],
                        }
                    ]
                }
            ),
        ),
    )
    conn.commit()
    conn.close()


# ----------------------------------------------------------- cursor CLI ----
def _build_cursor_cli(cursor_home: Path) -> None:
    # One workspace whose path the reverse index can recover (an agent-hooks
    # directory records it as base64url), and one it cannot.
    known_hash = hashlib.md5(WORKSPACE.encode()).hexdigest()
    unknown_hash = hashlib.md5(b"/some/path/this/machine/never/saw").hexdigest()

    hook_dir = cursor_home / "agent-hooks" / base64.urlsafe_b64encode(WORKSPACE.encode()).decode().rstrip("=")
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / ".dispatcher").write_text("", encoding="utf-8")

    session_id = str(uuid.UUID("7a5f1c2e-4b3d-4e6f-8a9b-0c1d2e3f4a5b"))
    _write_cli_session(
        cursor_home / "chats" / known_hash / session_id,
        title="Flaky integration test on CI",
        messages=[
            {
                "role": "user",
                "timestamp": _ms(0),
                "content": [
                    {
                        "type": "text",
                        "text": "`test_webhook_ordering` fails maybe one run in five on CI but never "
                        "locally. Find the race.",
                    }
                ],
            },
            {
                "role": "assistant",
                "timestamp": _ms(20),
                "content": [
                    {
                        "type": "thinking",
                        "text": "Only failing under parallelism points at shared state between tests.",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_a1",
                        "name": "run_terminal_cmd",
                        "input": {"command": "pytest -n 4 tests/test_webhooks.py -q"},
                    },
                ],
            },
            {
                "role": "tool",
                "timestamp": _ms(40),
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a1",
                        "content": "1 failed, 23 passed\nAssertionError: expected 2 events, got 3",
                    }
                ],
            },
            {
                "role": "assistant",
                "timestamp": _ms(60),
                "content": [
                    {
                        "type": "text",
                        "text": "The webhook queue is a module-level singleton, so parallel workers "
                        "share it. Making it a fixture with per-test isolation removes the race.",
                    }
                ],
            },
        ],
        prompts=["`test_webhook_ordering` fails maybe one run in five on CI but never locally."],
    )

    _write_cli_session(
        cursor_home / "chats" / unknown_hash / "8b6a2d3f-5c4e-4f70-9bac-1d2e3f4a5b6c",
        title="Unknown workspace demo",
        messages=[
            {
                "role": "user",
                "timestamp": _ms(0),
                "content": [{"type": "text", "text": "Summarize what this repo does."}],
            },
            {
                "role": "assistant",
                "timestamp": _ms(10),
                "content": [{"type": "text", "text": "It is a CLI that syncs calendars."}],
            },
        ],
        prompts=["Summarize what this repo does."],
    )


def _write_cli_session(
    session_dir: Path, *, title: str, messages: list[dict[str, Any]], prompts: list[str]
) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        session_dir / "meta.json",
        {"title": title, "createdAtMs": _ms(0), "updatedAtMs": _ms(120)},
    )
    _write_json(session_dir / "prompt_history.json", prompts)

    db = session_dir / "store.db"
    db.unlink(missing_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    agent_record = {
        "agentId": session_dir.name,
        "name": title,
        "mode": "agent",
        "createdAt": _ms(0),
        "lastUsedModel": "claude-4.5-sonnet",
        "latestRootBlobId": "root",
    }
    conn.execute(
        "INSERT INTO meta VALUES ('0', ?)",
        (json.dumps(agent_record).encode().hex(),),
    )
    for message in messages:
        payload = json.dumps(message).encode()
        conn.execute(
            "INSERT INTO blobs VALUES (?,?)",
            (hashlib.sha256(payload).hexdigest(), payload),
        )
    # A protobuf turn-graph blob: binary, must be counted and skipped, not fail.
    conn.execute("INSERT INTO blobs VALUES (?,?)", ("root", b"\x0a\x10turn-graph\x12\x04root"))
    conn.commit()
    conn.close()
