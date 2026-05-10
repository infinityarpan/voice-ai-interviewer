from app.schemas.interview import InterviewStartRequest
from app.services.interview_engine.orchestrator import InterviewEngine
from app.services.interview_engine.store import InMemoryInterviewStore


def test_manual_end_marks_session_completed_and_returns_report():
    engine = InterviewEngine(store=InMemoryInterviewStore())
    started = engine.start(
        InterviewStartRequest(
            job_description="Build Python APIs.",
            candidate_profile="Backend engineer.",
            role_level="senior",
            required_skills=["python", "apis"],
        )
    )

    ended = engine.end(started.session_id)

    assert ended.state.status == "completed"
    assert ended.state.completion_reason == "manual_end"
    assert ended.state.completed_at is not None
    assert ended.report.session_id == started.session_id


def test_answer_rejected_after_manual_end():
    engine = InterviewEngine(store=InMemoryInterviewStore())
    started = engine.start(
        InterviewStartRequest(
            job_description="Build Python APIs.",
            candidate_profile="Backend engineer.",
            role_level="senior",
            required_skills=["python"],
        )
    )
    engine.end(started.session_id)

    try:
        engine.answer(started.session_id, request=type("Payload", (), {"answer_text": "late answer"})())
    except ValueError as exc:
        assert str(exc) == "Interview is already completed"
    else:
        raise AssertionError("Expected answer after manual end to be rejected")
