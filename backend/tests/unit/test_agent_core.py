"""Unit tests for agent.py — tools_node state transitions, initialize_node, route_after_memory_updater."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent import (
    SECTION_ORDER,
    SECTION_LABELS,
    initialize_node,
    route_after_memory_updater,
    tools_node,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _base_state(**overrides):
    state = {
        "messages": [],
        "current_section": "problem",
        "last_completed_section": "",
        "section_status": {s: "pending" for s in SECTION_ORDER},
        "problem": "", "product": "", "features": "",
        "team_traction": "", "investment": "", "exit_strategy": "",
    }
    state.update(overrides)
    return state


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ai_tool(name: str, args: dict, call_id: str = "tc1") -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": call_id, "type": "tool_call"}
    ])


# ─── complete_section ────────────────────────────────────────────────────────


class TestCompleteSection:
    def test_saves_content_to_section_field(self):
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "no good coffee"})],
            current_section="problem",
        )
        result = tools_node(state)
        assert result["problem"] == "no good coffee"

    def test_marks_section_done_and_advances(self):
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "x"})],
            current_section="problem",
        )
        result = tools_node(state)
        assert result["section_status"]["problem"] == "done"
        assert result["current_section"] == "product"
        assert result["section_status"]["product"] == "in_progress"

    def test_does_not_mutate_input_section_status(self):
        original_status = {s: "pending" for s in SECTION_ORDER}
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "x"})],
            current_section="problem",
            section_status=original_status,
        )
        tools_node(state)
        assert original_status["problem"] == "pending"

    def test_last_section_sets_current_to_done(self):
        last = SECTION_ORDER[-1]
        status = {s: "done" for s in SECTION_ORDER}
        status[last] = "in_progress"
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "exit info"})],
            current_section=last,
            section_status=status,
        )
        result = tools_node(state)
        assert result["current_section"] == "done"
        assert result["section_status"][last] == "done"

    def test_returns_tool_message(self):
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "x"})],
            current_section="problem",
        )
        result = tools_node(state)
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], ToolMessage)
        assert "problem" in msgs[0].content.lower() or "Product" in msgs[0].content

    def test_invalid_section_returns_error_tool_message(self):
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "x"})],
            current_section="done",  # not in SECTION_ORDER
        )
        result = tools_node(state)
        assert "current_section" not in result  # state not changed
        assert "No active section" in result["messages"][0].content

    def test_advances_through_all_sections_sequentially(self):
        current = "problem"
        for i, section in enumerate(SECTION_ORDER):
            state = _base_state(
                messages=[_ai_tool("complete_section", {"content": "info"})],
                current_section=section,
                section_status={s: ("done" if j < i else "pending") for j, s in enumerate(SECTION_ORDER)},
            )
            result = tools_node(state)
            expected_next = SECTION_ORDER[i + 1] if i + 1 < len(SECTION_ORDER) else "done"
            assert result["current_section"] == expected_next

    def test_sets_last_completed_section(self):
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "x"})],
            current_section="problem",
        )
        result = tools_node(state)
        assert result["last_completed_section"] == "problem"

    def test_last_section_sets_last_completed_section(self):
        last = SECTION_ORDER[-1]
        status = {s: "done" for s in SECTION_ORDER}
        status[last] = "in_progress"
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "exit"})],
            current_section=last,
            section_status=status,
        )
        result = tools_node(state)
        assert result["last_completed_section"] == last


# ─── modify_section ───────────────────────────────────────────────────────────


class TestModifySection:
    def test_switches_to_target_section(self):
        state = _base_state(
            messages=[_ai_tool("modify_section", {"section": "product"})],
            current_section="features",
            section_status={s: "done" for s in SECTION_ORDER},
        )
        result = tools_node(state)
        assert result["current_section"] == "product"

    def test_marks_target_as_in_progress(self):
        state = _base_state(
            messages=[_ai_tool("modify_section", {"section": "product"})],
            section_status={s: "done" for s in SECTION_ORDER},
        )
        result = tools_node(state)
        assert result["section_status"]["product"] == "in_progress"

    def test_clears_target_section_content(self):
        state = _base_state(
            messages=[_ai_tool("modify_section", {"section": "problem"})],
            current_section="features",
            problem="old content",
        )
        result = tools_node(state)
        assert result["problem"] == ""

    def test_does_not_affect_other_sections(self):
        status = {s: "done" for s in SECTION_ORDER}
        state = _base_state(
            messages=[_ai_tool("modify_section", {"section": "problem"})],
            section_status=status,
            product="keep this",
        )
        result = tools_node(state)
        assert result["section_status"]["product"] == "done"
        assert "product" not in result  # product content not cleared

    def test_returns_tool_message(self):
        state = _base_state(
            messages=[_ai_tool("modify_section", {"section": "problem"})],
        )
        result = tools_node(state)
        assert isinstance(result["messages"][0], ToolMessage)

    def test_unknown_section_returns_error_message(self):
        state = _base_state(
            messages=[_ai_tool("modify_section", {"section": "unknown_xyz"})],
        )
        result = tools_node(state)
        assert "current_section" not in result
        assert "Unknown section" in result["messages"][0].content

    def test_all_valid_sections_accepted(self):
        for section in SECTION_ORDER:
            state = _base_state(
                messages=[_ai_tool("modify_section", {"section": section})],
            )
            result = tools_node(state)
            assert result["current_section"] == section


# ─── No tool calls ────────────────────────────────────────────────────────────


class TestNoToolCalls:
    def test_returns_empty_dict_when_no_tool_calls(self):
        state = _base_state(
            messages=[AIMessage(content="Hello! What problem are you solving?")]
        )
        result = tools_node(state)
        assert result == {}

    def test_returns_empty_dict_when_messages_empty(self):
        result = tools_node(_base_state(messages=[]))
        assert result == {}

    def test_returns_empty_dict_when_last_msg_not_ai(self):
        from langchain_core.messages import HumanMessage
        result = tools_node(_base_state(messages=[HumanMessage(content="hello")]))
        assert result == {}


# ─── Multiple tool calls in one message ───────────────────────────────────────


class TestInvalidCurrentSection:
    def test_complete_section_with_invalid_current_returns_error(self):
        state = _base_state(
            messages=[_ai_tool("complete_section", {"content": "x"})],
            current_section="welcome",  # not in SECTION_ORDER
        )
        result = tools_node(state)
        assert "No active section" in result["messages"][0].content

    def test_tools_invokable_directly(self):
        # Cover the @tool return statements
        from agent import complete_section, modify_section
        assert complete_section.invoke({"content": "x"}) == "Section complete."
        assert modify_section.invoke({"section": "problem"}) == "Now editing problem."


class TestMultipleToolCalls:
    def test_handles_multiple_tool_calls(self):
        msg = AIMessage(content="", tool_calls=[
            {"name": "complete_section", "args": {"content": "problem info"}, "id": "tc1", "type": "tool_call"},
        ])
        state = _base_state(messages=[msg], current_section="problem")
        result = tools_node(state)
        assert len(result["messages"]) == 1
        assert result["current_section"] == "product"


# ─── initialize_node ──────────────────────────────────────────────────────────


class TestInitializeNode:
    def test_bootstraps_section_status_when_missing(self):
        state = _base_state(section_status={})
        result = _run(initialize_node(state, {}))
        assert result["section_status"][SECTION_ORDER[0]] == "in_progress"
        for s in SECTION_ORDER[1:]:
            assert result["section_status"][s] == "pending"

    def test_no_update_when_section_status_already_set(self):
        state = _base_state()  # has non-empty section_status
        result = _run(initialize_node(state, {}))
        assert "section_status" not in result

    def test_fixes_invalid_current_section(self):
        state = _base_state(current_section="not_a_real_section")
        result = _run(initialize_node(state, {}))
        assert result["current_section"] == SECTION_ORDER[0]

    def test_valid_current_section_not_touched(self):
        state = _base_state(current_section="product")
        result = _run(initialize_node(state, {}))
        assert "current_section" not in result

    def test_done_current_section_not_reset(self):
        state = _base_state(current_section="done")
        result = _run(initialize_node(state, {}))
        assert "current_section" not in result


# ─── route_after_memory_updater ───────────────────────────────────────────────


class TestRouteAfterMemoryUpdater:
    def test_routes_to_implementation_when_done(self):
        state = _base_state(current_section="done")
        assert route_after_memory_updater(state) == "implementation"

    def test_routes_to_assistant_for_every_active_section(self):
        for section in SECTION_ORDER:
            state = _base_state(current_section=section)
            assert route_after_memory_updater(state) == "assistant"

    def test_routes_to_assistant_for_unknown_value(self):
        state = _base_state(current_section="")
        assert route_after_memory_updater(state) == "assistant"
