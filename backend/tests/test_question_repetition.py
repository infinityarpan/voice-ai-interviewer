from app.schemas.interview import InterviewStartRequest
from app.services.interview_engine.orchestrator import InterviewEngine
from app.services.interview_engine.store import InMemoryInterviewStore


def test_engine_prevents_repeated_question_text():
    engine = InterviewEngine(store=InMemoryInterviewStore())
    response = engine.start(
        InterviewStartRequest(
            job_description="Python APIs",
            candidate_profile="Backend engineer",
            role_level="senior",
            required_skills=["python"],
        )
    )

    answer = engine.answer(response.session_id, request=type("Payload", (), {"answer_text": "thin"})())

    questions = [turn.question.question_text for turn in answer.state.turns]
    assert len(questions) == len(set(questions))
