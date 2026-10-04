from pathlib import Path

import pytest

from socioscope_core.adapters.parquet_store import ParquetTableStore


def test_write_read_list_round_trip(tmp_path: Path) -> None:
    store = ParquetTableStore(tmp_path)
    rows = [{"iso3": "JPN", "year": 2000, "v": 1.5}, {"iso3": "USA", "year": 2000, "v": None}]
    store.write_table("staged/wb/tfr", rows)
    assert (tmp_path / "staged/wb/tfr.parquet").exists()
    assert store.read_table("staged/wb/tfr") == rows
    assert store.list_tables() == ["staged/wb/tfr"]


def test_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid table name"):
        ParquetTableStore(tmp_path).write_table("../evil", [])
