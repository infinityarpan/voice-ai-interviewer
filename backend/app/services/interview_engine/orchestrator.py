from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from app.ai.base import LLMProvider
from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEndResponse,
    InterviewQuestion,
    InterviewReport,
    InterviewSessionState,
    InterviewStartRequest,
    InterviewStartResponse,
    InterviewTurn,
    PolicyAction,
    SkillRuntimeState,
)
from app.services.interview_engine.evaluator import AnswerEvaluator
from app.services.interview_engine.fingerprints import question_fingerprint
from app.services.interview_engine.followup_generator import FollowUpGenerator
from app.services.interview_engine.plan_generator import InterviewPlanGenerator
from app.services.interview_engine.policy import InterviewPolicyEngine
from app.services.interview_engine.providers import get_llm_provider
from app.services.interview_engine.question_generator import QuestionGenerator
from app.services.interview_engine.report_generator import ReportGenerator
from app.services.interview_engine.score_aggregator import ScoreAggregator
from app.services.interview_engine.store import InterviewStore


class InterviewEngine:
    def __init__(self, store: InterviewStore, provider: LLMProvider | None = None) -> None:
        self.store = store
        self.provider = provider or get_llm_provider()
        self.plan_generator = InterviewPlanGenerator(self.provider)
        self.question_generator = QuestionGenerator(self.provider)
        self.evaluator = AnswerEvaluator(self.provider)
        self.followup_generator = FollowUpGenerator(self.provider)
        self.policy = InterviewPolicyEngine()
        self.aggregator = ScoreAggregator()
        self.report_generator = ReportGenerator(self.provider, self.aggregator)

    def start(self, request: InterviewStartRequest) -> InterviewStartResponse:
        plan = self.plan_generator.generate(request)
        session_id = str(uuid4())
        state = InterviewSessionState(
            session_id=session_id,
            plan=plan,
            config=request.config,
            current_skill_id=plan.skills[0].skill_id,
            skill_states={
                skill.skill_id: SkillRuntimeState(skill_id=skill.skill_id, skill_name=skill.skill_name)
                for skill in plan.skills
            },
        )
        first_question = self.question_generator.first_question(state)
        self._record_question(state, first_question)
        self.store.save(state)
        return InterviewStartResponse(session_id=session_id, plan=plan, first_question=first_question, state=state)

    def answer(self, session_id: str, request: InterviewAnswerRequest) -> InterviewAnswerResponse:
        state = self.store.get(session_id)
        if state.status == "completed":
            raise ValueError("Interview is already completed")
        active_turn = self._active_turn(state)
        if not active_turn:
            raise ValueError("No active question is available")

        skill = self._skill_by_id(state, active_turn.skill_id)
        evaluation = self.evaluator.evaluate(active_turn.question, request.answer_text, skill)
        active_turn.answer_text = request.answer_text
        active_turn.answer_source = getattr(request, "answer_source", "text")
        active_turn.transcript_confidence = getattr(request, "transcript_confidence", None)
        active_turn.audio_duration_seconds = getattr(request, "audio_duration_seconds", None)
        active_turn.evaluation = evaluation
        state.skill_states[skill.skill_id].turns += 1

        decision = self.policy.decide(state, skill.skill_id, evaluation)
        active_turn.policy_decision = decision

        next_question = None
        if state.remaining_question_count <= 0:
            self._complete_state(state, "question_budget_reached")
        else:
            next_question = self._next_question_for_decision(state, skill.skill_id, evaluation, decision.action)
        if next_question:
            self._record_question(state, next_question)
        elif state.status != "completed":
            self._complete_state(state, self._completion_reason_for(decision.action))
        self._touch(state)
        self.store.save(state)
        return InterviewAnswerResponse(
            session_id=session_id,
            evaluation=evaluation,
            policy_decision=decision,
            next_question=next_question,
            state=state,
        )

    def get_state(self, session_id: str) -> InterviewSessionState:
        return self.store.get(session_id)

    def end(self, session_id: str) -> InterviewEndResponse:
        state = self.store.get(session_id)
        self._complete_state(state, "manual_end")
        self._touch(state)
        self.store.save(state)
        return InterviewEndResponse(
            session_id=session_id,
            report=self.report_generator.generate(state),
            state=state,
        )

    def report(self, session_id: str) -> InterviewReport:
        state = self.store.get(session_id)
        return self.report_generator.generate(state)

    def _next_question_for_decision(
        self,
        state: InterviewSessionState,
        current_skill_id: str,
        evaluation,
        action: PolicyAction,
    ) -> InterviewQuestion | None:
        if len(state.turns) >= state.config.max_turns or state.remaining_question_count <= 0:
            return None
        if action == PolicyAction.ASK_FOLLOWUP:
            skill = self._skill_by_id(state, current_skill_id)
            state.skill_states[current_skill_id].followups_asked += 1
            return self.followup_generator.generate(state, skill, evaluation, "follow_up")
        if action == PolicyAction.ASK_CLARIFICATION:
            skill = self._skill_by_id(state, current_skill_id)
            state.skill_states[current_skill_id].followups_asked += 1
            return self.followup_generator.generate(state, skill, evaluation, "clarification")
        if action == PolicyAction.ASK_NEXT_TOPIC and state.current_skill_id:
            target_skill_id = self._next_uncovered_skill_id(state, current_skill_id)
            if target_skill_id:
                state.current_skill_id = target_skill_id
                return self.question_generator.next_topic_question(state, target_skill_id)
        return None

    def _record_question(self, state: InterviewSessionState, question: InterviewQuestion) -> None:
        fingerprint = question_fingerprint(question.question_text)
        if fingerprint in state.asked_question_fingerprints:
            question = question.model_copy(
                update={
                    "question_id": f"{question.question_id}-{len(state.turns) + 1}",
                    "question_text": f"{question.question_text} Please use a different concrete example than before.",
                }
            )
            fingerprint = question_fingerprint(question.question_text)
        state.asked_question_fingerprints.add(fingerprint)
        state.current_skill_id = question.skill_id
        self._touch(state)
        state.turns.append(
            InterviewTurn(
                turn_id=str(uuid4()),
                skill_id=question.skill_id,
                question=question,
            )
        )

    def _active_turn(self, state: InterviewSessionState) -> InterviewTurn | None:
        if state.turns and state.turns[-1].answer_text is None:
            return state.turns[-1]
        return None

    def _skill_by_id(self, state: InterviewSessionState, skill_id: str):
        for skill in state.plan.skills:
            if skill.skill_id == skill_id:
                return skill
        raise ValueError(f"Unknown skill_id: {skill_id}")

    def _next_uncovered_skill_id(self, state: InterviewSessionState, after_skill_id: str) -> str | None:
        skill_ids = [skill.skill_id for skill in state.plan.skills]
        start = skill_ids.index(after_skill_id) + 1 if after_skill_id in skill_ids else 0
        for skill_id in skill_ids[start:] + skill_ids[:start]:
            if skill_id != after_skill_id and not state.skill_states[skill_id].covered:
                return skill_id
        return None

    def _complete_state(
        self,
        state: InterviewSessionState,
        reason: Literal["policy_completed", "manual_end", "max_turns", "no_next_topic", "question_budget_reached"],
    ) -> None:
        state.status = "completed"
        state.completion_reason = reason
        state.completed_at = state.completed_at or datetime.now(UTC)

    def _completion_reason_for(
        self,
        action: PolicyAction,
    ) -> Literal["policy_completed", "max_turns", "no_next_topic", "question_budget_reached"]:
        # If the policy wanted to continue but the budget blocked the next question,
        # this interview ended by design rather than by wall-clock timeout.
        # This keeps voice interviews predictable around the target duration.
        if action == PolicyAction.END_INTERVIEW:
            return "policy_completed"
        if action in {PolicyAction.ASK_FOLLOWUP, PolicyAction.ASK_CLARIFICATION}:
            return "question_budget_reached"
        if action == PolicyAction.ASK_NEXT_TOPIC:
            return "question_budget_reached"
        return "max_turns"

    def _touch(self, state: InterviewSessionState) -> None:
        state.updated_at = datetime.now(UTC)

    def _topic_question_count(self, state: InterviewSessionState) -> int:
        return sum(1 for turn in state.turns if turn.question.question_type == "topic")
