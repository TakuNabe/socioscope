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


def test_column_null_in_first_rows_takes_type_from_later_rows(tmp_path: Path) -> None:
    # Long tables often start with metrics that leave a column (e.g. sex) None; the type must
    # be inferred over all rows, not polars' default first 100.
    store = ParquetTableStore(tmp_path)
    rows = [{"metric": "a", "sex": None, "value": 1.0} for _ in range(150)]
    rows.append({"metric": "b", "sex": "female", "value": 0.5})
    store.write_table("marts/long", rows)
    assert store.read_table("marts/long")[-1] == {"metric": "b", "sex": "female", "value": 0.5}


def test_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid table name"):
        ParquetTableStore(tmp_path).write_table("../evil", [])
