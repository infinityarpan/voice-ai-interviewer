from app.ai.base import LLMProvider
from app.schemas.interview import FollowUpTrigger, InterviewPlan, InterviewQuestion, InterviewSkillPlan, InterviewStartRequest, RubricItem
from app.services.interview_engine.prompt_context import shortlist_context_lines
from app.services.interview_engine.question_constraints import constrain_question_for_two_minutes


class InterviewPlanGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def generate(self, request: InterviewStartRequest) -> InterviewPlan:
        prompt = "\n".join(
            [
                "Create a structured interview plan.",
                "The plan is a controlled voice-interview question bank, not a written test.",
                "Generate at most one primary topic question per skill.",
                "Each topic question must be a single concise spoken prompt answerable in about 2 minutes.",
                "Do not ask multi-part written-test questions; ask for one focused scenario, decision, or explanation.",
                *shortlist_context_lines(),
                f"target_duration_minutes={request.config.target_duration_minutes}",
                f"max_required_skills_per_interview={request.config.max_required_skills_per_interview}",
                f"max_main_questions_per_skill={request.config.max_main_questions_per_skill}",
                f"max_followups_per_skill={request.config.max_followups_per_skill}",
                f"role_title={request.role_title}",
                f"role_level={request.role_level}",
                f"required_skills={','.join(request.required_skills)}",
                f"job_description={request.job_description}",
                f"candidate_profile={request.candidate_profile}",
            ]
        )
        plan = self.provider.generate_json(prompt, InterviewPlan)
        limited_plan = _limit_plan_questions(
            plan,
            max_required_skills=request.config.max_required_skills_per_interview,
            max_main_questions_per_skill=request.config.max_main_questions_per_skill,
        )
        return _normalize_plan(limited_plan)


def _limit_plan_questions(
    plan: InterviewPlan,
    max_required_skills: int,
    max_main_questions_per_skill: int = 1,
) -> InterviewPlan:
    limited_skills: list[InterviewSkillPlan] = []
    for skill in plan.skills:
        if len(limited_skills) >= max_required_skills:
            break
        primary_questions = _topic_questions(skill)[:max_main_questions_per_skill]
        limited_skills.append(skill.model_copy(update={"questions": primary_questions}))
    if not limited_skills:
        first_skill = plan.skills[0]
        limited_skills = [first_skill.model_copy(update={"questions": [_topic_questions(first_skill)[0]]})]
    return plan.model_copy(update={"skills": limited_skills})


def _topic_questions(skill: InterviewSkillPlan) -> list[InterviewQuestion]:
    topic_questions = [question for question in skill.questions if question.question_type == "topic"]
    if topic_questions:
        return topic_questions
    return [skill.questions[0].model_copy(update={"question_type": "topic"})]


def _normalize_plan(plan: InterviewPlan) -> InterviewPlan:
    used_skill_ids: dict[str, int] = {}
    used_question_ids: set[str] = set()
    normalized_skills: list[InterviewSkillPlan] = []

    for skill in plan.skills:
        skill_id = _unique_skill_id(skill.skill_id, used_skill_ids)
        normalized_questions = [
            _normalize_question(question, skill_id, used_question_ids)
            for question in skill.questions
        ]
        normalized_skills.append(
            skill.model_copy(
                update={
                    "skill_id": skill_id,
                    "questions": normalized_questions,
                    "rubric": _normalize_rubric(skill.rubric),
                    "follow_up_triggers": _normalize_follow_up_triggers(skill.follow_up_triggers),
                }
            )
        )
    return plan.model_copy(update={"skills": normalized_skills})


def _unique_skill_id(skill_id: str, used_skill_ids: dict[str, int]) -> str:
    base_id = skill_id.strip() or "skill"
    count = used_skill_ids.get(base_id, 0) + 1
    used_skill_ids[base_id] = count
    if count == 1:
        return base_id
    return f"{base_id}-{count}"


def _normalize_question(
    question: InterviewQuestion,
    skill_id: str,
    used_question_ids: set[str],
) -> InterviewQuestion:
    question_id = question.question_id.strip() or f"{skill_id}_topic"
    if question_id in used_question_ids:
        question_id = f"{question_id}_{len(used_question_ids) + 1}"
    used_question_ids.add(question_id)
    normalized = question.model_copy(update={"question_id": question_id, "skill_id": skill_id, "question_type": "topic"})
    return constrain_question_for_two_minutes(normalized)


def _normalize_rubric(rubric: list[RubricItem]) -> list[RubricItem]:
    max_score = max((item.score for item in rubric), default=100)
    if 0 < max_score <= 5:
        return [
            item.model_copy(update={"score": round(item.score * 100 / max_score)})
            for item in rubric
        ]
    return rubric


def _normalize_follow_up_triggers(triggers: list[FollowUpTrigger]) -> list[FollowUpTrigger]:
    by_type = {trigger.trigger_type: trigger for trigger in triggers}
    by_type.setdefault(
        "missing_concept",
        FollowUpTrigger(
            trigger_type="missing_concept",
            description="If expected concepts are missing from the answer.",
        ),
    )
    by_type.setdefault(
        "shallow_answer",
        FollowUpTrigger(
            trigger_type="shallow_answer",
            description="If the answer lacks concrete implementation detail or reasoning.",
        ),
    )
    ordered_types = ["missing_concept", "shallow_answer", "contradiction", "seniority_gap"]
    return [by_type[trigger_type] for trigger_type in ordered_types if trigger_type in by_type]
