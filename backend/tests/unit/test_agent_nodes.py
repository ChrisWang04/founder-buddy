"""Unit tests for graph nodes and routers in agent.py.

Nodes that call interrupt() can only be tested for their early-return branches
here. The interrupt paths are exercised via the compiled graph in the
integration tests (Phase 3).
"""

from langchain_core.messages import HumanMessage

from agent import (
    QUESTIONS,
    SECTION_ORDER,
    section_node,
    section_router,
    welcome_node,
    welcome_router,
)


# ─── welcome_router ───────────────────────────────────────────────────────────


class TestWelcomeRouter:
    def test_routes_to_section_when_done(self):
        assert welcome_router({"welcome_done": True}) == "section"

    def test_routes_to_welcome_when_not_done(self):
        assert welcome_router({"welcome_done": False}) == "welcome"

    def test_routes_to_welcome_when_field_missing(self):
        assert welcome_router({}) == "welcome"


# ─── section_router ───────────────────────────────────────────────────────────


class TestSectionRouter:
    def test_generate_bp_when_done(self):
        assert section_router({"current_section": "done"}) == "generate_bp"

    def test_routes_to_section_when_in_progress(self):
        state = {"current_section": "problem", "current_question_index": 0}
        assert section_router(state) == "section"

    def test_routes_to_edit_when_editing_section_complete(self):
        # edit_in_progress + current_section in QUESTIONS + finished its questions
        state = {
            "edit_in_progress": True,
            "current_section": "problem",
            "current_question_index": len(QUESTIONS["problem"]),
        }
        assert section_router(state) == "edit"

    def test_routes_to_section_when_editing_but_questions_remain(self):
        state = {
            "edit_in_progress": True,
            "current_section": "product",
            "current_question_index": 0,  # < len(QUESTIONS["product"])
        }
        assert section_router(state) == "section"

    def test_routes_to_section_when_not_editing_even_at_end(self):
        # If we're not in edit mode, the end-of-section transition happens
        # inside section_node, not via the router → router should still say
        # "section" so the node can re-run.
        state = {
            "edit_in_progress": False,
            "current_section": "problem",
            "current_question_index": len(QUESTIONS["problem"]),
        }
        assert section_router(state) == "section"

    def test_routes_to_generate_bp_when_editing_but_section_done(self):
        """edit_in_progress=True AND current_section not in QUESTIONS.
        This isolates the second clause of the 3-clause compound: even when
        edit_in_progress is True, if current_section is 'done' the second
        AND-clause shortcuts the path → falls through to the next check."""
        state = {
            "edit_in_progress": True,
            "current_section": "done",
            "current_question_index": 0,
        }
        # First if-block: edit_in_progress True AND "done" not in QUESTIONS → False
        # Second if-block: current_section == "done" → returns generate_bp
        assert section_router(state) == "generate_bp"


# ─── welcome_node early-return paths ──────────────────────────────────────────


class TestWelcomeNodeEarlyReturns:
    def test_returns_empty_when_already_done(self, stub_llm):
        result = welcome_node({"welcome_done": True})
        assert result == {}
        assert stub_llm.invoke_calls == []  # no LLM call

    def test_proceeds_on_user_confirmation(self, stub_llm):
        # Mapping LLM call returns both fields
        stub_llm.invoke_responses.append('{"problem": "real prob", "product": "real prod"}')
        state = {
            "messages": [
                HumanMessage(content="I want to start a coffee shop"),
                HumanMessage(content="yes"),
            ],
            "welcome_question_count": 1,
        }
        result = welcome_node(state)

        assert result["welcome_done"] is True
        assert result["current_section"] == "problem"
        assert result["section_status"]["problem"] == "in_progress"
        assert "Q: What problem" in result["problem"]
        assert "real prob" in result["problem"]
        assert "real prod" in result["product"]

    def test_force_proceed_at_max_count(self, stub_llm):
        # Empty mapping; force_proceed should still advance us
        stub_llm.invoke_responses.append("{}")
        state = {
            "messages": [HumanMessage(content="vague idea")],
            "welcome_question_count": 2,
        }
        result = welcome_node(state)

        assert result["welcome_done"] is True
        assert result["current_section"] == "problem"
        # Empty mapping → problem/product not populated
        assert "problem" not in result
        assert "product" not in result

    def test_mapping_skips_empty_fields(self, stub_llm):
        # Only problem populated; product should be skipped
        stub_llm.invoke_responses.append(
            '{"problem": "has value", "product": ""}'
        )
        state = {
            "messages": [
                HumanMessage(content="idea"),
                HumanMessage(content="ok"),
            ],
            "welcome_question_count": 1,
        }
        result = welcome_node(state)

        assert "problem" in result
        assert "product" not in result

    def test_partial_confirmation_word_matches(self, stub_llm):
        # "okay" is in CONFIRMATION_WORDS
        stub_llm.invoke_responses.append("{}")
        state = {
            "messages": [HumanMessage(content="okay let's do it")],
            "welcome_question_count": 0,
        }
        result = welcome_node(state)
        assert result["welcome_done"] is True

    def test_force_proceed_with_no_human_messages(self, stub_llm):
        """Edge case: no HumanMessage in history. Loop completes without break."""
        stub_llm.invoke_responses.append("{}")
        from langchain_core.messages import AIMessage as _AI

        state = {
            "messages": [_AI(content="only an AI message")],
            "welcome_question_count": 2,  # force_proceed
        }
        result = welcome_node(state)
        # force_proceed wins → welcome completes
        assert result["welcome_done"] is True


# ─── section_node end-of-section transition ───────────────────────────────────


class TestSectionNodeTransitions:
    def test_advances_to_next_section(self):
        state = {
            "current_section": "problem",
            "current_question_index": len(QUESTIONS["problem"]),
            "section_status": {"problem": "in_progress", "product": "pending"},
        }
        result = section_node(state)

        assert result["current_section"] == "product"
        assert result["current_question_index"] == 0
        assert result["section_status"]["problem"] == "done"
        assert result["section_status"]["product"] == "in_progress"

    def test_completes_last_section(self):
        last_section = SECTION_ORDER[-1]
        state = {
            "current_section": last_section,
            "current_question_index": len(QUESTIONS[last_section]),
            "section_status": {last_section: "in_progress"},
        }
        result = section_node(state)

        assert result["current_section"] == "done"
        assert result["section_status"][last_section] == "done"

    def test_skips_section_when_already_filled(self):
        # Welcome pre-filled "problem"; section_node should advance immediately
        state = {
            "current_section": "problem",
            "current_question_index": 0,
            "problem": "Q: X\nA: Y",
            "section_status": {"problem": "in_progress", "product": "pending"},
        }
        result = section_node(state)

        # idx bumped from 0 to len(questions) → triggers transition
        assert result["current_section"] == "product"

    def test_does_not_skip_section_when_idx_nonzero(self):
        # If we're mid-section, the pre-fill skip should NOT trigger
        # Need idx in valid range to trigger interrupt path, so we test the
        # end-of-section case with pre-fill (idx already at end)
        state = {
            "current_section": "product",
            "current_question_index": len(QUESTIONS["product"]),
            "product": "Q: X\nA: Y",
            "section_status": {"product": "in_progress", "features": "pending"},
        }
        result = section_node(state)
        # Just advances past — confirms idx isn't bumped twice
        assert result["current_section"] == "features"
