from app.ai.base import LLMProvider
from app.schemas.interview import AnswerEvaluation, InterviewQuestion, InterviewSkillPlan
from app.services.interview_engine.prompt_context import shortlist_context_lines


class AnswerEvaluator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def evaluate(self, question: InterviewQuestion, answer_text: str, skill: InterviewSkillPlan) -> AnswerEvaluation:
        prompt = "\n".join(
            [
                "Evaluate the candidate answer against expected concepts and rubric.",
                *shortlist_context_lines(),
                "Score evidence shown in this short screen, but treat incomplete detail as a follow-up/first-round validation need rather than final rejection.",
                f"question={question.question_text}",
                f"answer={answer_text}",
                f"skill_name={skill.skill_name}",
                f"expected_concepts={','.join(concept.name for concept in skill.expected_concepts)}",
                f"rubric={'; '.join(item.description for item in skill.rubric)}",
            ]
        )
        evaluation = self.provider.generate_json(prompt, AnswerEvaluation)
        if not answer_text.strip():
            return evaluation.model_copy(
                update={
                    "score": 0,
                    "positive_signals": [],
                    "evidence": [],
                    "follow_up_needed": False,
                    "shallow_answer": False,
                }
            )
        return evaluation
