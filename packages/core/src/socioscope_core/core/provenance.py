"""Provenance records for raw payloads (ADR 0002). No external dependencies."""

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RawRecord(BaseModel):
    """One line of data/raw/manifest.jsonl."""

    theme: str
    source: str
    name: str = Field(description="Relative file name under data/raw/<theme>/<source>/")
    url: str
    sha256: str
    size_bytes: int
    fetched_at: datetime
    license: str
    committed: bool = False

    @classmethod
    def create(
        cls,
        *,
        theme: str,
        source: str,
        name: str,
        url: str,
        license: str,
        payload: bytes,
        fetched_at: datetime | None = None,
    ) -> "RawRecord":
        return cls(
            theme=theme,
            source=source,
            name=name,
            url=url,
            sha256=sha256_hex(payload),
            size_bytes=len(payload),
            fetched_at=fetched_at or datetime.now(UTC),
            license=license,
        )

    def to_jsonl(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_jsonl(cls, line: str) -> "RawRecord":
        return cls.model_validate_json(line)

    @property
    def relative_path(self) -> str:
        return f"{self.theme}/{self.source}/{self.name}"
