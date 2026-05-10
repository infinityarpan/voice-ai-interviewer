from app.ai.base import LLMProvider
from app.schemas.interview import AnswerEvaluation, InterviewQuestion, InterviewSessionState, InterviewSkillPlan
from app.services.interview_engine.prompt_context import shortlist_context_lines
from app.services.interview_engine.question_constraints import constrain_question_for_two_minutes


class FollowUpGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def generate(
        self,
        state: InterviewSessionState,
        skill: InterviewSkillPlan,
        evaluation: AnswerEvaluation,
        question_type: str = "follow_up",
    ) -> InterviewQuestion:
        prompt = "\n".join(
            [
                "Generate one deeper follow-up question.",
                "The follow-up must be a single concise spoken prompt answerable in about 2 minutes.",
                "Ask for one missing concept, one tradeoff, or one clarification only; do not turn this into a deep technical drill.",
                *shortlist_context_lines(),
                f"skill_id={skill.skill_id}",
                f"skill_name={skill.skill_name}",
                f"question_type={question_type}",
                f"missing_signals={','.join(evaluation.missing_signals)}",
                f"shallow_answer={evaluation.shallow_answer}",
                f"contradiction_detected={evaluation.contradiction_detected}",
                f"asked_count={len(state.asked_question_fingerprints)}",
            ]
        )
        question = self.provider.generate_json(prompt, InterviewQuestion)
        return constrain_question_for_two_minutes(question.model_copy(update={"question_type": question_type}))
