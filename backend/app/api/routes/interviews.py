import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEndResponse,
    InterviewReport,
    InterviewStartRequest,
    InterviewStartResponse,
)
from app.schemas.voice import VoiceProviderStatus, VoiceSessionResponse, VoiceTranscriptSubmitRequest, VoiceTurnResponse
from app.services.interview_engine.engine import InterviewEngine
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
        return _submit_voice_transcript(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.websocket("/{session_id}/voice/stream")
async def voice_stream(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        state = engine.get_state(session_id)
        if state.status == "completed":
            await websocket.send_json({"type": "error", "detail": "Interview is already completed"})
            await websocket.close(code=1008)
            return
    except KeyError:
        await websocket.send_json({"type": "error", "detail": "Interview session not found"})
        await websocket.close(code=1008)
        return

    await websocket.send_json({"type": "connected", "session_id": session_id})
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "latency_mark":
                logger.info("voice latency mark session_id=%s name=%s payload=%s", session_id, message.get("name"), message)
                await websocket.send_json({"type": "latency_mark_ack", "name": message.get("name")})
            elif message_type == "transcript_delta":
                text = str(message.get("text") or message.get("delta") or "").strip()
                logger.info("voice transcript delta session_id=%s chars=%s", session_id, len(text))
                await websocket.send_json({"type": "transcript_delta_ack", "chars": len(text)})
            elif message_type == "transcript_final":
                try:
                    payload = VoiceTranscriptSubmitRequest(
                        transcript_text=str(message.get("transcript_text") or message.get("text") or ""),
                        transcript_confidence=message.get("transcript_confidence"),
                        audio_duration_seconds=message.get("audio_duration_seconds"),
                    )
                    result = _submit_voice_transcript(session_id, payload)
                    await websocket.send_json({"type": "voice_turn_result", "payload": result.model_dump(mode="json")})
                except (ValidationError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                except KeyError:
                    await websocket.send_json({"type": "error", "detail": "Interview session not found"})
                    await websocket.close(code=1008)
                    return
            else:
                await websocket.send_json({"type": "error", "detail": f"Unsupported voice stream event: {message_type}"})
    except WebSocketDisconnect:
        logger.info("voice stream disconnected session_id=%s", session_id)


@router.get("/{session_id}/report", response_model=InterviewReport)
def get_report(session_id: str) -> InterviewReport:
    try:
        return engine.report(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc


def _submit_voice_transcript(session_id: str, payload: VoiceTranscriptSubmitRequest) -> VoiceTurnResponse:
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
