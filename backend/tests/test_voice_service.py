from app.schemas.interview import InterviewConfig, InterviewQuestion, InterviewSessionState, InterviewTurn, SkillRuntimeState
from app.services.voice.realtime import MockVoiceService
from tests.utils import sample_plan


def test_mock_voice_service_uses_active_backend_question():
    plan = sample_plan(["python"])
    question = InterviewQuestion(
        question_id="q1",
        skill_id="skill-1",
        question_text="Tell me about Python. Answer in about 2 minutes.",
    )
    state = InterviewSessionState(
        session_id="s1",
        plan=plan,
        config=InterviewConfig(),
        current_skill_id="skill-1",
        skill_states={"skill-1": SkillRuntimeState(skill_id="skill-1", skill_name="python")},
        turns=[InterviewTurn(turn_id="t1", skill_id="skill-1", question=question)],
    )

    response = MockVoiceService().create_realtime_session(state)

    assert response.provider == "mock"
    assert response.question_text == question.question_text
    assert "Current question to speak exactly" in response.instructions


def test_mock_voice_service_rejects_completed_state():
    plan = sample_plan(["python"])
    state = InterviewSessionState(
        session_id="s1",
        plan=plan,
        config=InterviewConfig(),
        status="completed",
        skill_states={"skill-1": SkillRuntimeState(skill_id="skill-1", skill_name="python")},
    )

    try:
        MockVoiceService().create_realtime_session(state)
    except ValueError as exc:
        assert str(exc) == "Interview is already completed"
    else:
        raise AssertionError("Expected completed voice session to be rejected")
