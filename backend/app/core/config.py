from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # Allows tests to run before requirements are installed.
    load_dotenv = None

project_root_env = Path(__file__).resolve().parents[3] / ".env"
backend_env = Path(__file__).resolve().parents[2] / ".env"


def _load_env_file(path: Path) -> None:
    if load_dotenv:
        load_dotenv(path, override=False)
        return
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(project_root_env)
_load_env_file(backend_env)


class Settings(BaseModel):
    ai_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: str | None = None
    openai_llm_model: str = "gpt-5.4-nano"
    voice_provider: Literal["mock", "openai_realtime"] = "mock"
    openai_realtime_model: str = "gpt-realtime"
    openai_realtime_voice: str = "marin"
    interview_store: Literal["memory", "sqlite"] = "memory"
    interview_db_path: str = "interview_sessions.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        ai_provider=_literal_env("AI_PROVIDER", {"mock", "openai"}, "mock"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_llm_model=os.getenv("OPENAI_LLM_MODEL", "gpt-5.4-nano"),
        voice_provider=_literal_env("VOICE_PROVIDER", {"mock", "openai_realtime"}, "mock"),
        openai_realtime_model=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime"),
        openai_realtime_voice=os.getenv("OPENAI_REALTIME_VOICE", "marin"),
        interview_store=_literal_env("INTERVIEW_STORE", {"memory", "sqlite"}, "memory"),
        interview_db_path=os.getenv("INTERVIEW_DB_PATH", "interview_sessions.sqlite3"),
    )


def _literal_env(name: str, allowed: set[str], default: str):
    value = os.getenv(name, default).lower()
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value
