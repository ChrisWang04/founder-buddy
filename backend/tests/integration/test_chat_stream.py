"""Integration tests for the SSE /chat/stream endpoint."""

import asyncio

from tests.conftest import (
    collect_sse_events,
    complete_section_call,
)


class TestStreamQATurn:
    def test_qa_turn_yields_done_with_agent_message(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Tell me about the problem.")
        start = test_app.post("/chat/start", json={"message": "coffee shop"})
        session_id = start.json()["session_id"]

        stub_llm.invoke_responses.append("What problem are you solving?")
        events = collect_sse_events(
            test_app, "/chat/stream",
            {"session_id": session_id, "message": "some answer"},
        )

        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1
        assert done[0]["agent_message"] == "What problem are you solving?"
        assert done[0]["is_done"] is False

    def test_404_for_unknown_session(self, test_app):
        events = collect_sse_events(
            test_app, "/chat/stream",
            {"session_id": "unknown", "message": "x"},
        )
        assert events[0]["_status"] == 404


class TestStreamSectionAdvance:
    def test_complete_section_tool_call_reflected_in_done_event(self, test_app, stub_llm):
        stub_llm.invoke_responses.append("Tell me about the problem.")
        start = test_app.post("/chat/start", json={"message": "hi"})
        session_id = start.json()["session_id"]

        # LLM calls complete_section then asks next question
        stub_llm.invoke_responses.append(complete_section_call("no good coffee"))
        stub_llm.invoke_responses.append("Now tell me about your product.")

        events = collect_sse_events(
            test_app, "/chat/stream",
            {"session_id": session_id, "message": "there's no good coffee"},
        )
        done = next(e for e in events if e.get("type") == "done")
        assert done["section_status"]["problem"] == "done"
        assert done["agent_message"] == "Now tell me about your product."


class TestStreamBPGeneration:
    def test_last_section_streams_bp_tokens_from_implementation(self, test_app, stub_llm):
        """Completing the final section via /chat/stream should trigger
        implementation_node, which emits bp_token events (not token events)."""
        stub_llm.invoke_responses.append("Tell me about the problem.")
        start = test_app.post("/chat/start", json={"message": "coffee shop"})
        session_id = start.json()["session_id"]

        from agent import SECTION_ORDER

        # Drive sections 1-5 via /chat/message (each: tool_call + text response)
        for i, section in enumerate(SECTION_ORDER[:-1]):
            stub_llm.invoke_responses.append(complete_section_call(f"{section} info"))
            stub_llm.invoke_responses.append(f"Now let's talk about {SECTION_ORDER[i+1]}.")
            test_app.post("/chat/message", json={"session_id": session_id, "message": f"answer for {section}"})

        # Final section via /chat/stream:
        #   assistant emits complete_section tool call (no token events)
        #   tools_node sets current_section="done"
        #   memory_updater routes to implementation_node
        #   implementation_node emits bp_token events
        bp_text = "Executive Summary\n\n" + "Business plan content. " * 15
        stub_llm.invoke_responses.append(complete_section_call("exit strategy info"))
        stub_llm.invoke_responses.append(bp_text)

        events = collect_sse_events(
            test_app, "/chat/stream",
            {"session_id": session_id, "message": "our exit is acquisition"},
        )

        bp_tokens = [e for e in events if e.get("type") == "bp_token"]
        token_events = [e for e in events if e.get("type") == "token"]
        done = [e for e in events if e.get("type") == "done"]

        assert len(bp_tokens) > 0, "implementation_node should emit bp_token events"
        assert len(token_events) == 0, "Q&A token events must not appear during BP generation"
        assert len(done) == 1
        assert done[0]["is_done"] is True
        assert done[0]["business_plan"] is not None


class TestStreamError:
    def test_error_in_graph_yields_error_event(self, test_app, stub_llm, monkeypatch):
        stub_llm.invoke_responses.append("Tell me about the problem.")
        start = test_app.post("/chat/start", json={"message": "hi"})
        session_id = start.json()["session_id"]

        def boom(*_args, **_kwargs):
            raise RuntimeError("LLM exploded")
            yield  # make it a generator so _stream signature is satisfied

        # astream_events routes through _stream, not _generate
        monkeypatch.setattr(stub_llm, "_stream", boom)

        events = collect_sse_events(
            test_app, "/chat/stream",
            {"session_id": session_id, "message": "answer"},
        )
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "Generation failed" in error_events[0]["detail"]


class TestStreamPersistence:
    def test_persist_stream_swallows_exception(self, monkeypatch):
        import server

        monkeypatch.setattr(server, "get_conversation", lambda *_: (_ for _ in ()).throw(RuntimeError("db down")))

        async def _run():
            await server._persist_stream(
                "s", "msg",
                server.ChatResponse(
                    session_id="s", agent_message=None,
                    is_done=False, section_status={}, business_plan=None,
                ),
            )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()
