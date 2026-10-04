from collections.abc import Sequence
from pathlib import Path

import polars as pl

from socioscope_core.ports.store import Row


class ParquetTableStore:
    """TableStore where '<layer>/<domain>/<name>' -> data/<layer>/<domain>/<name>.parquet."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, name: str) -> Path:
        if ".." in name.split("/") or name.startswith("/"):
            msg = f"invalid table name: {name}"
            raise ValueError(msg)
        return self._root / f"{name}.parquet"

    def write_table(self, name: str, rows: Sequence[Row]) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # infer over every row: a column that is None in the first rows (e.g. long tables whose
        # early metrics have no `sex`) must still take its type from later rows.
        df = (
            pl.DataFrame([dict(r) for r in rows], infer_schema_length=None)
            if rows
            else pl.DataFrame()
        )
        df.write_parquet(path, compression="zstd")

    def read_table(self, name: str) -> list[dict[str, object]]:
        return pl.read_parquet(self._path(name)).to_dicts()

    def list_tables(self) -> list[str]:
        return sorted(
            str(p.relative_to(self._root).with_suffix("")) for p in self._root.rglob("*.parquet")
        )
