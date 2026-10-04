from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructurerUnavailableError(Exception):
    """Raised when no LLM credentials are configured (fail-closed, ADR 0003)."""


class Structurer(Protocol):
    def structure(self, prompt: str, schema: type[T], *, schema_version: str) -> T:
        """Turn free text into a validated instance of *schema*."""
        ...
