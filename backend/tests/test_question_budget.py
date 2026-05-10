from app.schemas.interview import InterviewConfig, InterviewPlan, InterviewStartRequest
from app.services.interview_engine.orchestrator import InterviewEngine
from app.services.interview_engine.plan_generator import _limit_plan_questions
from app.services.interview_engine.store import InMemoryInterviewStore
from tests.utils import sample_plan


def test_start_defaults_to_fifteen_minute_question_budget():
    engine = InterviewEngine(store=InMemoryInterviewStore())

    started = engine.start(
        InterviewStartRequest(
            job_description="Build Python APIs.",
            candidate_profile="Backend engineer.",
            role_level="junior",
            required_skills=["python"],
        )
    )

    assert started.state.config.target_duration_minutes == 15
    assert started.state.config.max_required_skills_per_interview == 5
    assert started.state.config.max_main_questions_per_skill == 1
    assert started.state.config.max_followups_per_skill == 1
    assert started.state.planned_question_count == 2
    assert started.state.remaining_question_count == 1
    assert started.state.estimated_duration_minutes == 15


def test_plan_is_limited_to_one_topic_question_per_skill():
    plan = sample_plan(["python", "fastapi"])
    expanded = InterviewPlan(
        role_title=plan.role_title,
        role_level=plan.role_level,
        skills=[
            skill.model_copy(update={"questions": [skill.questions[0], skill.questions[0].model_copy(update={"question_id": f"{skill.skill_id}-extra"})]})
            for skill in plan.skills
        ],
    )

    limited = _limit_plan_questions(expanded, max_required_skills=2)

    assert len(limited.skills) == 2
    assert all(len(skill.questions) == 1 for skill in limited.skills)


def test_plan_is_limited_to_max_required_skills():
    plan = sample_plan(["python", "fastapi", "streamlit"])

    limited = _limit_plan_questions(plan, max_required_skills=2)

    assert [skill.skill_name for skill in limited.skills] == ["python", "fastapi"]


def test_interview_completes_when_question_budget_is_reached():
    engine = InterviewEngine(store=InMemoryInterviewStore())
    started = engine.start(
        InterviewStartRequest(
            job_description="Build Python APIs.",
            candidate_profile="Backend engineer.",
            role_level="junior",
            required_skills=["python", "fastapi"],
            config=InterviewConfig(max_required_skills_per_interview=1, max_followups_per_skill=0, max_turns=1),
        )
    )

    answered = engine.answer(
        started.session_id,
        request=type("Payload", (), {"answer_text": "I used python because it was simple and measured latency."})(),
    )

    assert answered.state.status == "completed"
    assert answered.state.completion_reason == "question_budget_reached"
    assert answered.next_question is None
    assert answered.state.remaining_question_count == 0


def test_one_followup_per_skill_then_moves_to_next_required_skill():
    engine = InterviewEngine(store=InMemoryInterviewStore())
    started = engine.start(
        InterviewStartRequest(
            job_description="Build Python APIs.",
            candidate_profile="Backend engineer.",
            role_level="junior",
            required_skills=["python", "fastapi"],
            config=InterviewConfig(max_required_skills_per_interview=2, max_followups_per_skill=1, max_turns=4),
        )
    )

    first = engine.answer(started.session_id, request=type("Payload", (), {"answer_text": "thin"})())
    second = engine.answer(started.session_id, request=type("Payload", (), {"answer_text": "still thin"})())

    assert first.next_question is not None
    assert first.next_question.question_type == "follow_up"
    assert second.next_question is not None
    assert second.next_question.question_type == "topic"
    assert second.next_question.skill_id != first.state.turns[0].skill_id
