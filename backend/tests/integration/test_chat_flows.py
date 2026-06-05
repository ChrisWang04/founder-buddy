"""End-to-end graph flow tests through the HTTP layer."""

from agent import SECTION_ORDER
from tests.conftest import complete_section_call, modify_section_call


def _start(test_app, stub_llm, message="coffee shop idea"):
    stub_llm.invoke_responses.append("What problem are you solving?")
    resp = test_app.post("/chat/start", json={"message": message})
    return resp.json()["session_id"]


def _advance_section(test_app, stub_llm, session_id, section, next_question="Next section?"):
    """Send one user turn that completes `section` via a tool call."""
    stub_llm.invoke_responses.append(complete_section_call(f"{section} info"))
    stub_llm.invoke_responses.append(next_question)
    return test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": f"answer for {section}"},
    )


def test_section_advances_on_complete_section_call(test_app, stub_llm):
    session_id = _start(test_app, stub_llm)
    resp = _advance_section(test_app, stub_llm, session_id, "problem")

    data = resp.json()
    assert data["section_status"]["problem"] == "done"
    assert data["section_status"]["product"] == "in_progress"
    assert data["is_done"] is False


def test_full_happy_path_all_sections(test_app, stub_llm):
    session_id = _start(test_app, stub_llm)

    for i, section in enumerate(SECTION_ORDER):
        is_last = i == len(SECTION_ORDER) - 1
        stub_llm.invoke_responses.append(complete_section_call(f"{section} info"))
        if not is_last:
            stub_llm.invoke_responses.append(f"Now {SECTION_ORDER[i+1]}.")
        else:
            # After last section tools_node sets current_section="done" and
            # memory_updater routes to implementation_node, which calls llm.ainvoke().
            stub_llm.invoke_responses.append("Executive Summary\n\n" + "Business plan. " * 15)

        resp = test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": f"answer {i}"},
        )
        assert resp.status_code == 200

    # Last response: implementation_node ran and produced the BP
    data = resp.json()
    assert data["is_done"] is True
    assert data["business_plan"] is not None
    assert data["section_status"]["exit_strategy"] == "done"


def test_skip_section_with_skip_text(test_app, stub_llm):
    """LLM may complete a section with 'skipped' content — should still advance."""
    session_id = _start(test_app, stub_llm)

    stub_llm.invoke_responses.append(complete_section_call("skipped"))
    stub_llm.invoke_responses.append("Got it, let's talk product.")
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "skip"},
    )
    assert resp.json()["section_status"]["problem"] == "done"


def test_edit_flow_reverts_section(test_app, stub_llm):
    """After problem is done, calling modify_section should revert it."""
    session_id = _start(test_app, stub_llm)
    _advance_section(test_app, stub_llm, session_id, "problem")

    # Now at product; user wants to redo problem
    stub_llm.invoke_responses.append(modify_section_call("problem"))
    stub_llm.invoke_responses.append("What problem are you solving again?")
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "actually I want to change the problem"},
    )
    data = resp.json()
    # Section reverted
    assert data["section_status"]["problem"] == "in_progress"
    assert data["agent_message"] == "What problem are you solving again?"


def test_modify_then_recomplete(test_app, stub_llm):
    """Modify a section, re-complete it, check it advances normally."""
    session_id = _start(test_app, stub_llm)
    _advance_section(test_app, stub_llm, session_id, "problem")

    # Modify
    stub_llm.invoke_responses.append(modify_section_call("problem"))
    stub_llm.invoke_responses.append("OK, tell me the real problem.")
    test_app.post("/chat/message", json={"session_id": session_id, "message": "edit problem"})

    # Re-complete
    stub_llm.invoke_responses.append(complete_section_call("better problem description"))
    stub_llm.invoke_responses.append("Now let's talk product.")
    resp = test_app.post("/chat/message", json={"session_id": session_id, "message": "new answer"})

    data = resp.json()
    assert data["section_status"]["problem"] == "done"
    assert data["section_status"]["product"] == "in_progress"

    # Content updated
    state = test_app.get(f"/chat/state?session_id={session_id}").json()
    # section_status reflects the re-done problem
    assert data["section_status"]["problem"] == "done"


def test_invalid_modify_target_does_not_crash(test_app, stub_llm):
    """If LLM passes an invalid section to modify_section, graph should not crash."""
    session_id = _start(test_app, stub_llm)

    stub_llm.invoke_responses.append(modify_section_call("nonexistent_section"))
    stub_llm.invoke_responses.append("Hmm, I didn't catch that.")
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "edit xyz"},
    )
    assert resp.status_code == 200
    # current_section unchanged
    assert resp.json()["section_status"] is not None


def test_session_not_found_returns_404(test_app):
    resp = test_app.post("/chat/message", json={"session_id": "ghost", "message": "x"})
    assert resp.status_code == 404
