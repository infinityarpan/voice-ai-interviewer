from app.ai.base import LLMProvider
from app.schemas.interview import (
    AnswerEvaluation,
    ExpectedConcept,
    InterviewPlan,
    InterviewQuestion,
    InterviewReport,
    InterviewSkillPlan,
    RubricItem,
)
from app.services.interview_engine.evaluator import AnswerEvaluator
from app.services.interview_engine.plan_generator import InterviewPlanGenerator
from app.services.interview_engine.report_generator import ReportGenerator
from app.schemas.interview import InterviewConfig, InterviewSessionState, InterviewStartRequest, SkillRuntimeState


class RecordingProvider(LLMProvider):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, prompt, response_model):
        self.prompts.append(prompt)
        if response_model is InterviewPlan:
            return _plan()
        if response_model is AnswerEvaluation:
            return AnswerEvaluation(score=70, evidence=["answer"], confidence=0.8, follow_up_needed=False)
        if response_model is InterviewReport:
            return InterviewReport(
                session_id="s1",
                summary="summary",
                overall_score=70,
                skill_scores=[],
                strengths=[],
                weaknesses=[],
                evidence=[],
                risks=[],
                next_round_suggestions=[],
            )
        raise AssertionError(f"Unexpected response model: {response_model}")


def test_plan_prompt_uses_initial_recruiter_shortlist_context():
    provider = RecordingProvider()
    InterviewPlanGenerator(provider).generate(
        InterviewStartRequest(
            job_description="Backend role",
            candidate_profile="Python candidate",
            role_level="Associate",
            required_skills=["python"],
        )
    )

    assert "initial recruiter shortlist screen" in provider.prompts[0]
    assert "plausible candidate can be recommended for the first round" in provider.prompts[0]


def test_evaluator_prompt_does_not_treat_initial_screen_as_final_rejection():
    provider = RecordingProvider()
    skill = _plan().skills[0]
    AnswerEvaluator(provider).evaluate(skill.questions[0], "I have built Python APIs.", skill)

    assert "rather than final rejection" in provider.prompts[0]


def test_report_prompt_frames_risks_as_first_round_validation_items():
    provider = RecordingProvider()
    plan = _plan()
    state = InterviewSessionState(
        session_id="s1",
        plan=plan,
        config=InterviewConfig(),
        skill_states={"python": SkillRuntimeState(skill_id="python", skill_name="Python")},
    )
    ReportGenerator(provider).generate(state)

    assert "first-round validation items" in provider.prompts[0]


def _plan() -> InterviewPlan:
    return InterviewPlan(
        role_title="Backend Engineer",
        role_level="Associate",
        skills=[
            InterviewSkillPlan(
                skill_id="python",
                skill_name="Python",
                target_depth="broad practical familiarity",
                questions=[
                    InterviewQuestion(
                        question_id="python_topic",
                        skill_id="python",
                        question_text="Tell me about your Python backend experience.",
                    )
                ],
                expected_concepts=[ExpectedConcept(name="API exposure", description="Has built backend APIs.")],
                rubric=[RubricItem(score=70, description="Plausible first-round fit.")],
            )
        ],
    )
