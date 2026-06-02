"""Shared test fixtures.

Env vars are set BEFORE any backend module is imported, so the module-level
ChatAnthropic() and supabase create_client() calls don't fail.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

from contextlib import asynccontextmanager
from typing import Any, List

import jwt as pyjwt
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from pydantic import Field


# ─── Stub LLM ─────────────────────────────────────────────────────────────────


class StubChatModel(BaseChatModel):
    """In-process LLM that returns scripted responses.

    Tests push strings onto `invoke_responses` for sync .invoke() calls and
    lists of chunks onto `stream_chunks` for .astream() calls. Both queues
    pop FIFO. If a queue is empty, a default response is used.

    Extends BaseChatModel so LangGraph's astream_events emits the standard
    `on_chat_model_stream` events that the SSE filter looks for.
    """

    invoke_responses: List[str] = Field(default_factory=list)
    stream_chunks: List[List[str]] = Field(default_factory=list)
    invoke_calls: List[Any] = Field(default_factory=list)
    stream_calls: List[Any] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.invoke_calls.append(messages)
        content = self.invoke_responses.pop(0) if self.invoke_responses else "stub-response"
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.stream_calls.append(messages)
        chunks = self.stream_chunks.pop(0) if self.stream_chunks else ["stub-stream"]
        for c in chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=c))

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace agent.llm with a fresh StubChatModel for the test."""
    import agent

    stub = StubChatModel()
    monkeypatch.setattr(agent, "llm", stub)
    return stub


# ─── In-memory compiled graph ─────────────────────────────────────────────────


@pytest.fixture
def memory_graph(stub_llm):
    """Compile the LangGraph builder against MemorySaver (no PostgreSQL)."""
    import agent

    return agent.builder.compile(checkpointer=MemorySaver())


# ─── Mock Supabase ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_supabase(monkeypatch):
    """Replace backend.db functions with in-memory dict storage.

    Returns the storage dict so tests can assert on what was persisted.
    Patches the names on both the db module and the server module, since
    server imports them by name with `from db import ...`.
    """
    storage: dict = {
        "conversations": [],
        "messages": [],
        "business_plans": [],
    }

    def fake_create_conversation(user_id, session_id):
        conv = {
            "id": len(storage["conversations"]) + 1,
            "user_id": user_id,
            "session_id": session_id,
        }
        storage["conversations"].append(conv)
        return conv

    def fake_get_conversation(session_id):
        for c in storage["conversations"]:
            if c["session_id"] == session_id:
                return c
        return None

    def fake_save_business_plan(conv_id, content):
        for bp in storage["business_plans"]:
            if bp["conversation_id"] == conv_id:
                bp["content"] = content
                return bp
        bp = {
            "id": len(storage["business_plans"]) + 1,
            "conversation_id": conv_id,
            "content": content,
        }
        storage["business_plans"].append(bp)
        return bp

    def fake_save_message(conv_id, role, content):
        msg = {
            "id": len(storage["messages"]) + 1,
            "conversation_id": conv_id,
            "role": role,
            "content": content,
        }
        storage["messages"].append(msg)
        return msg

    def fake_get_messages(conv_id):
        return [m for m in storage["messages"] if m["conversation_id"] == conv_id]

    import db
    import server

    for mod in (db, server):
        monkeypatch.setattr(mod, "create_conversation", fake_create_conversation, raising=False)
        monkeypatch.setattr(mod, "get_conversation", fake_get_conversation, raising=False)
        monkeypatch.setattr(mod, "save_business_plan", fake_save_business_plan, raising=False)
        monkeypatch.setattr(mod, "save_message", fake_save_message, raising=False)
        monkeypatch.setattr(mod, "get_messages", fake_get_messages, raising=False)

    return storage


# ─── FastAPI TestClient with in-memory graph ──────────────────────────────────


@pytest.fixture
def test_app(memory_graph, mock_supabase, monkeypatch):
    """TestClient that bypasses the real lifespan (no PostgreSQL connection)."""
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
    """Unsigned JWT with a `sub` claim. server.get_user_id() skips signature verification."""
    return pyjwt.encode({"sub": "test-user-id"}, "secret", algorithm="HS256")


# ─── SSE helpers ──────────────────────────────────────────────────────────────


def collect_sse_events(client, url: str, json_payload: dict, headers: dict | None = None) -> list[dict]:
    """POST to an SSE endpoint and return the parsed event list.

    Mirrors the frontend parser: split on `\\n\\n`, strip `data: ` prefix,
    json.loads the payload.
    """
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


def drive_through_welcome(client, stub_llm, message: str = "test idea") -> str:
    """Start a new session and resume past the welcome phase.

    Returns the session_id positioned at the first problem question interrupt.
    The stub LLM uses default responses (mapping returns {} → no auto-fill).
    """
    start = client.post("/chat/start", json={"message": message})
    session_id = start.json()["session_id"]
    # Resume with "yes" to clear welcome and land on first section question
    client.post("/chat/message", json={"session_id": session_id, "message": "yes"})
    return session_id


def answer_n_questions(client, session_id: str, count: int, answer: str = "ok") -> None:
    """Send `count` /chat/message turns to advance through section questions."""
    for _ in range(count):
        client.post(
            "/chat/message",
            json={"session_id": session_id, "message": answer},
        )
