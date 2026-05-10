from app.ai.base import LLMProvider
from app.schemas.interview import InterviewReport, InterviewSessionState
from app.services.interview_engine.prompt_context import shortlist_context_lines
from app.services.interview_engine.score_aggregator import ScoreAggregator


class ReportGenerator:
    def __init__(self, provider: LLMProvider, aggregator: ScoreAggregator | None = None) -> None:
        self.provider = provider
        self.aggregator = aggregator or ScoreAggregator()

    def generate(self, state: InterviewSessionState) -> InterviewReport:
        skill_scores, overall = self.aggregator.aggregate(state)
        strengths = _unique(signal for score in skill_scores for signal in score.positive_signals)
        weaknesses = _unique(signal for score in skill_scores for signal in score.missing_signals)
        evidence = _unique(item for score in skill_scores for item in score.evidence)
        prompt = "\n".join(
            [
                "Generate recruiter-ready interview report.",
                *shortlist_context_lines(),
                "Frame risks as first-round validation items unless the evidence shows a clear mismatch.",
                f"session_id={state.session_id}",
                f"overall_score={overall}",
                f"skills={[(score.skill_name, score.score) for score in skill_scores]}",
            ]
        )
        provider_report = self.provider.generate_json(prompt, InterviewReport)
        return provider_report.model_copy(
            update={
                "session_id": state.session_id,
                "overall_score": overall,
                "skill_scores": skill_scores,
                "strengths": strengths or provider_report.strengths,
                "weaknesses": weaknesses or provider_report.weaknesses,
                "evidence": evidence or provider_report.evidence,
                "risks": provider_report.risks,
                "next_round_suggestions": provider_report.next_round_suggestions,
            }
        )


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
