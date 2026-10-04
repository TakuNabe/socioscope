from datetime import UTC, datetime

from socioscope_core.core.provenance import RawRecord, sha256_hex


def test_create_records_hash_size_and_path() -> None:
    rec = RawRecord.create(
        theme="t",
        source="wb",
        name="tfr.json",
        url="https://x/y",
        license="CC BY 4.0",
        payload=b"abc",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert rec.sha256 == sha256_hex(b"abc")
    assert rec.size_bytes == 3
    assert rec.relative_path == "t/wb/tfr.json"
    assert rec.committed is False


def test_jsonl_round_trip() -> None:
    rec = RawRecord.create(
        theme="t",
        source="s",
        name="n",
        url="u",
        license="l",
        payload=b"",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert RawRecord.from_jsonl(rec.to_jsonl()) == rec
