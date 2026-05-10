from fastapi.testclient import TestClient

from app.main import app


def test_interview_api_smoke_flow():
    client = TestClient(app)

    start_response = client.post(
        "/interviews/start",
        json={
            "job_description": "Build backend APIs in Python.",
            "candidate_profile": "Python developer with API experience.",
            "role_level": "senior",
            "required_skills": ["python", "apis"],
            "role_title": "Backend Engineer",
        },
    )
    assert start_response.status_code == 200
    start_payload = start_response.json()
    session_id = start_payload["session_id"]
    assert start_payload["first_question"]["question_text"]
    assert start_payload["state"]["estimated_duration_minutes"] == 15
    assert start_payload["state"]["planned_question_count"] > 0
    assert start_payload["state"]["remaining_question_count"] > 0

    answer_response = client.post(
        f"/interviews/{session_id}/answer",
        json={"answer_text": "I designed python APIs because we needed clear tradeoffs and measured latency."},
    )
    assert answer_response.status_code == 200
    answer_payload = answer_response.json()
    assert answer_payload["evaluation"]["score"] >= 0
    assert answer_payload["policy_decision"]["action"] in {
        "ASK_FOLLOWUP",
        "ASK_NEXT_TOPIC",
        "ASK_CLARIFICATION",
        "END_INTERVIEW",
    }

    state_response = client.get(f"/interviews/{session_id}/state")
    assert state_response.status_code == 200
    assert state_response.json()["session_id"] == session_id

    report_response = client.get(f"/interviews/{session_id}/report")
    assert report_response.status_code == 200
    assert report_response.json()["session_id"] == session_id


def test_end_interview_endpoint_completes_session():
    client = TestClient(app)
    start_response = client.post(
        "/interviews/start",
        json={
            "job_description": "Build backend APIs in Python.",
            "candidate_profile": "Python developer with API experience.",
            "role_level": "senior",
            "required_skills": ["python"],
        },
    )
    session_id = start_response.json()["session_id"]

    end_response = client.post(f"/interviews/{session_id}/end")

    assert end_response.status_code == 200
    payload = end_response.json()
    assert payload["state"]["status"] == "completed"
    assert payload["state"]["completion_reason"] == "manual_end"
    assert payload["report"]["session_id"] == session_id
