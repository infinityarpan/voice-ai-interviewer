import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEndResponse,
    InterviewReport,
    InterviewSessionState,
    InterviewStartRequest,
    InterviewStartResponse,
)
from app.schemas.voice import VoiceProviderStatus, VoiceSessionResponse, VoiceTranscriptSubmitRequest, VoiceTurnResponse
from app.services.interview_engine.orchestrator import InterviewEngine
from app.services.interview_engine.store import create_interview_store
from app.services.voice.realtime import VoiceProviderError, create_voice_service

router = APIRouter(prefix="/interviews", tags=["interviews"])
logger = logging.getLogger(__name__)

store = create_interview_store()
engine = InterviewEngine(store=store)
voice_service = create_voice_service()


@router.get("/voice/status", response_model=VoiceProviderStatus)
def voice_status() -> VoiceProviderStatus:
    return voice_service.status()


@router.post("/start", response_model=InterviewStartResponse)
def start_interview(payload: InterviewStartRequest) -> InterviewStartResponse:
    return engine.start(payload)


@router.post("/{session_id}/answer", response_model=InterviewAnswerResponse)
def submit_answer(session_id: str, payload: InterviewAnswerRequest) -> InterviewAnswerResponse:
    try:
        return engine.answer(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/end", response_model=InterviewEndResponse)
def end_interview(session_id: str) -> InterviewEndResponse:
    try:
        return engine.end(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc


@router.post("/{session_id}/voice/realtime-token", response_model=VoiceSessionResponse)
def create_realtime_voice_session(session_id: str) -> VoiceSessionResponse:
    try:
        state = engine.get_state(session_id)
        return voice_service.create_realtime_session(state)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoiceProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{session_id}/voice/answer", response_model=VoiceTurnResponse)
def submit_voice_answer(session_id: str, payload: VoiceTranscriptSubmitRequest) -> VoiceTurnResponse:
    try:
        answer_response = engine.answer(
            session_id,
            InterviewAnswerRequest(
                answer_text=payload.transcript_text,
                answer_source="voice",
                transcript_confidence=payload.transcript_confidence,
                audio_duration_seconds=payload.audio_duration_seconds,
            ),
        )
        return VoiceTurnResponse(
            session_id=session_id,
            transcript_text=payload.transcript_text,
            evaluation=answer_response.evaluation,
            policy_decision=answer_response.policy_decision,
            next_question=answer_response.next_question,
            next_question_text=answer_response.next_question.question_text if answer_response.next_question else None,
            state=answer_response.state,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/voice/client-log")
def log_voice_client_event(session_id: str, payload: dict[str, Any]) -> dict[str, bool]:
    logger.info("voice_client_event session_id=%s payload=%s", session_id, payload)
    return {"logged": True}


@router.get("/{session_id}/state", response_model=InterviewSessionState)
def get_state(session_id: str) -> InterviewSessionState:
    try:
        return engine.get_state(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc


@router.get("/{session_id}/report", response_model=InterviewReport)
def get_report(session_id: str) -> InterviewReport:
    try:
        return engine.report(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
