from app.ai.base import LLMProvider
from app.ai.mock import MockLLMProvider
from app.core.config import get_settings


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.ai_provider == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if settings.ai_provider == "mock":
        return MockLLMProvider()
    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
