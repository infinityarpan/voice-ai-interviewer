from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    def generate_json(self, prompt: str, response_model: type[ResponseModel]) -> ResponseModel:
        """Return a Pydantic-validated structured response for the requested model."""
