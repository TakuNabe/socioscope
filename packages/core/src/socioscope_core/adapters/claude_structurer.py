"""Structurer backed by the Claude API with an append-only JSONL cache (ADR 0003)."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from socioscope_core.core.llm_cache import LlmCacheRow, cache_key
from socioscope_core.core.provenance import sha256_hex
from socioscope_core.ports.structurer import StructurerUnavailableError

T = TypeVar("T", bound=BaseModel)

SYSTEM = (
    "You convert public-source text into the given closed schema. "
    "Copy numbers exactly as written; "
    "never estimate, impute, or convert units. "
    "If a field is not present in the text, leave it null. "
    "Fill `source_quote` fields with the verbatim passage that supports the value."
)


class JsonlLlmCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, schema_name: str) -> Path:
        return self._root / f"{schema_name}.jsonl"

    def get(self, schema_name: str, key: str) -> LlmCacheRow | None:
        path = self._path(schema_name)
        if not path.exists():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = LlmCacheRow.model_validate_json(line)
                if row.key == key:
                    return row
        return None

    def append(self, row: LlmCacheRow) -> None:
        path = self._path(row.schema_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(row.model_dump_json() + "\n")


class ClaudeStructurer:
    """Call `messages.parse` once per (model, schema, version, prompt); replay from cache after."""

    def __init__(
        self,
        *,
        cache: JsonlLlmCache,
        model: str,
        api_key: str | None,
        now: Callable[[], datetime] | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._cache = cache
        self._model = model
        self._now = now or (lambda: datetime.now(UTC))
        self._client = client
        self._has_key = bool(api_key) or client is not None
        if client is None and api_key:
            self._client = anthropic.Anthropic(api_key=api_key)

    def __repr__(self) -> str:
        return f"ClaudeStructurer(model={self._model!r})"

    def structure(self, prompt: str, schema: type[T], *, schema_version: str) -> T:
        name = schema.__name__
        key = cache_key(
            model=self._model, schema_name=name, schema_version=schema_version, prompt=prompt
        )
        cached = self._cache.get(name, key)
        if cached is not None:
            return schema.model_validate(cached.output)
        if not self._has_key or self._client is None:
            msg = "ANTHROPIC_API_KEY is not set and no cached result exists (ADR 0003 fail-closed)"
            raise StructurerUnavailableError(msg)

        response = self._client.messages.parse(
            model=self._model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            msg = f"model declined the request (stop_reason=refusal) for schema {name}"
            raise StructurerUnavailableError(msg)
        parsed = response.parsed_output
        if parsed is None:
            msg = f"no parsed output for schema {name}"
            raise StructurerUnavailableError(msg)
        self._cache.append(
            LlmCacheRow(
                key=key,
                model=self._model,
                schema_name=name,
                schema_version=schema_version,
                created_at=self._now(),
                input_sha256=sha256_hex(prompt.encode()),
                output=json.loads(parsed.model_dump_json()),
            )
        )
        return parsed
