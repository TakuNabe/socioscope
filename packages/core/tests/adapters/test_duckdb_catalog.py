from pathlib import Path

from socioscope_core.adapters.duckdb_catalog import build_catalog, query
from socioscope_core.adapters.parquet_store import ParquetTableStore


def test_catalog_exposes_one_view_per_parquet(tmp_path: Path) -> None:
    data = tmp_path / "data"
    store = ParquetTableStore(data)
    store.write_table("staged/worldbank/tfr", [{"iso3": "JPN", "year": 2000, "value": 1.36}])
    store.write_table("marts/growth_fertility_panel", [{"iso3": "JPN", "year": 2000}])

    db = tmp_path / "x.duckdb"
    views = build_catalog(db, data)
    assert views == ["staged.worldbank_tfr", "marts.growth_fertility_panel"]
    assert query(db, "select value from staged.worldbank_tfr where iso3 = ?", ["JPN"]) == [(1.36,)]
    # rebuild is idempotent
    assert build_catalog(db, data) == views
