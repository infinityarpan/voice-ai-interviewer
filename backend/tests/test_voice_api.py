import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.api.routes.interviews import engine


def test_voice_realtime_token_returns_mock_session_for_active_interview():
    client = TestClient(app)
    session_id = _start_session(client)

    response = client.post(f"/interviews/{session_id}/voice/realtime-token")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["provider"] == "mock"
    assert payload["client_secret"] == "mock-client-secret"
    assert payload["question_text"]
    assert "Do not invent new interview questions" in payload["instructions"]


def test_voice_status_reports_configured_mock_provider():
    client = TestClient(app)

    response = client.get("/interviews/voice/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["available"] is True
    assert "timing" not in payload


def test_voice_realtime_token_rejects_missing_session():
    client = TestClient(app)

    response = client.post("/interviews/missing/voice/realtime-token")

    assert response.status_code == 404


def test_voice_realtime_token_rejects_completed_session():
    client = TestClient(app)
    session_id = _start_session(client)
    client.post(f"/interviews/{session_id}/end")

    response = client.post(f"/interviews/{session_id}/voice/realtime-token")

    assert response.status_code == 400
    assert response.json()["detail"] == "Interview is already completed"


def test_voice_answer_uses_engine_answer_path_and_marks_turn_as_voice():
    client = TestClient(app)
    session_id = _start_session(client)

    response = client.post(
        f"/interviews/{session_id}/voice/answer",
        json={
            "transcript_text": "I built Python APIs because the team needed reliable pagination.",
            "transcript_confidence": 0.92,
            "audio_duration_seconds": 14.5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["transcript_text"].startswith("I built Python APIs")
    assert payload["evaluation"]["score"] >= 0
    first_turn = payload["state"]["turns"][0]
    assert first_turn["answer_source"] == "voice"
    assert first_turn["transcript_confidence"] == 0.92
    assert first_turn["audio_duration_seconds"] == 14.5
    if payload["next_question"]:
        assert payload["next_question_text"] == payload["next_question"]["question_text"]


def test_voice_answer_rejects_blank_transcript():
    client = TestClient(app)
    session_id = _start_session(client)

    response = client.post(f"/interviews/{session_id}/voice/answer", json={"transcript_text": "   "})

    assert response.status_code == 422


def test_voice_stream_accepts_latency_marks_then_final_transcript_advances():
    client = TestClient(app)
    session_id = _start_session(client)

    with client.websocket_connect(f"/interviews/{session_id}/voice/stream") as websocket:
        assert websocket.receive_json()["type"] == "connected"

        websocket.send_json({"type": "latency_mark", "name": "test_mark", "at_ms": 12})
        assert websocket.receive_json()["type"] == "latency_mark_ack"
        assert engine.get_state(session_id).turns[0].answer_text is None

        websocket.send_json(
            {
                "type": "transcript_final",
                "transcript_text": "I built Python APIs because pagination made the service reliable.",
                "audio_duration_seconds": 8.4,
            }
        )
        result = websocket.receive_json()

    assert result["type"] == "voice_turn_result"
    payload = result["payload"]
    assert payload["session_id"] == session_id
    assert payload["transcript_text"].startswith("I built Python APIs")
    assert payload["state"]["turns"][0]["answer_source"] == "voice"
    assert payload["state"]["turns"][0]["audio_duration_seconds"] == 8.4
    if payload["next_question"]:
        assert payload["next_question_text"] == payload["next_question"]["question_text"]


def test_voice_stream_rejects_missing_session():
    client = TestClient(app)

    with client.websocket_connect("/interviews/missing/voice/stream") as websocket:
        assert websocket.receive_json() == {"type": "error", "detail": "Interview session not found"}
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        assert closed.value.code == 1008


def test_voice_stream_rejects_completed_session():
    client = TestClient(app)
    session_id = _start_session(client)
    client.post(f"/interviews/{session_id}/end")

    with client.websocket_connect(f"/interviews/{session_id}/voice/stream") as websocket:
        assert websocket.receive_json() == {"type": "error", "detail": "Interview is already completed"}
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        assert closed.value.code == 1008


def test_voice_test_page_loads_with_expected_controls():
    client = TestClient(app)

    response = client.get("/voice-test")

    assert response.status_code == 200
    assert "Start interview" in response.text
    assert "End interview" in response.text
    assert 'href="/static/styles.css"' in response.text
    assert 'src="/static/voice.js"' in response.text
    assert "Connect voice" not in response.text
    assert "Disconnect voice" not in response.text
    assert 'id="uiState"' in response.text
    assert "<pre" not in response.text
    assert "<h2>Status</h2>" not in response.text
    assert "Voice diagnostics" in response.text
    assert "Microphone" in response.text
    assert "Mic level" in response.text
    assert "Latest transcript" in response.text
    assert "Start answer" not in response.text
    assert "Stop answer" not in response.text
    assert "Submit answer" not in response.text
    assert "Speak current question" not in response.text
    assert "autoHandsFree" not in response.text


def test_voice_test_static_assets_load():
    client = TestClient(app)

    styles = client.get("/static/styles.css")
    script = client.get("/static/voice.js")

    assert styles.status_code == 200
    assert "grid-template-columns" in styles.text
    assert script.status_code == 200
    assert "Hands-free mode" in script.text
    assert "WebSocket" in script.text
    assert "voice/stream" in script.text
    assert "transcript_final" in script.text
    assert "transcript_delta" not in script.text
    assert "latency_mark" in script.text
    assert "markLatency" in script.text
    assert "AUTO_SILENCE_MS" in script.text
    assert "const AUTO_SILENCE_MS = 1400" in script.text
    assert "const AUTO_START_AFTER_QUESTION_MS = 250" in script.text
    assert "const AUTO_SUBMIT_DELAY_MS = 100" in script.text
    assert "const MIN_RECORDING_MS = 1200" in script.text
    assert "DEFAULT_VOICE_TIMING" not in script.text
    assert "applyVoiceTiming" not in script.text
    assert "scheduleAutoSubmit" in script.text
    assert "selectedAudioConstraints" in script.text
    assert "RTCPeerConnection" in script.text
    assert "input_audio_buffer.commit" in script.text
    assert "output_modalities" in script.text
    assert "response.modalities" not in script.text
    assert "MIN_RECORDING_MS" in script.text
    assert "transcriptRejected" in script.text
    assert "Verbatim English transcription only" in script.text
    assert "transcriptLooksHallucinatedForDuration" in script.text
    assert "conversation.item.input_audio_transcription.completed" in script.text
    assert "conversation.item.input_audio_transcription.failed" in script.text


def _start_session(client: TestClient) -> str:
    response = client.post(
        "/interviews/start",
        json={
            "job_description": "Build backend APIs in Python.",
            "candidate_profile": "Python developer with API experience.",
            "role_level": "Associate",
            "required_skills": ["python", "apis"],
            "role_title": "Backend Engineer",
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]
