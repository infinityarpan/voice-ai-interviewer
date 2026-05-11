from app.schemas.interview import (
    AnswerEvaluation,
    InterviewAnswerRequest,
    InterviewConfig,
    InterviewSessionState,
    InterviewStartRequest,
    InterviewTurn,
    SkillRuntimeState,
)
from app.services.interview_engine.engine import InterviewEngine, InterviewPolicyEngine, ScoreAggregator, constrain_question_for_two_minutes
from app.services.interview_engine.store import InMemoryInterviewStore
from app.ai.provider import MockLLMProvider
from app.core.config import get_settings
from tests.utils import sample_plan


def test_policy_asks_followup_until_skill_budget_is_used():
    state = _state(["python"])
    evaluation = AnswerEvaluation(
        score=45,
        confidence=0.8,
        follow_up_needed=True,
        missing_signals=["tradeoffs"],
        evidence=["Used Python briefly."],
    )

    decision = InterviewPolicyEngine().decide(state, "skill-1", evaluation)

    assert decision.action == "ASK_FOLLOWUP"


def test_policy_moves_to_next_skill_when_current_skill_is_covered():
    state = _state(["python", "apis"])
    evaluation = AnswerEvaluation(
        score=85,
        confidence=0.8,
        follow_up_needed=False,
        evidence=["Explained tradeoffs."],
    )

    decision = InterviewPolicyEngine().decide(state, "skill-1", evaluation)

    assert decision.action == "ASK_NEXT_TOPIC"
    assert decision.skill_id == "skill-2"
    assert state.skill_states["skill-1"].covered is True


def test_score_aggregator_computes_skill_and_overall_scores():
    state = _state(["python"])
    turn = state.turns[0]
    turn.answer_text = "I used Python because validation mattered."
    turn.evaluation = AnswerEvaluation(
        score=80,
        confidence=0.5,
        follow_up_needed=False,
        positive_signals=["Clear example."],
        missing_signals=["Scale detail."],
        evidence=["validation mattered"],
    )

    skill_scores, overall = ScoreAggregator().aggregate(state)

    assert overall == 80
    assert skill_scores[0].positive_signals == ["Clear example."]
    assert skill_scores[0].missing_signals == ["Scale detail."]


def test_question_constraint_keeps_spoken_prompt_short():
    question = sample_plan(["python"]).skills[0].questions[0].model_copy(
        update={"question_text": "In about 2 minutes, " + " ".join(["detail"] * 80)}
    )

    constrained = constrain_question_for_two_minutes(question)

    assert len(constrained.question_text.split()) <= 50
    assert "Answer in about 2 minutes." in constrained.question_text


def test_template_followup_does_not_call_llm_question_generation(monkeypatch):
    monkeypatch.setenv("FOLLOWUP_GENERATION_MODE", "template")
    get_settings.cache_clear()
    provider = NoQuestionGenerationProvider()
    engine = InterviewEngine(store=InMemoryInterviewStore(), provider=provider)

    session = engine.start(
        InterviewStartRequest(
            job_description="Build backend APIs.",
            candidate_profile="Python API developer.",
            role_level="Associate",
            role_title="Backend Engineer",
            required_skills=["python"],
        )
    )
    response = engine.answer(
        session.session_id,
        InterviewAnswerRequest(
            answer_text="I used Python.",
            answer_source="voice",
        ),
    )

    assert response.policy_decision.action == "ASK_FOLLOWUP"
    assert response.next_question is not None
    assert response.next_question.question_type == "follow_up"
    assert provider.question_generation_calls == 0


class NoQuestionGenerationProvider(MockLLMProvider):
    def __init__(self) -> None:
        self.question_generation_calls = 0

    def generate_json(self, prompt, response_model):
        if response_model.__name__ == "InterviewQuestion":
            self.question_generation_calls += 1
            raise AssertionError("Template follow-ups should not call LLM question generation")
        return super().generate_json(prompt, response_model)


def _state(skills: list[str]) -> InterviewSessionState:
    plan = sample_plan(skills)
    state = InterviewSessionState(
        session_id="session-1",
        plan=plan,
        config=InterviewConfig(),
        current_skill_id=plan.skills[0].skill_id,
        skill_states={
            skill.skill_id: SkillRuntimeState(skill_id=skill.skill_id, skill_name=skill.skill_name)
            for skill in plan.skills
        },
    )
    state.turns.append(
        InterviewTurn(
            turn_id="turn-1",
            skill_id=plan.skills[0].skill_id,
            question=plan.skills[0].questions[0],
        )
    )
    return state
