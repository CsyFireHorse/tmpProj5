from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_chat_viewer.main import create_app

CODEX_UID = "codex:0199a1f0-1111-7000-8000-000000000001"
CURSOR_CLI_UID = "cursor-cli:7a5f1c2e-4b3d-4e6f-8a9b-0c1d2e3f4a5b"


@pytest.fixture
def client(settings):
    app = create_app(settings, autoscan=False)
    with TestClient(app) as test_client:
        app.state.scanner.scan()
        yield test_client


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_providers_report_detection_per_store(client):
    statuses = {p["id"]: p for p in client.get("/api/providers").json()}
    assert set(statuses) == {"codex", "cursor-ide", "cursor-cli", "opencode"}
    assert all(status["detected"] for status in statuses.values())
    assert statuses["codex"]["session_count"] == 3


def test_all_four_providers_appear_in_one_list(client):
    page = client.get("/api/sessions", params={"limit": 100}).json()
    providers = {item["provider"] for item in page["items"]}
    assert providers == {"codex", "cursor-ide", "cursor-cli", "opencode"}
    assert page["total"] == len(page["items"]) == 9


def test_filter_by_provider(client):
    page = client.get("/api/sessions", params={"provider": ["codex"]}).json()
    assert {item["provider"] for item in page["items"]} == {"codex"}


def test_projects_group_across_providers(client):
    projects = {p["name"]: p for p in client.get("/api/projects").json()}
    checkout = projects["checkout-api"]
    assert set(checkout["providers"]) == {"codex", "cursor-cli", "cursor-ide"}


def test_session_detail_renders_parts(client):
    session = client.get(f"/api/sessions/{CODEX_UID}").json()
    assert session["summary"]["provider"] == "codex"
    kinds = [part["type"] for message in session["messages"] for part in message["parts"]]
    assert {"text", "reasoning", "tool", "patch", "unknown"} <= set(kinds)


def test_detail_omits_raw_payloads_by_default(client):
    session = client.get(f"/api/sessions/{CODEX_UID}").json()
    assert all(part["raw"] is None for m in session["messages"] for part in m["parts"])
    with_raw = client.get(f"/api/sessions/{CODEX_UID}", params={"raw": True}).json()
    assert any(part["raw"] is not None for m in with_raw["messages"] for part in m["parts"])


def test_raw_endpoint_returns_original_records(client):
    body = client.get(f"/api/sessions/{CODEX_UID}/raw").json()
    assert body["records"][0]["record"]["type"] == "session_meta"


def test_missing_session_is_404(client):
    assert client.get("/api/sessions/codex:does-not-exist").status_code == 404


def test_full_text_search_spans_providers(client):
    hits = client.get("/api/search", params={"q": "idempotency"}).json()
    assert hits["items"]
    assert hits["items"][0]["uid"] == CODEX_UID
    assert "<<" in hits["items"][0]["snippet"]

    cursor_hits = client.get("/api/search", params={"q": "webhook"}).json()
    assert {hit["provider"] for hit in cursor_hits["items"]} == {"cursor-cli"}


def test_search_tolerates_fts_operator_characters(client):
    """A stray quote or NEAR must not produce a 500."""
    for query in ['"', "AND", "foo* OR (", "size=(sm|md)"]:
        assert client.get("/api/search", params={"q": query}).status_code == 200


def test_list_query_matches_titles_and_message_text(client):
    page = client.get("/api/sessions", params={"q": "Safari"}).json()
    assert [item["provider"] for item in page["items"]] == ["cursor-ide"]


def test_markdown_export(client):
    response = client.get(f"/api/sessions/{CODEX_UID}/export", params={"format": "md"})
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("# ")
    assert "### User" in body and "### Assistant" in body
    assert "```diff" in body


def test_json_export_round_trips(client):
    body = client.get(f"/api/sessions/{CODEX_UID}/export", params={"format": "json"}).json()
    assert body["summary"]["id"].endswith("000000000001")


def test_resume_command_is_returned_with_the_workspace(client):
    body = client.get(f"/api/sessions/{CURSOR_CLI_UID}/resume-command").json()
    assert body["command"].startswith("cd /home/demo/projects/checkout-api && cursor-agent --resume")

    ide_uid = "cursor-ide:3f1c8c9e-0000-4a00-9000-composer0001"
    assert client.get(f"/api/sessions/{ide_uid}/resume-command").status_code == 404


def test_stats_aggregate_usage(client):
    stats = client.get("/api/stats").json()
    assert stats["total_sessions"] == 9
    assert stats["tokens_input"] > 0
    assert {bucket["key"] for bucket in stats["by_provider"]} == {
        "codex",
        "cursor-ide",
        "cursor-cli",
        "opencode",
    }


def test_subagent_sessions_are_linked(client):
    children = client.get(f"/api/sessions/{CODEX_UID}/children").json()
    assert [child["kind"] for child in children] == ["subagent"]


def test_reveal_refuses_paths_outside_the_detected_roots(client):
    response = client.post("/api/actions/reveal", json={"path": "/etc/passwd"})
    assert response.status_code == 403


def test_unparseable_session_is_listed_with_a_status(client):
    page = client.get("/api/sessions", params={"limit": 100}).json()
    statuses = {item["id"]: item["parse_status"] for item in page["items"]}
    assert statuses["0199a1f0-3333-7000-8000-000000000003"] == "partial"
