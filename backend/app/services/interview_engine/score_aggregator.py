from app.schemas.interview import InterviewSessionState, SkillScore


class ScoreAggregator:
    def aggregate(self, state: InterviewSessionState) -> tuple[list[SkillScore], float]:
        skill_scores: list[SkillScore] = []
        for skill in state.plan.skills:
            evaluations = [
                turn.evaluation
                for turn in state.turns
                if turn.skill_id == skill.skill_id and turn.evaluation is not None
            ]
            if evaluations:
                score = round(sum(evaluation.score * evaluation.confidence for evaluation in evaluations) / sum(max(evaluation.confidence, 0.01) for evaluation in evaluations), 1)
            else:
                score = 0.0
            skill_scores.append(
                SkillScore(
                    skill_id=skill.skill_id,
                    skill_name=skill.skill_name,
                    score=score,
                    turns_evaluated=len(evaluations),
                    positive_signals=_unique(signal for evaluation in evaluations for signal in evaluation.positive_signals),
                    missing_signals=_unique(signal for evaluation in evaluations for signal in evaluation.missing_signals),
                    evidence=_unique(item for evaluation in evaluations for item in evaluation.evidence),
                )
            )
        overall = round(sum(score.score for score in skill_scores) / len(skill_scores), 1) if skill_scores else 0.0
        return skill_scores, overall


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
