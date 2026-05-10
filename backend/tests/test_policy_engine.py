from app.schemas.interview import AnswerEvaluation, InterviewConfig, InterviewSessionState, PolicyAction, SkillRuntimeState
from app.services.interview_engine.policy import InterviewPolicyEngine
from tests.utils import sample_plan


def state():
    plan = sample_plan(["python", "apis"])
    return InterviewSessionState(
        session_id="s1",
        plan=plan,
        config=InterviewConfig(max_followups_per_skill=1),
        current_skill_id="skill-1",
        skill_states={skill.skill_id: SkillRuntimeState(skill_id=skill.skill_id, skill_name=skill.skill_name) for skill in plan.skills},
    )


def test_asks_followup_when_missing_concepts_and_budget_remains():
    current = state()
    evaluation = AnswerEvaluation(score=60, missing_signals=["python tradeoffs"], evidence=["some answer"], confidence=0.8, follow_up_needed=True)

    decision = InterviewPolicyEngine().decide(current, "skill-1", evaluation)

    assert decision.action == PolicyAction.ASK_FOLLOWUP


def test_moves_to_next_topic_when_skill_is_covered():
    current = state()
    evaluation = AnswerEvaluation(score=88, positive_signals=["strong"], evidence=["clear"], confidence=0.9, follow_up_needed=False)

    decision = InterviewPolicyEngine().decide(current, "skill-1", evaluation)

    assert decision.action == PolicyAction.ASK_NEXT_TOPIC
    assert decision.skill_id == "skill-2"


def test_asks_clarification_for_empty_answer():
    current = state()
    evaluation = AnswerEvaluation(score=0, missing_signals=["python"], evidence=[], confidence=0.9, follow_up_needed=False)

    decision = InterviewPolicyEngine().decide(current, "skill-1", evaluation)

    assert decision.action == PolicyAction.ASK_CLARIFICATION


def test_ends_when_all_skills_are_covered():
    current = state()
    current.skill_states["skill-2"].covered = True
    evaluation = AnswerEvaluation(score=90, positive_signals=["strong"], evidence=["clear"], confidence=0.9, follow_up_needed=False)

    decision = InterviewPolicyEngine().decide(current, "skill-1", evaluation)

    assert decision.action == PolicyAction.END_INTERVIEW


def test_moves_on_when_followup_limit_is_reached():
    current = state()
    current.skill_states["skill-1"].followups_asked = 1
    evaluation = AnswerEvaluation(score=50, missing_signals=["python tradeoffs"], evidence=["thin"], confidence=0.8, follow_up_needed=True)

    decision = InterviewPolicyEngine().decide(current, "skill-1", evaluation)

    assert decision.action == PolicyAction.ASK_NEXT_TOPIC
