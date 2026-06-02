"""Integration tests for the JSON HTTP endpoints.

Covers /health, /chat/start, /chat/message, /chat/state, /chat/messages, and
the require_graph() 503 path. SSE-specific tests live in test_chat_stream.py.
"""

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient


# ─── /health ──────────────────────────────────────────────────────────────────


class TestHealth:
    def test_returns_ok(self, test_app):
        response = test_app.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ─── /chat/start ──────────────────────────────────────────────────────────────


class TestChatStart:
    def test_creates_session_and_returns_pending_question(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Tell me more about your idea")
        response = test_app.post("/chat/start", json={"message": "coffee shop"})

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"].startswith("session-")
        assert data["agent_message"] == "Tell me more about your idea"
        assert data["is_done"] is False
        assert data["business_plan"] is None

    def test_uses_provided_session_id(self, test_app, stub_llm):
        response = test_app.post(
            "/chat/start",
            json={"message": "x", "session_id": "custom-thread-42"},
        )
        assert response.json()["session_id"] == "custom-thread-42"

    def test_persists_to_supabase_when_authenticated(
        self, test_app, stub_llm, mock_supabase, fake_jwt
    ):
        stub_llm.invoke_responses.append("Q?")
        response = test_app.post(
            "/chat/start",
            json={"message": "coffee shop"},
            headers={"Authorization": f"Bearer {fake_jwt}"},
        )

        assert response.status_code == 200
        assert len(mock_supabase["conversations"]) == 1
        assert mock_supabase["conversations"][0]["user_id"] == "test-user-id"
        # user message + agent reply persisted
        assert len(mock_supabase["messages"]) == 2
        assert mock_supabase["messages"][0]["role"] == "user"
        assert mock_supabase["messages"][0]["content"] == "coffee shop"
        assert mock_supabase["messages"][1]["role"] == "assistant"
        assert mock_supabase["messages"][1]["content"] == "Q?"

    def test_skips_supabase_persistence_without_auth(
        self, test_app, stub_llm, mock_supabase
    ):
        test_app.post("/chat/start", json={"message": "x"})
        assert len(mock_supabase["conversations"]) == 0
        assert len(mock_supabase["messages"]) == 0


# ─── /chat/message ────────────────────────────────────────────────────────────


class TestChatMessage:
    def test_resumes_existing_session(self, test_app, stub_llm):
        start = test_app.post("/chat/start", json={"message": "coffee shop"})
        session_id = start.json()["session_id"]

        # Resume with "yes" — advances welcome → first section question
        resp = test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": "yes"},
        )

        assert resp.status_code == 200
        data = resp.json()
        # section_node interrupt should be the first problem question
        assert "What problem" in (data["agent_message"] or "")
        assert data["is_done"] is False

    def test_returns_404_for_unknown_session(self, test_app):
        resp = test_app.post(
            "/chat/message",
            json={"session_id": "does-not-exist", "message": "x"},
        )
        assert resp.status_code == 404
        assert "Session not found" in resp.json()["detail"]


# ─── /chat/state ──────────────────────────────────────────────────────────────


class TestChatState:
    def test_returns_current_state(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Pending question?")
        start = test_app.post("/chat/start", json={"message": "x"})
        session_id = start.json()["session_id"]

        state_resp = test_app.get(f"/chat/state?session_id={session_id}")

        assert state_resp.status_code == 200
        data = state_resp.json()
        assert data["agent_message"] == "Pending question?"
        assert data["session_id"] == session_id

    def test_returns_404_for_unknown_session(self, test_app):
        resp = test_app.get("/chat/state?session_id=missing")
        assert resp.status_code == 404


# ─── /chat/messages ───────────────────────────────────────────────────────────


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
        messages = resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "coffee shop"
        assert messages[1]["role"] == "assistant"

    def test_returns_404_when_conversation_missing(self, test_app, mock_supabase):
        # No conversation persisted → 404
        resp = test_app.get("/chat/messages?session_id=no-conv-here")
        assert resp.status_code == 404


# ─── require_graph 503 path ───────────────────────────────────────────────────


class TestRequireGraph:
    def test_503_when_graph_not_initialized(self, monkeypatch, mock_supabase):
        """When the lifespan hasn't compiled the graph yet, all routes 503."""
        import server

        @asynccontextmanager
        async def noop_lifespan(app):
            yield

        monkeypatch.setattr(server.app.router, "lifespan_context", noop_lifespan)
        monkeypatch.setattr(server, "graph", None)

        with TestClient(server.app) as client:
            resp = client.post("/chat/start", json={"message": "x"})
            assert resp.status_code == 503
            assert "starting up" in resp.json()["detail"].lower()

            resp = client.post(
                "/chat/message", json={"session_id": "x", "message": "x"}
            )
            assert resp.status_code == 503
