from app.ai.base import LLMProvider
from app.schemas.interview import InterviewQuestion, InterviewSessionState, InterviewSkillPlan
from app.services.interview_engine.fingerprints import question_fingerprint
from app.services.interview_engine.prompt_context import shortlist_context_lines
from app.services.interview_engine.question_constraints import constrain_question_for_two_minutes


class QuestionGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def first_question(self, state: InterviewSessionState) -> InterviewQuestion:
        skill = state.plan.skills[0]
        return self._first_unused_from_plan(skill, state) or self.next_topic_question(state, skill.skill_id)

    def next_topic_question(self, state: InterviewSessionState, skill_id: str) -> InterviewQuestion:
        skill = _skill_by_id(state, skill_id)
        planned = self._first_unused_from_plan(skill, state)
        if planned:
            return planned
        prompt = "\n".join(
            [
                "Generate the next topic question.",
                "The question must be a single concise spoken prompt answerable in about 2 minutes.",
                "Ask for one focused scenario, decision, or explanation only.",
                *shortlist_context_lines(),
                f"skill_id={skill.skill_id}",
                f"skill_name={skill.skill_name}",
                "question_type=topic",
            ]
        )
        return constrain_question_for_two_minutes(self.provider.generate_json(prompt, InterviewQuestion))

    def _first_unused_from_plan(self, skill: InterviewSkillPlan, state: InterviewSessionState) -> InterviewQuestion | None:
        for question in skill.questions:
            if question_fingerprint(question.question_text) not in state.asked_question_fingerprints:
                return question
        return None


def _skill_by_id(state: InterviewSessionState, skill_id: str) -> InterviewSkillPlan:
    for skill in state.plan.skills:
        if skill.skill_id == skill_id:
            return skill
    raise ValueError(f"Unknown skill_id: {skill_id}")
