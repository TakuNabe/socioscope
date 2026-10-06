"""socioscope CLI — the only place where adapters are wired to ports (ADR 0001)."""

import base64
import mimetypes
import shutil
import subprocess
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
from socioscope_core.core.note_export import convert_report
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


NOTE_EXPORT_DIR = Path("exports/note")


@app.command("note-draft")
def note_draft(
    report: Path,
    out: Path = typer.Option(  # noqa: B008
        NOTE_EXPORT_DIR, "--out", help="Output directory (gitignored; regenerable from the report)."
    ),
    copy: bool = typer.Option(
        False, "--copy", help="Also put the HTML on the macOS clipboard (rich-text paste)."
    ),
    embed_images: bool = typer.Option(
        False, "--embed-images", help="Inline figures into the HTML as base64 data URIs."
    ),
    figures: list[Path] | None = typer.Option(  # noqa: B008
        None, "--figures", help="Extra directories to search (recursively) for figures. Repeatable."
    ),
) -> None:
    """Convert a report into note.com-ready text (<stem>.note.md / .note.html) and list images.

    note.com has no public write API, so the draft is created by pasting: open a new note,
    paste the HTML (rich text) or the Markdown, then upload the listed figures at each
    「【画像を挿入: …】」 placeholder.
    """
    if not report.exists():
        typer.echo(f"{report} not found", err=True)
        raise typer.Exit(2)
    text = report.read_text(encoding="utf-8")
    roots = [report.parent, *(figures or [])]
    embedded: dict[str, str] = {}
    missing: list[str] = []
    if embed_images:
        for ref in convert_report(text).images:
            name = ref.rsplit("/", 1)[-1]
            found = find_figure(name, roots)
            if found is None:
                missing.append(name)
            else:
                embedded[name] = data_uri(found)
    draft = convert_report(text, embedded)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"{report.stem}.md"
    html_path = out / f"{report.stem}.html"
    md_path.write_text(draft.markdown, encoding="utf-8")
    html_path.write_text(draft.html, encoding="utf-8")
    typer.echo(f"title    {draft.title}")
    typer.echo(f"written  {md_path}")
    typer.echo(f"written  {html_path}")
    if draft.tables:
        typer.echo(
            f"note     {draft.tables} table(s) converted to bullet lists (note has no tables)"
        )
    if embed_images:
        typer.echo(f"note     embedded {len(embedded)} image(s) into the HTML")
        for name in missing:
            typer.echo(f"missing  {name}")
    else:
        for img in draft.images:
            typer.echo(f"image    {(report.parent / img).resolve()}")
    if copy:
        copy_html_to_clipboard(draft.html)
        typer.echo("copied   HTML to clipboard")


def find_figure(name: str, roots: list[Path]) -> Path | None:
    """Find a figure by basename under the given roots (direct hit first, then recursive)."""
    for root in roots:
        direct = root / name
        if direct.is_file():
            return direct
    for root in roots:
        if root.is_dir():
            hits = sorted(root.rglob(name))
            if hits:
                return hits[0]
    return None


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def copy_html_to_clipboard(html: str) -> None:
    """Place HTML on the macOS clipboard via osascript so the note editor pastes it as rich text."""
    osascript = shutil.which("osascript")
    if osascript is None:
        typer.echo("--copy needs macOS osascript; skipped", err=True)
        return
    script = f"set the clipboard to «data HTML{html.encode('utf-8').hex()}»"
    subprocess.run([osascript, "-e", script], check=True)  # noqa: S603
