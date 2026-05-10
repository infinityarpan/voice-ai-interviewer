import json
import urllib.error
import urllib.request
from typing import Protocol

from app.core.config import get_settings
from app.schemas.interview import InterviewSessionState
from app.schemas.voice import VoiceProviderStatus, VoiceSessionResponse

REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
TRANSCRIPTION_PROMPT = (
    "Verbatim English transcription only. Write exactly what the candidate says, including short tests like hello. "
    "Do not answer the interview question, infer missing words, summarize, rewrite, or add technical content that "
    "was not spoken. If the audio is silence or unclear noise, return an empty transcript."
)


class VoiceProviderError(RuntimeError):
    pass


class VoiceService(Protocol):
    def create_realtime_session(self, state: InterviewSessionState) -> VoiceSessionResponse:
        ...

    def status(self) -> VoiceProviderStatus:
        ...


class MockVoiceService:
    def create_realtime_session(self, state: InterviewSessionState) -> VoiceSessionResponse:
        question_text = _active_question_text(state)
        return VoiceSessionResponse(
            session_id=state.session_id,
            provider="mock",
            client_secret="mock-client-secret",
            realtime_url=REALTIME_CALLS_URL,
            model="mock-realtime",
            voice="mock",
            question_text=question_text,
            instructions=_voice_instructions(question_text),
        )

    def status(self) -> VoiceProviderStatus:
        return VoiceProviderStatus(provider="mock", available=True, model="mock-realtime", voice="mock")


class OpenAIRealtimeVoiceService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def create_realtime_session(self, state: InterviewSessionState) -> VoiceSessionResponse:
        if not self.settings.openai_api_key:
            raise VoiceProviderError("OPENAI_API_KEY is required when VOICE_PROVIDER=openai_realtime")
        question_text = _active_question_text(state)
        instructions = _voice_instructions(question_text)
        body = {
            "session": {
                "type": "realtime",
                "model": self.settings.openai_realtime_model,
                "instructions": instructions,
                "audio": {
                    "output": {"voice": self.settings.openai_realtime_voice},
                    "input": {
                        "noise_reduction": {"type": "near_field"},
                        "turn_detection": None,
                        "transcription": {
                            "model": "gpt-4o-transcribe",
                            "language": "en",
                            "prompt": TRANSCRIPTION_PROMPT,
                        },
                    },
                },
            }
        }
        request = urllib.request.Request(
            CLIENT_SECRETS_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VoiceProviderError(f"OpenAI Realtime token request failed: {detail}") from exc
        except OSError as exc:
            raise VoiceProviderError(f"OpenAI Realtime token request failed: {exc}") from exc

        client_secret, expires_at = _extract_client_secret(payload)
        return VoiceSessionResponse(
            session_id=state.session_id,
            provider="openai_realtime",
            client_secret=client_secret,
            realtime_url=REALTIME_CALLS_URL,
            model=self.settings.openai_realtime_model,
            voice=self.settings.openai_realtime_voice,
            question_text=question_text,
            instructions=instructions,
            expires_at=expires_at,
        )

    def status(self) -> VoiceProviderStatus:
        return VoiceProviderStatus(
            provider="openai_realtime",
            available=bool(self.settings.openai_api_key),
            model=self.settings.openai_realtime_model,
            voice=self.settings.openai_realtime_voice,
            detail=None if self.settings.openai_api_key else "OPENAI_API_KEY is not configured",
        )


def create_voice_service() -> VoiceService:
    settings = get_settings()
    if settings.voice_provider == "openai_realtime":
        return OpenAIRealtimeVoiceService()
    return MockVoiceService()


def _active_question_text(state: InterviewSessionState) -> str:
    if state.status == "completed":
        raise ValueError("Interview is already completed")
    for turn in reversed(state.turns):
        if turn.answer_text is None:
            return turn.question.question_text
    raise ValueError("No active interview question is available")


def _voice_instructions(question_text: str) -> str:
    return (
        "You are the voice transport for a controlled AI interviewer. "
        "Speak only the backend-provided question exactly or transcribe the candidate's answer. "
        "Do not invent new interview questions. Do not evaluate the answer. "
        "Do not decide whether to ask follow-ups. The backend policy engine controls the interview. "
        "Transcribe candidate answers verbatim; do not answer the question or hallucinate words from silence. "
        f"Current question to speak exactly: {question_text}"
    )


def _extract_client_secret(payload: dict) -> tuple[str, int | None]:
    if isinstance(payload.get("value"), str):
        return payload["value"], payload.get("expires_at")
    client_secret = payload.get("client_secret")
    if isinstance(client_secret, dict) and isinstance(client_secret.get("value"), str):
        return client_secret["value"], client_secret.get("expires_at")
    if isinstance(payload.get("secret"), dict) and isinstance(payload["secret"].get("value"), str):
        return payload["secret"]["value"], payload["secret"].get("expires_at")
    raise VoiceProviderError("OpenAI Realtime response did not include a client secret")
