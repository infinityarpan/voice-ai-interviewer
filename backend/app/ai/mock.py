import re
from typing import Any

from app.ai.base import LLMProvider, ResponseModel
from app.schemas.interview import (
    AnswerEvaluation,
    ExpectedConcept,
    FollowUpTrigger,
    InterviewPlan,
    InterviewQuestion,
    InterviewReport,
    InterviewSkillPlan,
    RubricItem,
    SkillScore,
)


class MockLLMProvider(LLMProvider):
    """Deterministic provider for tests and local development."""

    def generate_json(self, prompt: str, response_model: type[ResponseModel]) -> ResponseModel:
        if response_model is InterviewPlan:
            return self._plan(prompt)  # type: ignore[return-value]
        if response_model is InterviewQuestion:
            return self._question(prompt)  # type: ignore[return-value]
        if response_model is AnswerEvaluation:
            return self._evaluation(prompt)  # type: ignore[return-value]
        if response_model is InterviewReport:
            return self._report(prompt)  # type: ignore[return-value]
        raise ValueError(f"MockLLMProvider does not support {response_model.__name__}")

    def _plan(self, prompt: str) -> InterviewPlan:
        skills = _extract_csv_marker(prompt, "required_skills") or ["problem solving"]
        role_level = _extract_marker(prompt, "role_level") or "mid"
        skill_plans = []
        for index, skill in enumerate(skills, start=1):
            concepts = [
                ExpectedConcept(name=f"{skill} fundamentals", description=f"Core understanding of {skill}."),
                ExpectedConcept(name=f"{skill} tradeoffs", description=f"Ability to discuss decisions and tradeoffs."),
            ]
            skill_plans.append(
                InterviewSkillPlan(
                    skill_id=f"skill-{index}",
                    skill_name=skill,
                    target_depth="senior" if role_level.lower() in {"senior", "staff", "principal", "lead"} else "working",
                    questions=[
                        InterviewQuestion(
                            question_id=f"q-{index}-1",
                            skill_id=f"skill-{index}",
                            question_text=f"Tell me about a real project where you used {skill} and the tradeoffs you considered.",
                            question_type="topic",
                        )
                    ],
                    expected_concepts=concepts,
                    rubric=[
                        RubricItem(score=40, description="Names relevant concepts but gives limited detail."),
                        RubricItem(score=70, description="Explains practical use with clear examples."),
                        RubricItem(score=90, description="Shows strong judgment, tradeoffs, and senior-level reasoning."),
                    ],
                    follow_up_triggers=[
                        FollowUpTrigger(trigger_type="missing_concept", description="Expected concept was not evidenced."),
                        FollowUpTrigger(trigger_type="shallow_answer", description="Answer lacks concrete depth."),
                    ],
                )
            )
        return InterviewPlan(
            role_title=_extract_marker(prompt, "role_title") or "Target Role",
            role_level=role_level,
            skills=skill_plans,
        )

    def _question(self, prompt: str) -> InterviewQuestion:
        skill_id = _extract_marker(prompt, "skill_id") or "skill-1"
        skill_name = _extract_marker(prompt, "skill_name") or "the target skill"
        question_type = _extract_marker(prompt, "question_type") or "topic"
        return InterviewQuestion(
            question_id=f"{question_type}-{skill_id}",
            skill_id=skill_id,
            question_text=f"Walk me through one concrete {skill_name} example and the reasoning behind your choices.",
            question_type=question_type,
        )

    def _evaluation(self, prompt: str) -> AnswerEvaluation:
        answer = (_extract_marker(prompt, "answer") or "").lower()
        expected = _extract_csv_marker(prompt, "expected_concepts")
        is_empty = not answer.strip()
        has_depth = any(token in answer for token in ["because", "tradeoff", "measured", "designed", "scaled", "debugged"])
        positive = [concept for concept in expected if concept.lower().split()[0] in answer]
        missing = [concept for concept in expected if concept not in positive]
        if is_empty:
            score = 0
            confidence = 0.95
            follow_up_needed = False
        elif has_depth and len(missing) == 0:
            score = 85
            confidence = 0.8
            follow_up_needed = False
        elif has_depth:
            score = 68
            confidence = 0.7
            follow_up_needed = True
        else:
            score = 45
            confidence = 0.65
            follow_up_needed = True
        return AnswerEvaluation(
            score=score,
            positive_signals=positive or ([] if is_empty else ["Relevant experience was mentioned."]),
            missing_signals=missing or ([] if not is_empty else expected),
            evidence=[] if is_empty else [answer[:180]],
            confidence=confidence,
            follow_up_needed=follow_up_needed,
            contradiction_detected="contradiction" in answer,
            shallow_answer=not is_empty and not has_depth,
        )

    def _report(self, prompt: str) -> InterviewReport:
        return InterviewReport(
            session_id=_extract_marker(prompt, "session_id") or "unknown",
            summary="Candidate responses were evaluated against the planned skills and rubric.",
            overall_score=float(_extract_marker(prompt, "overall_score") or 0),
            skill_scores=[],
            strengths=["Structured evidence was collected during the interview."],
            weaknesses=["Review missing signals for each skill before making a final decision."],
            evidence=["See turn-level evaluations for supporting examples."],
            risks=["Mock report should be replaced by provider-generated prose in production mode."],
            next_round_suggestions=["Probe the weakest covered skill with a practical system-design scenario."],
        )


def _extract_marker(prompt: str, name: str) -> str | None:
    match = re.search(rf"{re.escape(name)}=(.*)", prompt)
    if not match:
        return None
    return match.group(1).splitlines()[0].strip()


def _extract_csv_marker(prompt: str, name: str) -> list[str]:
    value = _extract_marker(prompt, name)
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
