from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.routes import interviews
from app.static.voice_test import VOICE_TEST_HTML

app = FastAPI(title="AI Interviewer Engine")

app.include_router(interviews.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/voice-test", response_class=HTMLResponse)
def voice_test() -> str:
    return VOICE_TEST_HTML
