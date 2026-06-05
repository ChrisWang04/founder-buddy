"""Shared test fixtures for the agent-driven (ReAct) graph design."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

from contextlib import asynccontextmanager
from typing import Any, List

import json as _json

import jwt as pyjwt
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from pydantic import Field

from agent import SECTION_ORDER


# ─── Stub LLM ─────────────────────────────────────────────────────────────────


class StubChatModel(BaseChatModel):
    """Scripted LLM for tests.

    Push items onto `invoke_responses` before each test turn. Each item is
    popped FIFO and can be:
      - str  → plain AIMessage with that content
      - list → AIMessage with tool_calls (each element is a tool-call dict:
                {"name": ..., "args": {...}, "id": ..., "type": "tool_call"})

    `stream_chunks` is a list of lists: each inner list is the sequence of
    string chunks returned by one astream() call.
    """

    invoke_responses: List[Any] = Field(default_factory=list)
    stream_chunks: List[List[str]] = Field(default_factory=list)
    invoke_calls: List[Any] = Field(default_factory=list)
    stream_calls: List[Any] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.invoke_calls.append(messages)
        response = self.invoke_responses.pop(0) if self.invoke_responses else "stub-response"

        if isinstance(response, list):
            # Tool-call response
            msg = AIMessage(content="", tool_calls=response)
        else:
            msg = AIMessage(content=response)

        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        """astream_events routes through _stream instead of _generate.
        Use stream_chunks when set (for explicit streaming tests); otherwise
        fall back to invoke_responses so both endpoints share one queue."""
        self.stream_calls.append(messages)

        if self.stream_chunks:
            for c in self.stream_chunks.pop(0):
                yield ChatGenerationChunk(message=AIMessageChunk(content=c))
            return

        response = self.invoke_responses.pop(0) if self.invoke_responses else "stub-response"
        if isinstance(response, list):
            # Tool-call response — emit as a single chunk so tools_condition fires.
            # args must be a JSON string; type must be "tool_call_chunk".
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": tc["name"],
                            "args": _json.dumps(tc.get("args", {})),
                            "id": tc.get("id", f"tc_{tc['name']}"),
                            "index": i,
                            "type": "tool_call_chunk",
                        }
                        for i, tc in enumerate(response)
                    ],
                )
            )
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content=response))

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"


@pytest.fixture
def stub_llm(monkeypatch):
    import agent
    stub = StubChatModel()
    # llm → implementation_node (BP generation, Sonnet)
    # llm_qa / llm_with_tools → assistant_node (Q&A, Haiku)
    monkeypatch.setattr(agent, "llm", stub)
    monkeypatch.setattr(agent, "llm_qa", stub)
    monkeypatch.setattr(agent, "llm_with_tools", stub)
    return stub


# ─── Compiled graph with MemorySaver ──────────────────────────────────────────


@pytest.fixture
def memory_graph(stub_llm):
    import agent
    return agent.builder.compile(checkpointer=MemorySaver())


# ─── Mock Supabase ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_supabase(monkeypatch):
    storage: dict = {"conversations": [], "messages": [], "business_plans": []}

    def fake_create_conversation(user_id, session_id):
        conv = {"id": len(storage["conversations"]) + 1, "user_id": user_id, "session_id": session_id}
        storage["conversations"].append(conv)
        return conv

    def fake_get_conversation(session_id):
        return next((c for c in storage["conversations"] if c["session_id"] == session_id), None)

    def fake_save_business_plan(conv_id, content):
        for bp in storage["business_plans"]:
            if bp["conversation_id"] == conv_id:
                bp["content"] = content
                return bp
        bp = {"id": len(storage["business_plans"]) + 1, "conversation_id": conv_id, "content": content}
        storage["business_plans"].append(bp)
        return bp

    def fake_save_message(conv_id, role, content):
        msg = {"id": len(storage["messages"]) + 1, "conversation_id": conv_id, "role": role, "content": content}
        storage["messages"].append(msg)
        return msg

    def fake_get_messages(conv_id):
        return [m for m in storage["messages"] if m["conversation_id"] == conv_id]

    import db, server
    for mod in (db, server):
        monkeypatch.setattr(mod, "create_conversation", fake_create_conversation, raising=False)
        monkeypatch.setattr(mod, "get_conversation", fake_get_conversation, raising=False)
        monkeypatch.setattr(mod, "save_business_plan", fake_save_business_plan, raising=False)
        monkeypatch.setattr(mod, "save_message", fake_save_message, raising=False)
        monkeypatch.setattr(mod, "get_messages", fake_get_messages, raising=False)

    return storage


# ─── FastAPI TestClient ────────────────────────────────────────────────────────


@pytest.fixture
def test_app(memory_graph, mock_supabase, monkeypatch):
    from fastapi.testclient import TestClient
    import server

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    monkeypatch.setattr(server.app.router, "lifespan_context", noop_lifespan)
    monkeypatch.setattr(server, "graph", memory_graph)

    with TestClient(server.app) as client:
        yield client


# ─── JWT helper ───────────────────────────────────────────────────────────────


@pytest.fixture
def fake_jwt():
    return pyjwt.encode({"sub": "test-user-id"}, "secret", algorithm="HS256")


# ─── Tool-call response builders ──────────────────────────────────────────────


def make_tool_call(name: str, args: dict, call_id: str | None = None) -> dict:
    """Build a single tool-call dict for use in StubChatModel."""
    return {"name": name, "args": args, "id": call_id or f"tc_{name}", "type": "tool_call"}


def complete_section_call(content: str = "stub content", call_id: str | None = None) -> list:
    return [make_tool_call("complete_section", {"content": content}, call_id)]


def modify_section_call(section: str, call_id: str | None = None) -> list:
    return [make_tool_call("modify_section", {"section": section}, call_id)]


# ─── SSE helpers ──────────────────────────────────────────────────────────────


def collect_sse_events(client, url: str, json_payload: dict, headers: dict | None = None) -> list[dict]:
    import json as _json
    events: list[dict] = []
    buffer = ""
    with client.stream("POST", url, json=json_payload, headers=headers or {}) as response:
        if response.status_code != 200:
            return [{"_status": response.status_code, "_body": response.read().decode()}]
        for chunk in response.iter_bytes():
            buffer += chunk.decode("utf-8")
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                frame = frame.strip()
                if frame.startswith("data: "):
                    try:
                        events.append(_json.loads(frame[6:]))
                    except _json.JSONDecodeError:
                        pass
    return events


# ─── Graph-driving helpers ────────────────────────────────────────────────────


def drive_all_sections(client, stub_llm, session_id: str) -> None:
    """Drive through all 6 sections via /chat/message.

    Each section turn: assistant emits a complete_section tool call, then
    memory_updater routes back to assistant for a follow-up question.
    On the last section memory_updater routes to implementation_node instead,
    which needs a BP response (>200 chars) so build_response finds it.
    """
    for i, section in enumerate(SECTION_ORDER):
        stub_llm.invoke_responses.append(
            complete_section_call(content=f"{section} collected info")
        )
        if i < len(SECTION_ORDER) - 1:
            stub_llm.invoke_responses.append(f"Great! Now let's talk about {SECTION_ORDER[i + 1]}.")
        else:
            # Last section: memory_updater routes to implementation_node which calls llm.ainvoke()
            stub_llm.invoke_responses.append("Executive Summary\n\n" + "Business plan details. " * 15)

    client.post("/chat/message", json={"session_id": session_id, "message": "drive all sections"})
