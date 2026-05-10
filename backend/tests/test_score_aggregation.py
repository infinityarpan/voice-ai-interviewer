from app.schemas.interview import AnswerEvaluation, InterviewConfig, InterviewQuestion, InterviewSessionState, InterviewTurn, SkillRuntimeState
from app.services.interview_engine.score_aggregator import ScoreAggregator
from tests.utils import sample_plan


def test_aggregates_skill_and_overall_scores():
    plan = sample_plan(["python", "apis"])
    state = InterviewSessionState(
        session_id="s1",
        plan=plan,
        config=InterviewConfig(),
        skill_states={skill.skill_id: SkillRuntimeState(skill_id=skill.skill_id, skill_name=skill.skill_name) for skill in plan.skills},
        turns=[
            InterviewTurn(
                turn_id="t1",
                skill_id="skill-1",
                question=InterviewQuestion(question_id="q1", skill_id="skill-1", question_text="Q1"),
                answer_text="A1",
                evaluation=AnswerEvaluation(
                    score=80,
                    positive_signals=["clear python"],
                    missing_signals=["profiling"],
                    evidence=["used python"],
                    confidence=1,
                    follow_up_needed=False,
                ),
            ),
            InterviewTurn(
                turn_id="t2",
                skill_id="skill-2",
                question=InterviewQuestion(question_id="q2", skill_id="skill-2", question_text="Q2"),
                answer_text="A2",
                evaluation=AnswerEvaluation(
                    score=60,
                    positive_signals=["api basics"],
                    missing_signals=["error handling"],
                    evidence=["built api"],
                    confidence=1,
                    follow_up_needed=True,
                ),
            ),
        ],
    )

    skill_scores, overall = ScoreAggregator().aggregate(state)

    assert [score.score for score in skill_scores] == [80, 60]
    assert overall == 70
    assert skill_scores[0].positive_signals == ["clear python"]
    assert skill_scores[1].missing_signals == ["error handling"]


def test_handles_unanswered_skills():
    plan = sample_plan(["python"])
    state = InterviewSessionState(
        session_id="s1",
        plan=plan,
        config=InterviewConfig(),
        skill_states={"skill-1": SkillRuntimeState(skill_id="skill-1", skill_name="python")},
    )

    skill_scores, overall = ScoreAggregator().aggregate(state)

    assert skill_scores[0].score == 0
    assert skill_scores[0].turns_evaluated == 0
    assert overall == 0
