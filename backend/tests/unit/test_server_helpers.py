"""Unit tests for HTTP-layer helpers in server.py."""

from dataclasses import dataclass, field
from typing import Any, List

from langchain_core.messages import AIMessage, HumanMessage

from server import (
    build_response,
    get_business_plan,
    get_interrupt_message,
    get_user_id,
)


# ─── Test doubles for LangGraph's StateSnapshot ───────────────────────────────


@dataclass
class _MockInterrupt:
    value: Any


@dataclass
class _MockTask:
    interrupts: List[_MockInterrupt] = field(default_factory=list)


@dataclass
class _MockState:
    tasks: List[_MockTask] = field(default_factory=list)
    values: dict = field(default_factory=dict)


# ─── get_interrupt_message ────────────────────────────────────────────────────


class TestGetInterruptMessage:
    def test_returns_last_interrupt_value(self):
        state = _MockState(tasks=[_MockTask([
            _MockInterrupt("first"),
            _MockInterrupt("last"),
        ])])
        assert get_interrupt_message(state) == "last"

    def test_returns_single_interrupt(self):
        state = _MockState(tasks=[_MockTask([_MockInterrupt("only")])])
        assert get_interrupt_message(state) == "only"

    def test_returns_none_when_no_tasks(self):
        state = _MockState(tasks=[])
        assert get_interrupt_message(state) is None

    def test_returns_none_when_task_has_no_interrupts(self):
        state = _MockState(tasks=[_MockTask([])])
        assert get_interrupt_message(state) is None


# ─── get_business_plan ────────────────────────────────────────────────────────


class TestGetBusinessPlan:
    def test_finds_long_ai_message(self):
        long_content = "A" * 250
        state = _MockState(values={"messages": [
            HumanMessage(content="hi"),
            AIMessage(content=long_content),
        ]})
        assert get_business_plan(state) == long_content

    def test_ignores_short_ai_message(self):
        state = _MockState(values={"messages": [AIMessage(content="short reply")]})
        assert get_business_plan(state) is None

    def test_ignores_long_human_message(self):
        state = _MockState(values={"messages": [HumanMessage(content="A" * 500)]})
        assert get_business_plan(state) is None

    def test_returns_latest_ai_message(self):
        first = "F" * 250
        second = "S" * 250
        state = _MockState(values={"messages": [
            AIMessage(content=first),
            HumanMessage(content="edit"),
            AIMessage(content=second),
        ]})
        assert get_business_plan(state) == second

    def test_returns_none_when_no_messages(self):
        state = _MockState(values={"messages": []})
        assert get_business_plan(state) is None

    def test_boundary_at_200_chars(self):
        # exactly 200 chars → NOT a BP (strict >, not >=)
        state = _MockState(values={"messages": [AIMessage(content="A" * 200)]})
        assert get_business_plan(state) is None

        state = _MockState(values={"messages": [AIMessage(content="A" * 201)]})
        assert get_business_plan(state) == "A" * 201


# ─── build_response ───────────────────────────────────────────────────────────


class TestBuildResponse:
    def test_qa_phase(self):
        state = _MockState(
            tasks=[_MockTask([_MockInterrupt("What's your idea?")])],
            values={
                "current_section": "problem",
                "section_status": {"problem": "in_progress"},
            },
        )
        resp = build_response("s1", state)

        assert resp.session_id == "s1"
        assert resp.agent_message == "What's your idea?"
        assert resp.is_done is False
        assert resp.business_plan is None
        assert resp.section_status == {"problem": "in_progress"}

    def test_edit_phase_returns_done_with_plan_and_message(self):
        long_bp = "B" * 250
        state = _MockState(
            tasks=[_MockTask([_MockInterrupt("Edit anything?")])],
            values={
                "current_section": "done",
                "messages": [AIMessage(content=long_bp)],
                "section_status": {"problem": "done"},
            },
        )
        resp = build_response("s1", state)

        assert resp.agent_message == "Edit anything?"
        assert resp.is_done is True
        assert resp.business_plan == long_bp

    def test_truly_complete_no_interrupt(self):
        state = _MockState(
            tasks=[],
            values={"current_section": "done", "section_status": {}},
        )
        resp = build_response("s1", state)

        assert resp.agent_message is None
        assert resp.is_done is True
        assert resp.business_plan is None  # no AI message

    def test_degenerate_state_no_interrupt_and_not_done(self):
        """No interrupt, current_section != 'done': interrupt_msg is None
        forces is_done True via the OR-shortcut, even though plan_ready_for_edit
        is False. Isolates the (False, False) case of the plan_ready_for_edit and-clause."""
        state = _MockState(
            tasks=[],
            values={"current_section": "problem", "section_status": {}},
        )
        resp = build_response("s1", state)
        assert resp.is_done is True  # interrupt_msg is None branch
        assert resp.agent_message is None

    def test_qa_phase_omits_business_plan_even_if_present(self):
        # In Q&A phase (is_done=False), business_plan should not be returned
        long_msg = "X" * 250
        state = _MockState(
            tasks=[_MockTask([_MockInterrupt("Next question?")])],
            values={
                "current_section": "problem",
                "messages": [AIMessage(content=long_msg)],
            },
        )
        resp = build_response("s1", state)
        assert resp.is_done is False
        assert resp.business_plan is None


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

    def test_none_when_token_has_no_sub_claim(self):
        import jwt as pyjwt

        token = pyjwt.encode({"email": "x@y.z"}, "secret", algorithm="HS256")
        assert get_user_id(f"Bearer {token}") is None

    def test_empty_authorization_header(self):
        assert get_user_id("") is None
