from __future__ import annotations

import pytest

from agent_chat_viewer.adapters.opencode import OpencodeProvider

DB_SESSION = "ses_demo0001"
JSON_SESSION = "ses_legacy01"


def test_both_storage_eras_are_discovered(settings):
    """1.2+ keeps a SQLite db; older builds keep JSON files. Both must list."""
    ids = {s.id for s in OpencodeProvider(settings).iter_sessions()}
    assert ids == {DB_SESSION, JSON_SESSION}


def test_detect_reports_which_backends_are_present(settings):
    status = OpencodeProvider(settings).detect()
    assert status.detected
    assert status.note is not None
    assert "sqlite" in status.note and "json-files" in status.note


@pytest.mark.parametrize("session_id", [DB_SESSION, JSON_SESSION])
def test_sessions_load_from_either_backend(settings, session_id):
    session = OpencodeProvider(settings).load_session(session_id)
    assert session.messages
    assert session.messages[0].role == "user"
    assert session.summary.cwd == "/home/demo/projects/design-system"


def test_parts_are_normalized_by_type(settings):
    session = OpencodeProvider(settings).load_session(DB_SESSION)
    assistant = session.messages[1]
    kinds = [p.type for p in assistant.parts]
    assert kinds == ["step", "reasoning", "tool", "patch", "text", "step", "unknown"]


def test_tool_part_keeps_input_output_and_timing(settings):
    session = OpencodeProvider(settings).load_session(DB_SESSION)
    tool = next(p for p in session.messages[1].parts if p.type == "tool")
    assert tool.name == "grep"
    assert tool.status == "completed"
    assert tool.input == {"pattern": 'size="(sm|md|lg)"', "path": "src"}
    assert "Checkout.tsx" in (tool.output or "")
    assert tool.started_at is not None and tool.ended_at is not None


def test_patch_part_carries_a_diff(settings):
    session = OpencodeProvider(settings).load_session(DB_SESSION)
    patch = next(p for p in session.messages[1].parts if p.type == "patch")
    assert patch.files[0].path == "src/components/Button.tsx"
    assert "Size = 100" in (patch.files[0].diff or "")


def test_unknown_part_type_is_preserved(settings):
    session = OpencodeProvider(settings).load_session(DB_SESSION)
    unknown = next(p for p in session.messages[1].parts if p.type == "unknown")
    assert unknown.kind == "some-new-part"
    assert unknown.data["payload"] == {"hello": "world"}


def test_usage_and_cost_roll_up_to_the_session(settings):
    session = OpencodeProvider(settings).load_session(DB_SESSION)
    assert session.summary.tokens is not None
    assert session.summary.tokens.input == 9120
    assert session.summary.tokens.cache_read == 8000
    assert session.summary.cost == pytest.approx(0.0412)
