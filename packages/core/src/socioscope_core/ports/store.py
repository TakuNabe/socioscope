from collections.abc import Mapping, Sequence
from typing import Protocol

from socioscope_core.core.provenance import RawRecord

Row = Mapping[str, object]


class RawStore(Protocol):
    """Immutable raw payloads + provenance manifest (ADR 0002)."""

    def put(
        self, *, theme: str, source: str, name: str, url: str, license: str, payload: bytes
    ) -> RawRecord:
        """Persist payload and append a manifest row. Returns the provenance record."""
        ...

    def get(self, *, theme: str, source: str, name: str) -> bytes | None:
        """Return a previously stored payload, or None."""
        ...

    def records(self) -> Sequence[RawRecord]:
        """All manifest rows, in append order."""
        ...


class TableStore(Protocol):
    """Columnar tables keyed by '<layer>/<domain>/<name>' (e.g. 'staged/worldbank/tfr')."""

    def write_table(self, name: str, rows: Sequence[Row]) -> None: ...

    def read_table(self, name: str) -> list[dict[str, object]]: ...

    def list_tables(self) -> list[str]: ...
