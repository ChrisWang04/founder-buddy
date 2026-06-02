"""Integration tests for the SSE /chat/stream endpoint."""

import asyncio

from tests.conftest import (
    answer_n_questions,
    collect_sse_events,
    drive_through_welcome,
)


# Total Q&A questions across all sections: 1+2+2+2+2+2 = 11
# Mapping returns {} so all 11 must be answered.
TOTAL_QUESTIONS = 11


# ─── Q&A turn: no tokens, single done event ───────────────────────────────────


class TestStreamQATurn:
    def test_qa_turn_yields_done_only(self, test_app, stub_llm):
        """When the resumed step is a non-generate_bp node, no token events
        should be forwarded — only the final `done` event."""
        session_id = drive_through_welcome(test_app, stub_llm)
        # Now positioned at problem Q1. Stream the answer.
        events = collect_sse_events(
            test_app,
            "/chat/stream",
            {"session_id": session_id, "message": "my problem"},
        )

        token_events = [e for e in events if e.get("type") == "token"]
        done_events = [e for e in events if e.get("type") == "done"]

        assert token_events == []
        assert len(done_events) == 1
        assert done_events[0]["is_done"] is False
        assert done_events[0]["business_plan"] is None
        # Next interrupt is product Q1
        assert done_events[0]["agent_message"] is not None

    def test_stream_404_for_unknown_session(self, test_app):
        events = collect_sse_events(
            test_app,
            "/chat/stream",
            {"session_id": "unknown", "message": "x"},
        )
        # collect_sse_events returns a status sentinel on non-200
        assert len(events) == 1
        assert events[0]["_status"] == 404


# ─── BP generation turn: tokens then done ─────────────────────────────────────


class TestStreamBPGeneration:
    def test_bp_streams_tokens_then_done(self, test_app, stub_llm):
        session_id = drive_through_welcome(test_app, stub_llm)
        # Answer all but the last question via /chat/message
        answer_n_questions(test_app, session_id, TOTAL_QUESTIONS - 1)

        # Queue the BP chunks for the upcoming astream
        bp_chunks = ["Executive Summary: ", "Coffee shop concept. ", "X" * 250]
        stub_llm.stream_chunks.append(bp_chunks)

        # Last answer via /chat/stream — triggers generate_bp + edit interrupt
        events = collect_sse_events(
            test_app,
            "/chat/stream",
            {"session_id": session_id, "message": "final answer"},
        )

        token_events = [e for e in events if e.get("type") == "token"]
        done_events = [e for e in events if e.get("type") == "done"]

        # Tokens should match what we queued
        assert len(token_events) == len(bp_chunks)
        joined = "".join(e["content"] for e in token_events)
        assert joined == "".join(bp_chunks)

        # Exactly one done event with BP + edit prompt
        assert len(done_events) == 1
        done = done_events[0]
        assert done["is_done"] is True
        assert done["business_plan"].startswith("Executive Summary:")
        assert "edit" in (done["agent_message"] or "").lower()


# ─── Error handling ──────────────────────────────────────────────────────────


class TestStreamErrorHandling:
    def test_error_during_stream_yields_error_event(
        self, test_app, stub_llm, monkeypatch
    ):
        """If the graph raises during execution, the stream should yield an
        `error` SSE event and close cleanly (no crash)."""
        session_id = drive_through_welcome(test_app, stub_llm)
        answer_n_questions(test_app, session_id, TOTAL_QUESTIONS - 1)

        # Force the LLM's _stream to raise
        def boom(*_args, **_kwargs):
            raise RuntimeError("LLM blew up")

        monkeypatch.setattr(stub_llm, "_stream", boom)

        events = collect_sse_events(
            test_app,
            "/chat/stream",
            {"session_id": session_id, "message": "final"},
        )

        error_events = [e for e in events if e.get("type") == "error"]
        done_events = [e for e in events if e.get("type") == "done"]

        assert len(error_events) == 1
        assert "Generation failed" in error_events[0]["detail"]
        # No done event when stream errored out
        assert done_events == []


# ─── DB persistence after stream ──────────────────────────────────────────────


class TestPersistStreamErrorHandling:
    def test_exception_in_persist_does_not_crash(self, monkeypatch):
        """_persist_stream swallows any exception so the stream remains intact."""
        import server

        def boom(*_args, **_kwargs):
            raise RuntimeError("supabase down")

        # Force get_conversation to raise — must be caught
        monkeypatch.setattr(server, "get_conversation", boom)

        # Direct call to the helper
        async def _run():
            await server._persist_stream(
                "session-x",
                "user msg",
                server.ChatResponse(
                    session_id="session-x",
                    agent_message=None,
                    is_done=True,
                    section_status={},
                    business_plan=None,
                ),
            )

        import asyncio

        # Should NOT raise
        asyncio.get_event_loop().run_until_complete(_run()) if False else None
        # Use a fresh loop for portability
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


class TestStreamPersistence:
    def test_persists_messages_and_bp_after_stream(
        self, test_app, stub_llm, mock_supabase, fake_jwt
    ):
        headers = {"Authorization": f"Bearer {fake_jwt}"}
        # Start with auth so a Supabase conversation row is created
        test_app.post("/chat/start", json={"message": "test idea"}, headers=headers)
        # Drive to BP gen — collect session_id from the recorded conversation
        session_id = mock_supabase["conversations"][0]["session_id"]
        # Resume welcome
        test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": "yes"},
            headers=headers,
        )
        # Answer through Q&A
        for _ in range(TOTAL_QUESTIONS - 1):
            test_app.post(
                "/chat/message",
                json={"session_id": session_id, "message": "ok"},
                headers=headers,
            )

        stub_llm.stream_chunks.append(["BP CONTENT " * 30])  # > 200 chars

        events = collect_sse_events(
            test_app,
            "/chat/stream",
            {"session_id": session_id, "message": "final"},
            headers=headers,
        )

        # Done event arrived
        assert any(e.get("type") == "done" for e in events)

        # _persist_stream is fire-and-forget via asyncio.ensure_future.
        # Let the event loop run pending tasks before asserting.
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.sleep(0.05))
        loop.close()

        # User "final" message + assistant edit prompt should be saved
        roles = [m["role"] for m in mock_supabase["messages"]]
        assert "user" in roles
        assert "assistant" in roles
        # Business plan should be saved
        assert len(mock_supabase["business_plans"]) == 1
        assert "BP CONTENT" in mock_supabase["business_plans"][0]["content"]
