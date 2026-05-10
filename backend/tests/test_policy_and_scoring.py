from app.schemas.interview import AnswerEvaluation, InterviewConfig, InterviewSessionState, InterviewTurn, SkillRuntimeState
from app.services.interview_engine.engine import InterviewPolicyEngine, ScoreAggregator, constrain_question_for_two_minutes
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
