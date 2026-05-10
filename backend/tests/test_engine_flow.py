from fastapi.testclient import TestClient

from app.main import app


def test_start_text_answer_and_report_flow():
    client = TestClient(app)
    session_id = _start_session(client)

    answer = client.post(
        f"/interviews/{session_id}/answer",
        json={"answer_text": "I used Python APIs because pagination and validation kept the service reliable."},
    )
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["evaluation"]["score"] >= 0
    assert payload["state"]["turns"][0]["answer_source"] == "text"

    report = client.get(f"/interviews/{session_id}/report")
    assert report.status_code == 200
    assert report.json()["session_id"] == session_id


def test_voice_answer_and_manual_end_flow():
    client = TestClient(app)
    session_id = _start_session(client)

    voice_answer = client.post(
        f"/interviews/{session_id}/voice/answer",
        json={
            "transcript_text": "I designed a backend because the system needed clear API boundaries.",
            "audio_duration_seconds": 12.5,
        },
    )
    assert voice_answer.status_code == 200
    payload = voice_answer.json()
    assert payload["state"]["turns"][0]["answer_source"] == "voice"
    assert payload["next_question_text"] == (payload["next_question"] or {}).get("question_text")

    ended = client.post(f"/interviews/{session_id}/end")
    assert ended.status_code == 200
    assert ended.json()["state"]["status"] == "completed"
    assert ended.json()["report"]["overall_score"] >= 0


def test_removed_debug_state_endpoint_is_not_public():
    client = TestClient(app)
    session_id = _start_session(client)

    response = client.get(f"/interviews/{session_id}/state")

    assert response.status_code == 404


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
    payload = response.json()
    assert payload["first_question"]["question_text"]
    return payload["session_id"]
