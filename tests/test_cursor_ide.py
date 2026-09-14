from __future__ import annotations

from agent_chat_viewer.adapters.cursor_ide import CursorIdeProvider

COMPOSER = "3f1c8c9e-0000-4a00-9000-composer0001"
LEGACY = "legacy:0a1b2c3d4e5f60718293a4b5c6d7e8f9:tab-legacy-1"


def test_lists_composer_and_legacy_chats(settings):
    ids = {s.id for s in CursorIdeProvider(settings).iter_sessions()}
    assert ids == {COMPOSER, LEGACY}


def test_workspace_is_resolved_through_workspace_storage(settings):
    summary = next(s for s in CursorIdeProvider(settings).iter_sessions() if s.id == COMPOSER)
    assert summary.cwd == "/home/demo/projects/checkout-api"
    assert summary.title == "Safari drops the session cookie"


def test_bubbles_render_in_header_order(settings):
    session = CursorIdeProvider(settings).load_session(COMPOSER)
    assert [m.role for m in session.messages] == ["user", "assistant", "user"]


def test_thinking_and_tool_data_become_parts(settings):
    session = CursorIdeProvider(settings).load_session(COMPOSER)
    kinds = [p.type for p in session.messages[1].parts]
    assert kinds == ["reasoning", "text", "tool", "snapshot"]
    tool = session.messages[1].parts[2]
    assert tool.name == "read_file"
    assert tool.input == {"path": "src/auth/session.ts"}


def test_rich_text_only_bubble_still_renders(settings):
    """Composer input is stored as a Lexical tree with no plain `text` field."""
    session = CursorIdeProvider(settings).load_session(COMPOSER)
    assert session.messages[2].parts[0].text == "Ship it, and add a regression test."


def test_missing_bubble_is_a_warning_not_a_failure(settings):
    session = CursorIdeProvider(settings).load_session(COMPOSER)
    assert session.summary.parse_status == "partial"
    assert any("bub-missing" in w.message for w in session.warnings)


def test_token_counts_roll_up(settings):
    session = CursorIdeProvider(settings).load_session(COMPOSER)
    assert session.summary.tokens is not None
    assert session.summary.tokens.input == 6120


def test_legacy_workspace_chat_is_readable(settings):
    session = CursorIdeProvider(settings).load_session(LEGACY)
    assert session.summary.title == "Explain the webpack config"
    assert [m.role for m in session.messages] == ["user", "assistant"]
    assert "webpack" in session.messages[0].parts[0].text


def test_no_resume_command_for_ide_threads(settings):
    """IDE threads cannot be resumed by the CLI; do not pretend otherwise."""
    assert CursorIdeProvider(settings).resume_command(COMPOSER) is None
