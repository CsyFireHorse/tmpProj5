from __future__ import annotations

from agent_chat_viewer.adapters.codex import CodexProvider

MAIN_ID = "0199a1f0-1111-7000-8000-000000000001"
SUB_ID = "0199a1f0-2222-7000-8000-000000000002"
BROKEN_ID = "0199a1f0-3333-7000-8000-000000000003"


def test_lists_only_files_with_a_session_header(settings):
    provider = CodexProvider(settings)
    ids = {s.id for s in provider.iter_sessions()}
    assert ids == {MAIN_ID, SUB_ID, BROKEN_ID}


def test_header_carries_workspace_and_git_metadata(settings):
    provider = CodexProvider(settings)
    summary = next(s for s in provider.iter_sessions() if s.id == MAIN_ID)
    assert summary.cwd == "/home/demo/projects/checkout-api"
    assert summary.project == "checkout-api"
    assert summary.git_branch == "feature/idempotency"
    assert summary.kind == "main"


def test_subagent_links_back_to_its_parent(settings):
    provider = CodexProvider(settings)
    summary = next(s for s in provider.iter_sessions() if s.id == SUB_ID)
    assert summary.kind == "subagent"
    assert summary.parent_uid == f"codex:{MAIN_ID}"


def test_transcript_shape(settings):
    session = CodexProvider(settings).load_session(MAIN_ID)
    roles = [m.role for m in session.messages]
    assert roles == ["user", "assistant"]

    assistant = session.messages[1]
    kinds = [p.type for p in assistant.parts]
    assert kinds.count("reasoning") == 1
    assert kinds.count("tool") == 2
    assert "patch" in kinds
    assert kinds.index("text") > kinds.index("patch")


def test_tool_output_is_attached_to_its_call(settings):
    session = CodexProvider(settings).load_session(MAIN_ID)
    tools = [p for m in session.messages for p in m.parts if p.type == "tool"]
    shell = next(t for t in tools if t.name == "shell")
    assert shell.call_id == "call_1"
    assert shell.input == {"command": ["rg", "-n", "def create_charge", "src"]}
    assert "charges.py:42" in (shell.output or "")
    assert shell.status == "completed"
    assert shell.metadata and shell.metadata["exit_code"] == 0


def test_token_usage_comes_from_the_event_log(settings):
    session = CodexProvider(settings).load_session(MAIN_ID)
    assert session.summary.tokens is not None
    assert session.summary.tokens.input == 18432
    assert session.summary.tokens.output == 2110
    assert session.summary.tokens.cache_read == 12000


def test_assistant_text_is_not_duplicated_by_the_event_log(settings):
    """response_item and event_msg both carry the reply; only one must render."""
    session = CodexProvider(settings).load_session(MAIN_ID)
    texts = [p.text for m in session.messages for p in m.parts if p.type == "text"]
    assert len([t for t in texts if "Idempotency-Key" in t]) == 1


def test_unknown_item_type_is_kept_not_dropped(settings):
    session = CodexProvider(settings).load_session(MAIN_ID)
    unknown = [p for m in session.messages for p in m.parts if p.type == "unknown"]
    assert [p.kind for p in unknown] == ["future_item_kind"]


def test_truncated_line_degrades_to_a_warning(settings):
    session = CodexProvider(settings).load_session(BROKEN_ID)
    assert session.summary.parse_status == "partial"
    assert session.warnings
    assert [m.role for m in session.messages] == ["user"]


def test_title_falls_back_to_the_first_user_message(settings):
    session = CodexProvider(settings).load_session(MAIN_ID)
    assert session.summary.title is not None
    assert session.summary.title.startswith("Payments can be charged twice")


def test_resume_command_is_offered_but_never_run(settings):
    assert CodexProvider(settings).resume_command(MAIN_ID) == f"codex resume {MAIN_ID}"
