"""In-memory fakes for classical (state-based) tests. Importable by every theme's tests."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel

from socioscope_core.core.provenance import RawRecord
from socioscope_core.ports.fetcher import FetchError
from socioscope_core.ports.store import Row
from socioscope_core.ports.structurer import StructurerUnavailableError

T = TypeVar("T", bound=BaseModel)

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeFetcher:
    def __init__(self, responses: dict[str, bytes] | None = None) -> None:
        self.responses = dict(responses or {})
        self.requested: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.requested.append(url)
        if url not in self.responses:
            msg = f"no fake response for {url}"
            raise FetchError(msg)
        return self.responses[url]


class InMemoryRawStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._records: list[RawRecord] = []

    def put(
        self, *, theme: str, source: str, name: str, url: str, license: str, payload: bytes
    ) -> RawRecord:
        rec = RawRecord.create(
            theme=theme,
            source=source,
            name=name,
            url=url,
            license=license,
            payload=payload,
            fetched_at=FIXED_NOW,
        )
        self._blobs[rec.relative_path] = payload
        self._records.append(rec)
        return rec

    def get(self, *, theme: str, source: str, name: str) -> bytes | None:
        return self._blobs.get(f"{theme}/{source}/{name}")

    def records(self) -> Sequence[RawRecord]:
        return list(self._records)


class InMemoryTableStore:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, object]]] = {}

    def write_table(self, name: str, rows: Sequence[Row]) -> None:
        self.tables[name] = [dict(r) for r in rows]

    def read_table(self, name: str) -> list[dict[str, object]]:
        if name not in self.tables:
            raise FileNotFoundError(name)
        return [dict(r) for r in self.tables[name]]

    def list_tables(self) -> list[str]:
        return sorted(self.tables)


class FakeStructurer:
    """Returns canned outputs keyed by schema name; records prompts it saw."""

    def __init__(self, outputs: dict[str, list[dict[str, object]]] | None = None) -> None:
        self._outputs = {k: list(v) for k, v in (outputs or {}).items()}
        self.prompts: list[str] = []

    def structure(self, prompt: str, schema: type[T], *, schema_version: str) -> T:
        self.prompts.append(prompt)
        queue = self._outputs.get(schema.__name__)
        if not queue:
            msg = f"FakeStructurer has no output for {schema.__name__}"
            raise StructurerUnavailableError(msg)
        return schema.model_validate(queue.pop(0))
