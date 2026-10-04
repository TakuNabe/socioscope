"""socioscope CLI — the only place where adapters are wired to ports (ADR 0001)."""

from importlib.metadata import entry_points
from pathlib import Path

import typer

from socioscope_core.adapters.claude_structurer import ClaudeStructurer, JsonlLlmCache
from socioscope_core.adapters.duckdb_catalog import build_catalog
from socioscope_core.adapters.duckdb_catalog import query as duck_query
from socioscope_core.adapters.filesystem_raw import FilesystemRawStore
from socioscope_core.adapters.http_fetcher import HttpxFetcher
from socioscope_core.adapters.parquet_store import ParquetTableStore
from socioscope_core.config import Settings
from socioscope_core.core.pipeline import Context, Pipeline, Stage

app = typer.Typer(
    no_args_is_help=True, help="Run socioscope theme pipelines and query the catalog."
)
db_app = typer.Typer(no_args_is_help=True, help="DuckDB catalog over data/**/*.parquet")
app.add_typer(db_app, name="db")


def discover_themes() -> dict[str, Pipeline]:
    found: dict[str, Pipeline] = {}
    for ep in entry_points(group="socioscope.themes"):
        obj = ep.load()
        if isinstance(obj, Pipeline):
            found[ep.name] = obj
    return found


def build_context(settings: Settings, sources: frozenset[str] | None = None) -> Context:
    data = settings.data_dir
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return Context(
        fetcher=HttpxFetcher(user_agent=settings.user_agent),
        raw=FilesystemRawStore(data / "raw"),
        tables=ParquetTableStore(data),
        structurer=ClaudeStructurer(
            cache=JsonlLlmCache(data / "llm_cache"), model=settings.llm_model, api_key=key
        ),
        sources=sources,
    )


@app.command()
def themes() -> None:
    """List registered themes."""
    for slug, p in sorted(discover_themes().items()):
        stages = ",".join(s.value for s in Stage if s in p.stages) or "-"
        typer.echo(f"{slug:36} {p.title}  [{stages}]")


@app.command()
def run(
    theme: str,
    stage: Stage,
    only: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--only",
        help="Restrict the stage to these raw-store sources (e.g. --only oecd). Repeatable.",
    ),
) -> None:
    """Run one stage (fetch | stage | mart) of a theme."""
    pipelines = discover_themes()
    if theme not in pipelines:
        typer.echo(f"unknown theme '{theme}'. known: {', '.join(sorted(pipelines))}", err=True)
        raise typer.Exit(2)
    sources = frozenset(only) if only else None
    result = pipelines[theme].run(stage, build_context(Settings(), sources))
    for w in result.written:
        typer.echo(f"written  {w}")
    for s in result.skipped:
        typer.echo(f"skipped  {s}")
    for n in result.notes:
        typer.echo(f"note     {n}")


@db_app.command("build")
def db_build(path: Path = Path("socioscope.duckdb")) -> None:
    """(Re)create the DuckDB catalog with views over staged/ and marts/ parquet files."""
    settings = Settings()
    views = build_catalog(path, settings.data_dir)
    typer.echo(f"{path}: {len(views)} views")
    for v in views:
        typer.echo(f"  {v}")


@db_app.command("query")
def db_query(sql: str, path: Path = Path("socioscope.duckdb")) -> None:
    """Run a read-only SQL statement against the catalog."""
    if not path.exists():
        typer.echo(f"{path} not found; run `socioscope db build` first", err=True)
        raise typer.Exit(2)
    for row in duck_query(path, sql):
        typer.echo("\t".join("" if v is None else str(v) for v in row))
