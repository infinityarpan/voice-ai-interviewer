import re
import logging
from time import perf_counter
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from app.ai.provider import LLMProvider, get_llm_provider
from app.core.config import get_settings
from app.schemas.interview import (
    AnswerEvaluation,
    FollowUpTrigger,
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEndResponse,
    InterviewPlan,
    InterviewQuestion,
    InterviewReport,
    InterviewSessionState,
    InterviewSkillPlan,
    InterviewStartRequest,
    InterviewStartResponse,
    InterviewTurn,
    PolicyAction,
    PolicyDecision,
    RubricItem,
    SkillRuntimeState,
    SkillScore,
)
from app.services.interview_engine.store import InterviewStore

logger = logging.getLogger(__name__)

INITIAL_SHORTLIST_CONTEXT = (
    "This is an initial recruiter shortlist screen for a recruitment firm serving multiple clients. "
    "The goal is to collect broad first-round suitability signals, not make a final technical hiring decision. "
    "Ask broad role-relevant questions and avoid deep implementation drills unless needed to clarify a clear risk. "
    "A plausible candidate can be recommended for the first round even if they are not yet proven strong."
)
MAX_QUESTION_WORDS = 45
TWO_MINUTE_INSTRUCTION = "Answer in about 2 minutes."


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
        turn_started = perf_counter()
        logger.info("voice latency: transcript received session_id=%s source=%s", session_id, request.answer_source)
        state = self.store.get(session_id)
        if state.status == "completed":
            raise ValueError("Interview is already completed")
        active_turn = self._active_turn(state)
        if not active_turn:
            raise ValueError("No active question is available")

        skill = self._skill_by_id(state, active_turn.skill_id)
        evaluation_started = perf_counter()
        logger.info("voice latency: evaluation start session_id=%s", session_id)
        evaluation = self.evaluator.evaluate(active_turn.question, request.answer_text, skill)
        logger.info("voice latency: evaluation end session_id=%s elapsed_ms=%s", session_id, elapsed_ms(evaluation_started))
        active_turn.answer_text = request.answer_text
        active_turn.answer_source = request.answer_source
        active_turn.transcript_confidence = request.transcript_confidence
        active_turn.audio_duration_seconds = request.audio_duration_seconds
        active_turn.evaluation = evaluation
        state.skill_states[skill.skill_id].turns += 1

        decision = self.policy.decide(state, skill.skill_id, evaluation)
        logger.info("voice latency: policy decision session_id=%s action=%s", session_id, decision.action)
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
        logger.info("voice latency: save complete session_id=%s total_ms=%s", session_id, elapsed_ms(turn_started))
        return InterviewAnswerResponse(
            session_id=session_id,
            evaluation=evaluation,
            policy_decision=decision,
            next_question=next_question,
            state=state,
        )

    def end(self, session_id: str) -> InterviewEndResponse:
        state = self.store.get(session_id)
        self._complete_state(state, "manual_end")
        self._touch(state)
        self.store.save(state)
        return InterviewEndResponse(session_id=session_id, report=self.report_generator.generate(state), state=state)

    def report(self, session_id: str) -> InterviewReport:
        return self.report_generator.generate(self.store.get(session_id))

    def get_state(self, session_id: str) -> InterviewSessionState:
        return self.store.get(session_id)

    def _next_question_for_decision(
        self,
        state: InterviewSessionState,
        current_skill_id: str,
        evaluation: AnswerEvaluation,
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
        state.turns.append(InterviewTurn(turn_id=str(uuid4()), skill_id=question.skill_id, question=question))

    def _active_turn(self, state: InterviewSessionState) -> InterviewTurn | None:
        if state.turns and state.turns[-1].answer_text is None:
            return state.turns[-1]
        return None

    def _skill_by_id(self, state: InterviewSessionState, skill_id: str) -> InterviewSkillPlan:
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
        if action == PolicyAction.END_INTERVIEW:
            return "policy_completed"
        return "question_budget_reached" if action in {PolicyAction.ASK_FOLLOWUP, PolicyAction.ASK_CLARIFICATION, PolicyAction.ASK_NEXT_TOPIC} else "max_turns"

    def _touch(self, state: InterviewSessionState) -> None:
        state.updated_at = datetime.now(UTC)


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
        limited_plan = limit_plan_questions(
            plan,
            max_required_skills=request.config.max_required_skills_per_interview,
            max_main_questions_per_skill=request.config.max_main_questions_per_skill,
        )
        return normalize_plan(limited_plan)


class QuestionGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def first_question(self, state: InterviewSessionState) -> InterviewQuestion:
        skill = state.plan.skills[0]
        return self._first_unused_from_plan(skill, state) or self.next_topic_question(state, skill.skill_id)

    def next_topic_question(self, state: InterviewSessionState, skill_id: str) -> InterviewQuestion:
        skill = skill_by_id(state, skill_id)
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


class FollowUpGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.mode = get_settings().followup_generation_mode

    def generate(
        self,
        state: InterviewSessionState,
        skill: InterviewSkillPlan,
        evaluation: AnswerEvaluation,
        question_type: Literal["follow_up", "clarification"] = "follow_up",
    ) -> InterviewQuestion:
        if self.mode == "template":
            return self._template_question(state, skill, evaluation, question_type)

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

    def _template_question(
        self,
        state: InterviewSessionState,
        skill: InterviewSkillPlan,
        evaluation: AnswerEvaluation,
        question_type: Literal["follow_up", "clarification"],
    ) -> InterviewQuestion:
        if question_type == "clarification":
            text = f"Could you clarify your {skill.skill_name} experience with one concrete example and what you personally did?"
        elif evaluation.contradiction_detected:
            text = f"I heard a possible inconsistency in your {skill.skill_name} answer. Could you clarify the tradeoff and your actual approach?"
        elif evaluation.missing_signals:
            missing = evaluation.missing_signals[0]
            text = f"Could you expand on {missing} in your {skill.skill_name} example and explain the decision you made?"
        elif evaluation.shallow_answer:
            text = f"Could you make your {skill.skill_name} answer more concrete by walking through one real decision and why you chose it?"
        else:
            text = f"Could you add one practical {skill.skill_name} example that shows your reasoning and tradeoffs?"
        return constrain_question_for_two_minutes(
            InterviewQuestion(
                question_id=f"{question_type}-{skill.skill_id}-{len(state.turns) + 1}",
                skill_id=skill.skill_id,
                question_text=text,
                question_type=question_type,
            )
        )


class InterviewPolicyEngine:
    coverage_score_threshold = 75
    low_confidence_threshold = 0.35

    def decide(self, state: InterviewSessionState, skill_id: str, evaluation: AnswerEvaluation) -> PolicyDecision:
        skill_state = state.skill_states[skill_id]
        has_followup_budget = skill_state.followups_asked < state.config.max_followups_per_skill

        if not evaluation.evidence and evaluation.score == 0 and has_followup_budget:
            return PolicyDecision(action=PolicyAction.ASK_CLARIFICATION, skill_id=skill_id, reason="Answer was empty.")

        needs_followup = evaluation.follow_up_needed or evaluation.shallow_answer or evaluation.contradiction_detected or bool(evaluation.missing_signals)
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
        for skill_id in skill_ids[start:] + skill_ids[:start]:
            if skill_id != after_skill_id and not state.skill_states[skill_id].covered:
                return skill_id
        return None

    def _all_skills_covered(self, state: InterviewSessionState) -> bool:
        return all(skill_state.covered for skill_state in state.skill_states.values())


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
                    positive_signals=unique(signal for evaluation in evaluations for signal in evaluation.positive_signals),
                    missing_signals=unique(signal for evaluation in evaluations for signal in evaluation.missing_signals),
                    evidence=unique(item for evaluation in evaluations for item in evaluation.evidence),
                )
            )
        overall = round(sum(score.score for score in skill_scores) / len(skill_scores), 1) if skill_scores else 0.0
        return skill_scores, overall


