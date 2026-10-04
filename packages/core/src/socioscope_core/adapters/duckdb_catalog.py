"""Build a throw-away DuckDB catalog over data/**/*.parquet (ADR 0002)."""

from pathlib import Path

import duckdb

LAYERS = ("staged", "marts")


def _view_name(rel: Path) -> str:
    # staged/worldbank/tfr.parquet -> worldbank_tfr
    # marts/growth_fertility_panel.parquet -> growth_fertility_panel
    return "_".join(rel.with_suffix("").parts[1:]).replace("-", "_")


def build_catalog(db_path: Path, data_dir: Path) -> list[str]:
    """(Re)create db_path with one view per parquet file: <layer>.<domain>_<name>.

    Returns the created view names.
    """
    if db_path.exists():
        db_path.unlink()
    created: list[str] = []
    with duckdb.connect(str(db_path)) as con:
        for layer in LAYERS:
            con.execute(f'CREATE SCHEMA IF NOT EXISTS "{layer}"')
            for parquet in sorted((data_dir / layer).rglob("*.parquet")):
                rel = parquet.relative_to(data_dir)
                view = _view_name(rel)
                # DDL cannot take bound parameters in DuckDB. Identifiers come from our own file
                # layout and the path literal is escaped, so no untrusted input reaches the SQL.
                path_literal = str(parquet.resolve()).replace("'", "''")
                con.execute(
                    f'CREATE OR REPLACE VIEW "{layer}"."{view}" AS '  # noqa: S608
                    f"SELECT * FROM read_parquet('{path_literal}')"
                )
                created.append(f"{layer}.{view}")
    return created


def query(db_path: Path, sql: str, params: list[object] | None = None) -> list[tuple[object, ...]]:
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, params or []).fetchall()
