import json
from typing import Any

from app.ai.base import LLMProvider, ResponseModel
from app.core.config import get_settings


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.openai_llm_model
        resolved_key = api_key or settings.openai_api_key
        if not resolved_key:
            raise RuntimeError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        from openai import OpenAI

        self.client = OpenAI(api_key=resolved_key)

    def generate_json(self, prompt: str, response_model: type[ResponseModel]) -> ResponseModel:
        schema = _strict_json_schema(response_model.model_json_schema())
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": "Return strict JSON that matches the supplied schema."},
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return response_model.model_validate_json(_response_text(response))


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    if chunks:
        return "".join(chunks)
    return json.dumps(response)


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    hardened = json.loads(json.dumps(schema))
    _harden_schema_node(hardened)
    return hardened


def _harden_schema_node(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties") or {}
            node["additionalProperties"] = False
            node["required"] = list(properties.keys())
        for value in node.values():
            _harden_schema_node(value)
    elif isinstance(node, list):
        for item in node:
            _harden_schema_node(item)
