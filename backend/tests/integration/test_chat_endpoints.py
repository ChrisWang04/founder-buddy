"""Integration tests for JSON HTTP endpoints."""

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from tests.conftest import complete_section_call


class TestHealth:
    def test_returns_ok(self, test_app):
        assert test_app.get("/health").json() == {"status": "ok"}


class TestChatStart:
    def test_creates_session_and_returns_agent_message(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("What problem are you solving?")
        resp = test_app.post("/chat/start", json={"message": "coffee shop"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"].startswith("session-")
        assert data["agent_message"] == "What problem are you solving?"
        assert data["is_done"] is False

    def test_uses_provided_session_id(self, test_app, stub_llm):
        resp = test_app.post("/chat/start", json={"message": "x", "session_id": "my-thread"})
        assert resp.json()["session_id"] == "my-thread"

    def test_persists_to_supabase_when_authenticated(
        self, test_app, stub_llm, mock_supabase, fake_jwt
    ):
        stub_llm.invoke_responses.append("Q?")
        test_app.post(
            "/chat/start",
            json={"message": "coffee shop"},
            headers={"Authorization": f"Bearer {fake_jwt}"},
        )
        assert len(mock_supabase["conversations"]) == 1
        assert mock_supabase["conversations"][0]["user_id"] == "test-user-id"
        assert len(mock_supabase["messages"]) == 2
        assert mock_supabase["messages"][0]["role"] == "user"
        assert mock_supabase["messages"][1]["role"] == "assistant"

    def test_skips_supabase_without_auth(self, test_app, stub_llm, mock_supabase):
        test_app.post("/chat/start", json={"message": "x"})
        assert len(mock_supabase["conversations"]) == 0


class TestChatMessage:
    def test_resumes_existing_session(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Tell me about the problem.")
        start = test_app.post("/chat/start", json={"message": "coffee shop"})
        session_id = start.json()["session_id"]

        stub_llm.invoke_responses.append("Got it! What is your product?")
        resp = test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": "no good coffee nearby"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent_message"] == "Got it! What is your product?"

    def test_returns_404_for_unknown_session(self, test_app):
        resp = test_app.post(
            "/chat/message",
            json={"session_id": "does-not-exist", "message": "x"},
        )
        assert resp.status_code == 404

    def test_tool_call_advances_section(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Tell me about the problem.")
        start = test_app.post("/chat/start", json={"message": "hi"})
        session_id = start.json()["session_id"]

        # LLM calls complete_section → advances to product
        stub_llm.invoke_responses.append(complete_section_call("no good coffee"))
        stub_llm.invoke_responses.append("Now tell me about your product.")
        resp = test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": "there's no good coffee"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["section_status"]["problem"] == "done"
        assert data["agent_message"] == "Now tell me about your product."


class TestChatState:
    def test_returns_current_state(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Pending question?")
        start = test_app.post("/chat/start", json={"message": "x"})
        session_id = start.json()["session_id"]

        resp = test_app.get(f"/chat/state?session_id={session_id}")
        assert resp.status_code == 200
        assert resp.json()["agent_message"] == "Pending question?"

    def test_returns_404_for_unknown_session(self, test_app):
        assert test_app.get("/chat/state?session_id=missing").status_code == 404


class TestChatMessages:
    def test_returns_persisted_messages(
        self, test_app, stub_llm, mock_supabase, fake_jwt
    ):
        stub_llm.invoke_responses.append("Q?")
        start = test_app.post(
            "/chat/start",
            json={"message": "coffee shop"},
            headers={"Authorization": f"Bearer {fake_jwt}"},
        )
        session_id = start.json()["session_id"]

        resp = test_app.get(f"/chat/messages?session_id={session_id}")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"

    def test_returns_404_when_no_conversation(self, test_app, mock_supabase):
        assert test_app.get("/chat/messages?session_id=no-conv").status_code == 404


class TestRequireGraph:
    def test_503_when_graph_not_initialized(self, monkeypatch, mock_supabase):
        import server

        @asynccontextmanager
        async def noop_lifespan(app):
            yield

        monkeypatch.setattr(server.app.router, "lifespan_context", noop_lifespan)
        monkeypatch.setattr(server, "graph", None)

        with TestClient(server.app) as client:
            assert client.post("/chat/start", json={"message": "x"}).status_code == 503
            assert client.post(
                "/chat/message", json={"session_id": "x", "message": "x"}
            ).status_code == 503
