from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from socioscope_core.core.provenance import RawRecord


class FilesystemRawStore:
    """RawStore on data/raw/<theme>/<source>/<name> + append-only manifest.jsonl (ADR 0002)."""

    def __init__(self, root: Path, *, now: Callable[[], datetime] | None = None) -> None:
        self._root = root
        self._manifest = root / "manifest.jsonl"
        self._now = now or (lambda: datetime.now(UTC))

    def put(
        self, *, theme: str, source: str, name: str, url: str, license: str, payload: bytes
    ) -> RawRecord:
        record = RawRecord.create(
            theme=theme,
            source=source,
            name=name,
            url=url,
            license=license,
            payload=payload,
            fetched_at=self._now(),
        )
        path = self._root / record.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        with self._manifest.open("a", encoding="utf-8") as f:
            f.write(record.to_jsonl() + "\n")
        return record

    def get(self, *, theme: str, source: str, name: str) -> bytes | None:
        path = self._root / theme / source / name
        return path.read_bytes() if path.exists() else None

    def records(self) -> Sequence[RawRecord]:
        if not self._manifest.exists():
            return []
        lines = self._manifest.read_text(encoding="utf-8").splitlines()
        return [RawRecord.from_jsonl(line) for line in lines if line.strip()]
