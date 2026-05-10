from app.ai.base import LLMProvider
from app.schemas.interview import (
    ExpectedConcept,
    FollowUpTrigger,
    InterviewConfig,
    InterviewPlan,
    InterviewQuestion,
    InterviewSkillPlan,
    InterviewStartRequest,
    RubricItem,
)
from app.services.interview_engine.plan_generator import InterviewPlanGenerator


class DuplicatePlanProvider(LLMProvider):
    def generate_json(self, prompt, response_model):
        return InterviewPlan(
            role_title="Backend developer",
            role_level="Associate",
            skills=[
                _skill("fastapi", "FastAPI", "fastapi_topic_1"),
                _skill("fastapi", "FastAPI secondary", "fastapi_topic_1"),
            ],
        )


class LongQuestionProvider(LLMProvider):
    def generate_json(self, prompt, response_model):
        skill = _skill("python", "Python", "python_topic_1")
        long_question = (
            "In about 2 minutes, explain how you would implement an API endpoint, describe validation, "
            "database pagination, empty results, authentication, authorization, logging, observability, "
            "deployment strategy, caching, async behavior, retries, and how you would test every branch?"
        )
        return InterviewPlan(
            role_title="Backend developer",
            role_level="Associate",
            skills=[
                skill.model_copy(
                    update={
                        "questions": [
                            skill.questions[0].model_copy(update={"question_text": long_question})
                        ]
                    }
                )
            ],
        )


def test_plan_generator_normalizes_duplicate_skill_ids_and_question_skill_ids():
    plan = InterviewPlanGenerator(DuplicatePlanProvider()).generate(_request())

    assert [skill.skill_id for skill in plan.skills] == ["fastapi", "fastapi-2"]
    assert [skill.questions[0].skill_id for skill in plan.skills] == ["fastapi", "fastapi-2"]
    assert len({skill.questions[0].question_id for skill in plan.skills}) == 2


def test_plan_generator_normalizes_rubric_scale_to_policy_scale():
    plan = InterviewPlanGenerator(DuplicatePlanProvider()).generate(_request())

    assert [item.score for item in plan.skills[0].rubric] == [0, 33, 67, 100]


def test_plan_generator_adds_baseline_follow_up_triggers():
    plan = InterviewPlanGenerator(DuplicatePlanProvider()).generate(_request())
    trigger_types = [trigger.trigger_type for trigger in plan.skills[0].follow_up_triggers]

    assert "missing_concept" in trigger_types
    assert "shallow_answer" in trigger_types
    assert "contradiction" in trigger_types


def test_plan_generator_constrains_questions_for_two_minute_voice_answers():
    plan = InterviewPlanGenerator(LongQuestionProvider()).generate(_request())
    question_text = plan.skills[0].questions[0].question_text

    assert len(question_text.split()) <= 50
    assert "Answer in about 2 minutes." in question_text
    assert question_text.count("?") <= 1


def _request() -> InterviewStartRequest:
    return InterviewStartRequest(
        job_description="Backend developer",
        candidate_profile="Associate backend candidate",
        role_level="Associate",
        role_title="Backend developer",
        required_skills=["fastapi"],
        config=InterviewConfig(),
    )


def _skill(skill_id: str, skill_name: str, question_id: str) -> InterviewSkillPlan:
    return InterviewSkillPlan(
        skill_id=skill_id,
        skill_name=skill_name,
        target_depth="backend fundamentals",
        questions=[
            InterviewQuestion(
                question_id=question_id,
                skill_id=skill_id,
                question_text="Explain a FastAPI endpoint.",
                question_type="topic",
            )
        ],
        expected_concepts=[
            ExpectedConcept(name="Validation", description="Uses request validation."),
        ],
        rubric=[
            RubricItem(score=0, description="No answer."),
            RubricItem(score=1, description="Thin answer."),
            RubricItem(score=2, description="Good answer."),
            RubricItem(score=3, description="Strong answer."),
        ],
        follow_up_triggers=[
            FollowUpTrigger(trigger_type="contradiction", description="If the answer contradicts expected FastAPI behavior."),
        ],
    )
