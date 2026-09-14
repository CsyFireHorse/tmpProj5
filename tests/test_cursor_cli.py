from __future__ import annotations

import hashlib

from agent_chat_viewer.adapters.cursor_cli import CursorCliProvider

KNOWN = "7a5f1c2e-4b3d-4e6f-8a9b-0c1d2e3f4a5b"
UNKNOWN = "8b6a2d3f-5c4e-4f70-9bac-1d2e3f4a5b6c"


def test_sessions_are_discovered_across_workspace_buckets(settings):
    ids = {s.id for s in CursorCliProvider(settings).iter_sessions()}
    assert ids == {KNOWN, UNKNOWN}


def test_workspace_path_is_recovered_by_hashing_candidates(settings):
    """The bucket name is md5(path); it is matched, never reversed."""
    summary = next(s for s in CursorCliProvider(settings).iter_sessions() if s.id == KNOWN)
    assert summary.cwd == "/home/demo/projects/checkout-api"


def test_unmatched_workspace_is_surfaced_not_hidden(settings):
    summary = next(s for s in CursorCliProvider(settings).iter_sessions() if s.id == UNKNOWN)
    assert summary.cwd is None
    assert summary.project.startswith("md5:")


def test_title_and_model_come_from_meta_json_and_the_hex_record(settings):
    summary = next(s for s in CursorCliProvider(settings).iter_sessions() if s.id == KNOWN)
    assert summary.title == "Flaky integration test on CI"
    assert summary.model == "claude-4.5-sonnet"


def test_json_blobs_become_a_transcript(settings):
    session = CursorCliProvider(settings).load_session(KNOWN)
    assert [m.role for m in session.messages] == ["user", "assistant", "assistant"]
    assert "test_webhook_ordering" in session.messages[0].parts[0].text


def test_tool_result_is_folded_into_its_call(settings):
    session = CursorCliProvider(settings).load_session(KNOWN)
    tools = [p for m in session.messages for p in m.parts if p.type == "tool"]
    assert len(tools) == 1
    assert tools[0].name == "run_terminal_cmd"
    assert "1 failed, 23 passed" in (tools[0].output or "")


def test_binary_turn_graph_blobs_are_counted_not_decoded(settings):
    session = CursorCliProvider(settings).load_session(KNOWN)
    assert session.metadata["binary_blobs"] == 1
    assert any("protobuf" in note for note in session.notes)


def test_approximate_ordering_is_disclosed(settings):
    """Order comes from blob insertion, so the UI must be told it is a guess."""
    session = CursorCliProvider(settings).load_session(KNOWN)
    assert session.metadata["order_confidence"] == "approximate"
    assert any("approximate" in note for note in session.notes)


def test_unknown_workspace_can_be_bound_by_the_user(settings):
    provider = CursorCliProvider(settings)
    path = "/some/path/this/machine/never/saw"
    bucket = hashlib.md5(path.encode()).hexdigest()

    assert provider.bind_workspace(bucket, "/wrong/path") is False
    assert provider.bind_workspace(bucket, path) is True

    summary = next(s for s in provider.iter_sessions() if s.id == UNKNOWN)
    assert summary.cwd == path


def test_resume_command_includes_the_session_id(settings):
    assert CursorCliProvider(settings).resume_command(KNOWN) == f"cursor-agent --resume {KNOWN}"
