"""Cache key + row schema for LLM structuring results (ADR 0003). No external dependencies."""

import hashlib
from datetime import datetime

from pydantic import BaseModel


def cache_key(*, model: str, schema_name: str, schema_version: str, prompt: str) -> str:
    material = f"{model}\x1f{schema_name}\x1f{schema_version}\x1f{prompt}".encode()
    return hashlib.sha256(material).hexdigest()


class LlmCacheRow(BaseModel):
    key: str
    model: str
    schema_name: str
    schema_version: str
    created_at: datetime
    input_sha256: str
    output: dict[str, object]
