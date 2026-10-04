from datetime import UTC, datetime
from pathlib import Path

from socioscope_core.adapters.filesystem_raw import FilesystemRawStore


def test_put_writes_file_and_appends_manifest(tmp_path: Path) -> None:
    store = FilesystemRawStore(tmp_path, now=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    store.put(theme="t", source="s", name="a.json", url="https://u/a", license="CC0", payload=b"1")
    store.put(theme="t", source="s", name="b.json", url="https://u/b", license="CC0", payload=b"22")

    assert (tmp_path / "t/s/a.json").read_bytes() == b"1"
    assert store.get(theme="t", source="s", name="b.json") == b"22"
    assert store.get(theme="t", source="s", name="zzz") is None
    recs = store.records()
    assert [r.name for r in recs] == ["a.json", "b.json"]
    assert recs[1].size_bytes == 2
    assert len((tmp_path / "manifest.jsonl").read_text().splitlines()) == 2


def test_empty_store_has_no_records(tmp_path: Path) -> None:
    assert FilesystemRawStore(tmp_path).records() == []
