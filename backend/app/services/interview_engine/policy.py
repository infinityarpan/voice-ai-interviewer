from app.schemas.interview import AnswerEvaluation, InterviewSessionState, PolicyAction, PolicyDecision


class InterviewPolicyEngine:
    coverage_score_threshold = 75
    low_confidence_threshold = 0.35

    def decide(self, state: InterviewSessionState, skill_id: str, evaluation: AnswerEvaluation) -> PolicyDecision:
        skill_state = state.skill_states[skill_id]
        has_followup_budget = skill_state.followups_asked < state.config.max_followups_per_skill

        if not evaluation.evidence and evaluation.score == 0 and has_followup_budget:
            return PolicyDecision(action=PolicyAction.ASK_CLARIFICATION, skill_id=skill_id, reason="Answer was empty.")

        needs_followup = (
            evaluation.follow_up_needed
            or evaluation.shallow_answer
            or evaluation.contradiction_detected
            or bool(evaluation.missing_signals)
        )
        if evaluation.confidence < self.low_confidence_threshold and has_followup_budget:
            return PolicyDecision(action=PolicyAction.ASK_CLARIFICATION, skill_id=skill_id, reason="Evaluation confidence was low.")

        if needs_followup and has_followup_budget:
            return PolicyDecision(action=PolicyAction.ASK_FOLLOWUP, skill_id=skill_id, reason="More evidence is needed for this skill.")

        skill_state.covered = True

        next_skill_id = self._next_uncovered_skill_id(state, after_skill_id=skill_id)
        if next_skill_id:
            return PolicyDecision(action=PolicyAction.ASK_NEXT_TOPIC, skill_id=next_skill_id, reason="Moving to the next uncovered skill.")

        if self._all_skills_covered(state) or len(state.turns) >= state.config.max_turns:
            return PolicyDecision(action=PolicyAction.END_INTERVIEW, reason="Interview coverage is complete.")

        return PolicyDecision(action=PolicyAction.END_INTERVIEW, reason="No valid next topic remains.")

    def _next_uncovered_skill_id(self, state: InterviewSessionState, after_skill_id: str) -> str | None:
        skill_ids = [skill.skill_id for skill in state.plan.skills]
        start = skill_ids.index(after_skill_id) + 1 if after_skill_id in skill_ids else 0
        ordered = skill_ids[start:] + skill_ids[:start]
        for skill_id in ordered:
            if skill_id != after_skill_id and not state.skill_states[skill_id].covered:
                return skill_id
        return None

    def _all_skills_covered(self, state: InterviewSessionState) -> bool:
        return all(skill_state.covered for skill_state in state.skill_states.values())
