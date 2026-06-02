"""End-to-end graph flow tests through the HTTP layer.

These exercise the full state machine across many turns. They are slower than
the focused tests in test_chat_stream.py but catch routing/state regressions
the focused tests can't.
"""

from tests.conftest import answer_n_questions, drive_through_welcome


TOTAL_QUESTIONS = 11


# ─── Full happy path ──────────────────────────────────────────────────────────


def test_full_happy_path(test_app, stub_llm):
    """Start → answer welcome → 11 section questions → BP generated."""
    session_id = drive_through_welcome(test_app, stub_llm)

    # Queue a BP for the final astream
    stub_llm.stream_chunks.append(["This is the final business plan. " * 10])

    # Answer all 11 questions via /chat/message (no streaming needed here)
    for i in range(TOTAL_QUESTIONS):
        resp = test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": f"answer {i}"},
        )
        assert resp.status_code == 200

    # Final state should have BP + edit interrupt
    final = test_app.get(f"/chat/state?session_id={session_id}").json()
    assert final["is_done"] is True
    assert final["business_plan"] is not None
    assert "business plan" in final["business_plan"].lower()
    assert "edit" in (final["agent_message"] or "").lower()


# ─── Skip path ────────────────────────────────────────────────────────────────


def test_skip_all_questions_still_generates_bp(test_app, stub_llm):
    """Every answer = 'skip' → no per-section content but BP is still produced."""
    session_id = drive_through_welcome(test_app, stub_llm)

    stub_llm.stream_chunks.append(["BP for empty answers. " * 15])  # > 200 chars

    for _ in range(TOTAL_QUESTIONS):
        resp = test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": "skip"},
        )
        assert resp.status_code == 200

    final = test_app.get(f"/chat/state?session_id={session_id}").json()
    assert final["is_done"] is True
    assert final["business_plan"] is not None


# ─── Edit flow ────────────────────────────────────────────────────────────────


def test_edit_flow_reroutes_to_section(test_app, stub_llm):
    """After BP gen, edit a section → re-collect → confirm → new BP generated.

    The edit loop is: edit_node asks "anything else?" each time a section
    edit completes, and only regenerates the BP when the user confirms with
    a word in EDIT_CONFIRMATION_WORDS (e.g. "looks good").
    """
    session_id = drive_through_welcome(test_app, stub_llm)

    # First BP
    stub_llm.stream_chunks.append(["First BP version. " * 20])
    answer_n_questions(test_app, session_id, TOTAL_QUESTIONS)

    # Now at the edit interrupt. Request to edit the problem section.
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "edit problem"},
    )
    data = resp.json()
    assert data["is_done"] is False
    assert "What problem" in (data["agent_message"] or "")

    # Re-answer the problem question — lands at "anything else?" prompt
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "new problem answer"},
    )
    data = resp.json()
    assert "anything else" in (data["agent_message"] or "").lower()

    # Confirm — triggers BP regen
    stub_llm.stream_chunks.append(["Second BP version. " * 20])
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "looks good"},
    )
    data = resp.json()
    assert data["is_done"] is True
    assert "Second BP version" in (data["business_plan"] or "")


# ─── Welcome auto-fill skip ───────────────────────────────────────────────────


def test_edit_node_loops_on_unrecognized_input(test_app, stub_llm):
    """If the user's edit reply is neither an alias nor a confirmation word,
    edit_node should re-interrupt with the same prompt (Command(goto='edit'))."""
    session_id = drive_through_welcome(test_app, stub_llm)
    stub_llm.stream_chunks.append(["BP. " * 60])
    answer_n_questions(test_app, session_id, TOTAL_QUESTIONS)

    # At edit interrupt. Send something that's neither edit-word + alias nor
    # a confirmation word. (Avoid "no", "yes", "done" etc — they're confirmations.)
    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "hmm"},
    )
    data = resp.json()
    # Loops back to same prompt — still in edit phase
    assert data["is_done"] is True  # current_section == "done" + interrupt present
    assert "edit" in (data["agent_message"] or "").lower()


def test_chat_message_saves_business_plan_on_completion(
    test_app, stub_llm, mock_supabase, fake_jwt
):
    """The /chat/message route should persist the business plan when the
    final turn completes BP generation."""
    headers = {"Authorization": f"Bearer {fake_jwt}"}
    start = test_app.post(
        "/chat/start", json={"message": "test idea"}, headers=headers
    )
    session_id = start.json()["session_id"]
    test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "yes"},
        headers=headers,
    )

    stub_llm.stream_chunks.append(["Saved BP content. " * 20])
    for _ in range(TOTAL_QUESTIONS):
        test_app.post(
            "/chat/message",
            json={"session_id": session_id, "message": "ok"},
            headers=headers,
        )

    # Business plan should be saved (via /chat/message's own persistence path)
    assert len(mock_supabase["business_plans"]) == 1
    assert "Saved BP" in mock_supabase["business_plans"][0]["content"]


def test_welcome_mapping_skips_prefilled_sections(test_app, stub_llm):
    """If welcome mapping populates problem+product, those sections are
    skipped — only features+team+investment+exit (8 questions) remain.

    On resume, welcome_node re-runs from the top, so llm.invoke(assessment)
    is called a SECOND time before interrupt() returns "yes". The mapping
    call is the third invoke.
    """
    stub_llm.invoke_responses.extend([
        "first assessment",                # /chat/start
        "second assessment on resume",     # re-run before interrupt resolves
        '{"problem": "real prob", "product": "real prod"}',  # mapping
    ])

    start = test_app.post("/chat/start", json={"message": "coffee shop"})
    session_id = start.json()["session_id"]

    resp = test_app.post(
        "/chat/message",
        json={"session_id": session_id, "message": "yes"},
    )
    # problem + product were both prefilled → first interrupt is features Q1
    assert "Features" in (resp.json()["agent_message"] or "")