class ReportGenerator:
    def __init__(self, provider: LLMProvider, aggregator: ScoreAggregator | None = None) -> None:
        self.provider = provider
        self.aggregator = aggregator or ScoreAggregator()

    def generate(self, state: InterviewSessionState) -> InterviewReport:
        skill_scores, overall = self.aggregator.aggregate(state)
        strengths = unique(signal for score in skill_scores for signal in score.positive_signals)
        weaknesses = unique(signal for score in skill_scores for signal in score.missing_signals)
        evidence = unique(item for score in skill_scores for item in score.evidence)
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


def shortlist_context_lines() -> list[str]:
    return [
        INITIAL_SHORTLIST_CONTEXT,
        "Optimize for broad coverage, communication clarity, practical exposure, and obvious red flags.",
        "Do not reject candidates for missing low-level details during this initial screen.",
    ]


def limit_plan_questions(
    plan: InterviewPlan,
    max_required_skills: int,
    max_main_questions_per_skill: int = 1,
) -> InterviewPlan:
    limited_skills: list[InterviewSkillPlan] = []
    for skill in plan.skills:
        if len(limited_skills) >= max_required_skills:
            break
        primary_questions = topic_questions(skill)[:max_main_questions_per_skill]
        limited_skills.append(skill.model_copy(update={"questions": primary_questions}))
    if not limited_skills:
        first_skill = plan.skills[0]
        limited_skills = [first_skill.model_copy(update={"questions": [topic_questions(first_skill)[0]]})]
    return plan.model_copy(update={"skills": limited_skills})


