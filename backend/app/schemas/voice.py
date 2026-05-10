from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.interview import AnswerEvaluation, InterviewQuestion, InterviewSessionState, PolicyDecision


class VoiceProviderStatus(BaseModel):
    provider: Literal["mock", "openai_realtime"]
    available: bool
    model: str | None = None
    voice: str | None = None
    detail: str | None = None


class VoiceSessionResponse(BaseModel):
    session_id: str
    provider: Literal["mock", "openai_realtime"]
    client_secret: str
    realtime_url: str
    model: str
    voice: str
    question_text: str
    instructions: str
    expires_at: int | None = None


class VoiceTranscriptSubmitRequest(BaseModel):
    transcript_text: str = Field(min_length=1)
    transcript_confidence: float | None = Field(default=None, ge=0, le=1)
    audio_duration_seconds: float | None = Field(default=None, ge=0)

    @field_validator("transcript_text")
    @classmethod
    def transcript_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("transcript_text must not be blank")
        return stripped


class VoiceTurnResponse(BaseModel):
    session_id: str
    transcript_text: str
    evaluation: AnswerEvaluation
    policy_decision: PolicyDecision
    next_question: InterviewQuestion | None
    next_question_text: str | None
    state: InterviewSessionState
