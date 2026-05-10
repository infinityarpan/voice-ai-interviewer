from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class PolicyAction(StrEnum):
    ASK_FOLLOWUP = "ASK_FOLLOWUP"
    ASK_NEXT_TOPIC = "ASK_NEXT_TOPIC"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    END_INTERVIEW = "END_INTERVIEW"


class ExpectedConcept(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class RubricItem(BaseModel):
    score: int = Field(ge=0, le=100)
    description: str = Field(min_length=1)


class FollowUpTrigger(BaseModel):
    trigger_type: Literal["missing_concept", "shallow_answer", "contradiction", "seniority_gap"]
    description: str = Field(min_length=1)


class InterviewQuestion(BaseModel):
    question_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    question_type: Literal["topic", "follow_up", "clarification"] = "topic"


class InterviewSkillPlan(BaseModel):
    skill_id: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    target_depth: str = Field(min_length=1)
    questions: list[InterviewQuestion] = Field(min_length=1)
    expected_concepts: list[ExpectedConcept] = Field(min_length=1)
    rubric: list[RubricItem] = Field(min_length=1)
    follow_up_triggers: list[FollowUpTrigger] = Field(default_factory=list)


class InterviewPlan(BaseModel):
    role_title: str = Field(min_length=1)
    role_level: str = Field(min_length=1)
    skills: list[InterviewSkillPlan] = Field(min_length=1)


class AnswerEvaluation(BaseModel):
    score: float = Field(ge=0, le=100)
    positive_signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    follow_up_needed: bool
    contradiction_detected: bool = False
    shallow_answer: bool = False

    @field_validator("evidence")
    @classmethod
    def evidence_items_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("evidence items must not be blank")
        return value


class PolicyDecision(BaseModel):
    action: PolicyAction
    reason: str = Field(min_length=1)
    skill_id: str | None = None


class InterviewTurn(BaseModel):
    turn_id: str
    skill_id: str
    question: InterviewQuestion
    answer_text: str | None = None
    answer_source: Literal["text", "voice"] | None = None
    transcript_confidence: float | None = Field(default=None, ge=0, le=1)
    audio_duration_seconds: float | None = Field(default=None, ge=0)
    evaluation: AnswerEvaluation | None = None
    policy_decision: PolicyDecision | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InterviewConfig(BaseModel):
    target_duration_minutes: int = Field(default=15, ge=5, le=180)
    max_required_skills_per_interview: int = Field(default=5, ge=1, le=10)
    max_main_questions_per_skill: int = Field(default=1, ge=1, le=1)
    max_followups_per_skill: int = Field(default=1, ge=0, le=10)
    max_turns: int = Field(default=10, ge=1, le=50)


class InterviewStartRequest(BaseModel):
    job_description: str = Field(min_length=1)
    candidate_profile: str | dict = Field(default_factory=dict)
    role_level: str = Field(min_length=1)
    required_skills: list[str] = Field(min_length=1)
    role_title: str = "Target Role"
    config: InterviewConfig = Field(default_factory=InterviewConfig)


class InterviewAnswerRequest(BaseModel):
    answer_text: str
    answer_source: Literal["text", "voice"] = "text"
    transcript_confidence: float | None = Field(default=None, ge=0, le=1)
    audio_duration_seconds: float | None = Field(default=None, ge=0)


class SkillRuntimeState(BaseModel):
    skill_id: str
    skill_name: str
    covered: bool = False
    followups_asked: int = 0
    turns: int = 0


class InterviewSessionState(BaseModel):
    session_id: str
    plan: InterviewPlan
    config: InterviewConfig
    status: Literal["in_progress", "completed"] = "in_progress"
    completion_reason: Literal["policy_completed", "manual_end", "max_turns", "no_next_topic", "question_budget_reached"] | None = None
    current_skill_id: str | None = None
    turns: list[InterviewTurn] = Field(default_factory=list)
    skill_states: dict[str, SkillRuntimeState] = Field(default_factory=dict)
    asked_question_fingerprints: set[str] = Field(default_factory=set)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @computed_field
    @property
    def planned_question_count(self) -> int:
        per_skill_budget = self.config.max_main_questions_per_skill + self.config.max_followups_per_skill
        return min(
            self.config.max_turns,
            len(self.plan.skills) * per_skill_budget,
        )

    @computed_field
    @property
    def remaining_question_count(self) -> int:
        if self.status == "completed":
            return 0
        return max(0, self.planned_question_count - len(self.turns))

    @computed_field
    @property
    def estimated_duration_minutes(self) -> int:
        return self.config.target_duration_minutes

    model_config = ConfigDict(arbitrary_types_allowed=True)


class SkillScore(BaseModel):
    skill_id: str
    skill_name: str
    score: float = Field(ge=0, le=100)
    turns_evaluated: int = Field(ge=0)
    positive_signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class InterviewReport(BaseModel):
    session_id: str
    summary: str
    overall_score: float = Field(ge=0, le=100)
    skill_scores: list[SkillScore]
    strengths: list[str]
    weaknesses: list[str]
    evidence: list[str]
    risks: list[str]
    next_round_suggestions: list[str]


class InterviewStartResponse(BaseModel):
    session_id: str
    plan: InterviewPlan
    first_question: InterviewQuestion
    state: InterviewSessionState


class InterviewAnswerResponse(BaseModel):
    session_id: str
    evaluation: AnswerEvaluation
    policy_decision: PolicyDecision
    next_question: InterviewQuestion | None
    state: InterviewSessionState


class InterviewEndResponse(BaseModel):
    session_id: str
    report: InterviewReport
    state: InterviewSessionState