def topic_questions(skill: InterviewSkillPlan) -> list[InterviewQuestion]:
    topic_questions_list = [question for question in skill.questions if question.question_type == "topic"]
    if topic_questions_list:
        return topic_questions_list
    return [skill.questions[0].model_copy(update={"question_type": "topic"})]


def normalize_plan(plan: InterviewPlan) -> InterviewPlan:
    used_skill_ids: dict[str, int] = {}
    used_question_ids: set[str] = set()
    normalized_skills: list[InterviewSkillPlan] = []
    for skill in plan.skills:
        skill_id = unique_skill_id(skill.skill_id, used_skill_ids)
        normalized_questions = [normalize_question(question, skill_id, used_question_ids) for question in skill.questions]
        normalized_skills.append(
            skill.model_copy(
                update={
                    "skill_id": skill_id,
                    "questions": normalized_questions,
                    "rubric": normalize_rubric(skill.rubric),
                    "follow_up_triggers": normalize_follow_up_triggers(skill.follow_up_triggers),
                }
            )
        )
    return plan.model_copy(update={"skills": normalized_skills})


def unique_skill_id(skill_id: str, used_skill_ids: dict[str, int]) -> str:
    base_id = skill_id.strip() or "skill"
    count = used_skill_ids.get(base_id, 0) + 1
    used_skill_ids[base_id] = count
    return base_id if count == 1 else f"{base_id}-{count}"


def normalize_question(question: InterviewQuestion, skill_id: str, used_question_ids: set[str]) -> InterviewQuestion:
    question_id = question.question_id.strip() or f"{skill_id}_topic"
    if question_id in used_question_ids:
        question_id = f"{question_id}_{len(used_question_ids) + 1}"
    used_question_ids.add(question_id)
    normalized = question.model_copy(update={"question_id": question_id, "skill_id": skill_id, "question_type": "topic"})
    return constrain_question_for_two_minutes(normalized)


def normalize_rubric(rubric: list[RubricItem]) -> list[RubricItem]:
    max_score = max((item.score for item in rubric), default=100)
    if 0 < max_score <= 5:
        return [item.model_copy(update={"score": round(item.score * 100 / max_score)}) for item in rubric]
    return rubric


def normalize_follow_up_triggers(triggers: list[FollowUpTrigger]) -> list[FollowUpTrigger]:
    by_type = {trigger.trigger_type: trigger for trigger in triggers}
    by_type.setdefault(
        "missing_concept",
        FollowUpTrigger(trigger_type="missing_concept", description="If expected concepts are missing from the answer."),
    )
    by_type.setdefault(
        "shallow_answer",
        FollowUpTrigger(trigger_type="shallow_answer", description="If the answer lacks concrete implementation detail or reasoning."),
    )
    ordered_types = ["missing_concept", "shallow_answer", "contradiction", "seniority_gap"]
    return [by_type[trigger_type] for trigger_type in ordered_types if trigger_type in by_type]


def constrain_question_for_two_minutes(question: InterviewQuestion) -> InterviewQuestion:
    text = single_prompt(strip_time_phrasing(question.question_text))
    text = limit_words(text, MAX_QUESTION_WORDS)
    if TWO_MINUTE_INSTRUCTION.lower() not in text.lower():
        text = f"{text} {TWO_MINUTE_INSTRUCTION}"
    return question.model_copy(update={"question_text": text})


def strip_time_phrasing(text: str) -> str:
    replacements = [
        "In about 2 minutes, ",
        "In about 2 minutes,",
        "Follow-up (about 2 minutes): ",
        "Follow-up (about 2 minutes):",
        "about 2 minutes",
    ]
    cleaned = text.strip()
    for value in replacements:
        cleaned = cleaned.replace(value, "")
    return cleaned.strip()


def single_prompt(text: str) -> str:
    parts = [part.strip() for part in text.replace("?", ".").split(".") if part.strip()]
    if not parts:
        return "Walk me through your approach."
    first = parts[0]
    if len(parts) > 1 and len(first.split()) < 18:
        first = f"{first}; {parts[1]}"
    return first.rstrip(".?") + "."


def limit_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    shortened = " ".join(words[:max_words]).rstrip(".,;:")
    return f"{shortened}."


def question_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", normalized)


def skill_by_id(state: InterviewSessionState, skill_id: str) -> InterviewSkillPlan:
    for skill in state.plan.skills:
        if skill.skill_id == skill_id:
            return skill
    raise ValueError(f"Unknown skill_id: {skill_id}")


def unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def elapsed_ms(start: float) -> int:
    return round((perf_counter() - start) * 1000)
