# AI Interviewer Engine

Minimal FastAPI backend for a controlled AI interview intelligence layer.

## Run

```powershell
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Docker

```powershell
docker compose up --build
```

The compose setup reads `.env`, serves the API on `http://localhost:8000`, and persists SQLite data under `./docker-data`.

## Core Endpoints

- `POST /interviews/start`
- `POST /interviews/{session_id}/answer`
- `POST /interviews/{session_id}/voice/realtime-token`
- `POST /interviews/{session_id}/voice/answer`
- `POST /interviews/{session_id}/end`
- `GET /interviews/{session_id}/report`
- `GET /voice-test`

## Test

```powershell
cd backend
pytest
```

The default AI provider is deterministic mock mode, so tests and local API calls do not need network access or API keys.

## Interview Runtime

`/interviews/start` returns a controlled interview plan as a question bank, but the engine asks one question at a time through `state.turns[-1].question`.

For voice-based candidate input, the backend controls interview length by question budget, not wall-clock cutoff. The default budget is designed to fit roughly 15 minutes:

```json
{
  "config": {
    "target_duration_minutes": 15,
    "max_required_skills_per_interview": 5,
    "max_main_questions_per_skill": 1,
    "max_followups_per_skill": 1,
    "max_turns": 10
  }
}
```

The session state includes `planned_question_count`, `remaining_question_count`, and `estimated_duration_minutes`. Once the question budget is exhausted, the next answer submission completes the interview with `completion_reason: "question_budget_reached"` instead of asking another question.

Technical pre-screening is coverage-first: the backend keeps at most five required skills, asks one main question per skill, and asks at most one follow-up or clarification per skill when the answer is weak, vague, contradictory, or missing key concepts. OpenAI may propose several questions per skill, but the backend normalizes the plan to one primary topic question per skill and lets policy decide any follow-ups.

## Voice Test

The first voice layer uses browser WebRTC for OpenAI Realtime STT/TTS, but the backend still controls the interview flow. Realtime speaks backend-generated questions and transcribes the candidate; `/interviews/{session_id}/voice/answer` submits the final transcript through the same policy/evaluation path as typed answers.

Open the minimal test page after starting Uvicorn:

```text
http://localhost:8000/voice-test
```

Mock voice mode is the default for tests. Real hands-free voice interviews require `VOICE_PROVIDER=openai_realtime`.

## Configuration

Recommended deployable MVP configuration:

```powershell
$env:AI_PROVIDER="openai"
$env:VOICE_PROVIDER="openai_realtime"
$env:INTERVIEW_STORE="sqlite"
$env:INTERVIEW_DB_PATH="interview_sessions.sqlite3"
$env:OPENAI_API_KEY="sk-..."
```

Local mock configuration:

```powershell
$env:AI_PROVIDER="mock"
$env:VOICE_PROVIDER="mock"
$env:INTERVIEW_STORE="memory"
```

Optional OpenAI provider:

```powershell
$env:AI_PROVIDER="openai"
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_LLM_MODEL="gpt-5.4-nano"
```

Optional OpenAI Realtime voice provider:

```powershell
$env:VOICE_PROVIDER="openai_realtime"
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_REALTIME_MODEL="gpt-realtime"
$env:OPENAI_REALTIME_VOICE="marin"
```
