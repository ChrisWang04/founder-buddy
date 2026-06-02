"""Unit tests for pure helper functions in agent.py."""

from agent import (
    build_edit_status,
    complete_current_edit_status,
    detect_edit_section,
    map_welcome_to_sections,
)


# ─── detect_edit_section ──────────────────────────────────────────────────────


class TestDetectEditSection:
    def test_returns_none_without_edit_word(self):
        assert detect_edit_section("the team is great") is None

    def test_returns_none_with_edit_word_but_no_alias(self):
        assert detect_edit_section("change everything please") is None

    def test_returns_none_with_alias_but_no_edit_word(self):
        # "team" is an alias but no edit word present
        assert detect_edit_section("the team is fine") is None

    def test_returns_none_for_empty_string(self):
        assert detect_edit_section("") is None

    def test_simple_aliases(self):
        assert detect_edit_section("edit problem") == "problem"
        assert detect_edit_section("change product") == "product"
        assert detect_edit_section("update features") == "features"

    def test_singular_feature_alias(self):
        assert detect_edit_section("edit feature") == "features"

    def test_compound_aliases(self):
        assert detect_edit_section("edit team") == "team_traction"
        assert detect_edit_section("modify traction") == "team_traction"
        assert detect_edit_section("change funding") == "investment"
        assert detect_edit_section("redo exit") == "exit_strategy"

    def test_case_insensitive(self):
        assert detect_edit_section("EDIT PROBLEM") == "problem"
        assert detect_edit_section("Edit Problem") == "problem"

    def test_dash_normalization(self):
        assert detect_edit_section("edit team-traction") == "team_traction"
        assert detect_edit_section("change exit-strategy") == "exit_strategy"

    def test_ampersand_normalization(self):
        # "&" → " and "; the alias "team" still matches the result
        assert detect_edit_section("edit team & traction") == "team_traction"

    def test_all_edit_words(self):
        for verb in ("change", "edit", "update", "modify", "redo"):
            assert detect_edit_section(f"{verb} problem") == "problem"


# ─── build_edit_status ────────────────────────────────────────────────────────


class TestBuildEditStatus:
    def test_sets_target_to_in_progress(self):
        result = build_edit_status("problem", {"problem": "done", "product": "done"})
        assert result["problem"] == "in_progress"

    def test_preserves_other_sections(self):
        result = build_edit_status("problem", {"problem": "done", "product": "done"})
        assert result["product"] == "done"

    def test_does_not_mutate_input(self):
        status = {"problem": "done"}
        build_edit_status("problem", status)
        assert status["problem"] == "done"


# ─── complete_current_edit_status ─────────────────────────────────────────────


class TestCompleteCurrentEditStatus:
    def test_marks_current_section_done(self):
        result = complete_current_edit_status({
            "current_section": "problem",
            "section_status": {"problem": "in_progress"},
        })
        assert result["problem"] == "done"

    def test_skips_when_current_section_is_done_sentinel(self):
        # "done" is not in SECTION_ORDER, so status should be unchanged
        result = complete_current_edit_status({
            "current_section": "done",
            "section_status": {"problem": "done"},
        })
        assert "done" not in result
        assert result["problem"] == "done"

    def test_does_not_mutate_input(self):
        status = {"problem": "in_progress"}
        complete_current_edit_status({
            "current_section": "problem",
            "section_status": status,
        })
        assert status["problem"] == "in_progress"

    def test_handles_missing_section_status(self):
        result = complete_current_edit_status({"current_section": "problem"})
        assert result == {"problem": "done"}


# ─── map_welcome_to_sections ──────────────────────────────────────────────────


class TestMapWelcomeToSections:
    def test_parses_valid_json(self, stub_llm):
        stub_llm.invoke_responses.append('{"problem": "X", "product": "Y"}')
        assert map_welcome_to_sections("conv") == {"problem": "X", "product": "Y"}

    def test_strips_markdown_json_fence(self, stub_llm):
        stub_llm.invoke_responses.append('```json\n{"problem": "X", "product": "Y"}\n```')
        assert map_welcome_to_sections("conv") == {"problem": "X", "product": "Y"}

    def test_strips_plain_code_fence(self, stub_llm):
        stub_llm.invoke_responses.append('```\n{"problem": "X", "product": "Y"}\n```')
        assert map_welcome_to_sections("conv") == {"problem": "X", "product": "Y"}

    def test_returns_empty_on_malformed_json(self, stub_llm):
        stub_llm.invoke_responses.append("not json at all")
        assert map_welcome_to_sections("conv") == {}

    def test_returns_empty_on_empty_response(self, stub_llm):
        stub_llm.invoke_responses.append("")
        assert map_welcome_to_sections("conv") == {}
