from app.schemas.interview import InterviewQuestion
from app.services.interview_engine.question_constraints import constrain_question_for_two_minutes


def test_constrain_question_for_two_minutes_keeps_prompt_short_and_explicit():
    question = InterviewQuestion(
        question_id="q1",
        skill_id="python",
        question_text=(
            "In about 2 minutes, explain validation, pagination, errors, empty states, logging, metrics, "
            "authentication, authorization, caching, retry behavior, deployment, and testing strategy?"
        ),
    )

    constrained = constrain_question_for_two_minutes(question)

    assert len(constrained.question_text.split()) <= 50
    assert constrained.question_text.endswith("Answer in about 2 minutes.")
