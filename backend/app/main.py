from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import interviews

app = FastAPI(title="AI Interviewer Engine")
STATIC_DIR = Path(__file__).parent / "static"

app.include_router(interviews.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/voice-test", response_class=FileResponse)
def voice_test() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
