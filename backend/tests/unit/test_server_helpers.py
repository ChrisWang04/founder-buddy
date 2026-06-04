"""Unit tests for HTTP-layer helpers in server.py."""

from dataclasses import dataclass, field
from typing import List

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from server import (
    build_response,
    get_business_plan,
    get_last_assistant_message,
    get_user_id,
)


# ─── Mock state snapshot ─────────────────────────────────────────────────────


@dataclass
class _MockState:
    values: dict = field(default_factory=dict)


# ─── get_last_assistant_message ───────────────────────────────────────────────


class TestGetLastAssistantMessage:
    def test_returns_last_text_ai_message(self):
        state = _MockState(values={"messages": [
            HumanMessage(content="hi"),
            AIMessage(content="Hello! What problem are you solving?"),
        ]})
        assert get_last_assistant_message(state) == "Hello! What problem are you solving?"

    def test_skips_tool_call_messages(self):
        state = _MockState(values={"messages": [
            AIMessage(content="", tool_calls=[{"name": "complete_section", "args": {}, "id": "1", "type": "tool_call"}]),
            AIMessage(content="Great! Now tell me about your product."),
        ]})
        assert get_last_assistant_message(state) == "Great! Now tell me about your product."

    def test_returns_none_when_only_tool_calls(self):
        state = _MockState(values={"messages": [
            AIMessage(content="", tool_calls=[{"name": "complete_section", "args": {}, "id": "1", "type": "tool_call"}]),
        ]})
        assert get_last_assistant_message(state) is None

    def test_returns_none_when_no_messages(self):
        assert get_last_assistant_message(_MockState(values={"messages": []})) is None

    def test_ignores_human_messages(self):
        state = _MockState(values={"messages": [HumanMessage(content="hi")]})
        assert get_last_assistant_message(state) is None

    def test_returns_latest_when_multiple_text_messages(self):
        state = _MockState(values={"messages": [
            AIMessage(content="first"),
            AIMessage(content="second"),
        ]})
        assert get_last_assistant_message(state) == "second"

    def test_skips_empty_content_ai_messages(self):
        state = _MockState(values={"messages": [
            AIMessage(content="real content"),
            AIMessage(content=""),
        ]})
        assert get_last_assistant_message(state) == "real content"


# ─── get_business_plan ────────────────────────────────────────────────────────


class TestGetBusinessPlan:
    def test_finds_long_ai_message(self):
        long_bp = "B" * 250
        state = _MockState(values={"messages": [AIMessage(content=long_bp)]})
        assert get_business_plan(state) == long_bp

    def test_ignores_short_messages(self):
        state = _MockState(values={"messages": [AIMessage(content="short")]})
        assert get_business_plan(state) is None

    def test_ignores_tool_call_messages(self):
        state = _MockState(values={"messages": [
            AIMessage(content="B" * 250, tool_calls=[{"name": "x", "args": {}, "id": "1", "type": "tool_call"}]),
        ]})
        assert get_business_plan(state) is None

    def test_boundary_at_200_chars(self):
        state = _MockState(values={"messages": [AIMessage(content="A" * 200)]})
        assert get_business_plan(state) is None
        state = _MockState(values={"messages": [AIMessage(content="A" * 201)]})
        assert get_business_plan(state) == "A" * 201

    def test_returns_latest_long_message(self):
        state = _MockState(values={"messages": [
            AIMessage(content="F" * 250),
            AIMessage(content="S" * 250),
        ]})
        assert get_business_plan(state) == "S" * 250


# ─── build_response ───────────────────────────────────────────────────────────


class TestBuildResponse:
    def test_qa_phase_not_done(self):
        state = _MockState(values={
            "messages": [AIMessage(content="What problem are you solving?")],
            "current_section": "problem",
            "section_status": {"problem": "in_progress"},
        })
        resp = build_response("s1", state)
        assert resp.is_done is False
        assert resp.agent_message == "What problem are you solving?"
        assert resp.business_plan is None

    def test_done_phase_returns_bp(self):
        long_bp = "C" * 250
        state = _MockState(values={
            "messages": [AIMessage(content=long_bp)],
            "current_section": "done",
            "section_status": {},
        })
        resp = build_response("s1", state)
        assert resp.is_done is True
        assert resp.business_plan == long_bp

    def test_not_done_when_section_not_done(self):
        state = _MockState(values={
            "messages": [],
            "current_section": "features",
            "section_status": {},
        })
        resp = build_response("s1", state)
        assert resp.is_done is False
        assert resp.business_plan is None

    def test_section_status_passed_through(self):
        status = {"problem": "done", "product": "in_progress"}
        state = _MockState(values={
            "messages": [],
            "current_section": "product",
            "section_status": status,
        })
        resp = build_response("s1", state)
        assert resp.section_status == status


# ─── get_user_id ──────────────────────────────────────────────────────────────


class TestGetUserId:
    def test_extracts_sub_from_valid_bearer(self, fake_jwt):
        assert get_user_id(f"Bearer {fake_jwt}") == "test-user-id"

    def test_none_when_header_missing(self):
        assert get_user_id(None) is None

    def test_none_when_missing_bearer_prefix(self, fake_jwt):
        assert get_user_id(fake_jwt) is None

    def test_none_when_wrong_scheme(self, fake_jwt):
        assert get_user_id(f"Basic {fake_jwt}") is None

    def test_none_when_token_is_garbage(self):
        assert get_user_id("Bearer not-a-jwt") is None

    def test_none_when_no_sub_claim(self):
        token = pyjwt.encode({"email": "x@y.z"}, "secret", algorithm="HS256")
        assert get_user_id(f"Bearer {token}") is None

    def test_empty_string_header(self):
        assert get_user_id("") is None


import jwt as pyjwt
