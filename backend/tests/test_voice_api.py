from fastapi.testclient import TestClient

from app.main import app


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


def test_voice_client_log_endpoint_accepts_compact_status():
    client = TestClient(app)
    session_id = _start_session(client)

    response = client.post(
        f"/interviews/{session_id}/voice/client-log",
        json={"status": {"voice": "connected"}, "at": "2026-05-10T00:00:00Z"},
    )

    assert response.status_code == 200
    assert response.json() == {"logged": True}


def test_voice_test_page_loads_with_expected_controls():
    client = TestClient(app)

    response = client.get("/voice-test")

    assert response.status_code == 200
    assert "Start interview" in response.text
    assert "End interview" in response.text
    assert "Connect voice" not in response.text
    assert "Disconnect voice" not in response.text
    assert 'id="uiState"' in response.text
    assert "<pre" not in response.text
    assert "<h2>Status</h2>" not in response.text
    assert "Voice diagnostics" in response.text
    assert "Microphone" in response.text
    assert "Mic level" in response.text
    assert "Latest transcript" in response.text
    assert "Hands-free mode" in response.text
    assert "AUTO_SILENCE_MS" in response.text
    assert "scheduleAutoSubmit" in response.text
    assert "selectedAudioConstraints" in response.text
    assert "Start answer" not in response.text
    assert "Stop answer" not in response.text
    assert "Submit answer" not in response.text
    assert "Speak current question" not in response.text
    assert "autoHandsFree" not in response.text
    assert "RTCPeerConnection" in response.text
    assert "input_audio_buffer.commit" in response.text
    assert "output_modalities" in response.text
    assert "response.modalities" not in response.text
    assert "MIN_RECORDING_MS" in response.text
    assert "transcriptRejected" in response.text
    assert "Verbatim English transcription only" in response.text
    assert "transcriptLooksHallucinatedForDuration" in response.text
    assert "conversation.item.input_audio_transcription.completed" in response.text
    assert "conversation.item.input_audio_transcription.failed" in response.text


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
