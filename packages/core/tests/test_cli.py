import pytest
from typer.testing import CliRunner

from socioscope_core import cli
from socioscope_core.core.pipeline import Context, Pipeline, Stage, StageResult
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore


def test_run_passes_only_filter_into_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[frozenset[str] | None] = []
    p = Pipeline(slug="demo", title="Demo")

    @p.register(Stage.FETCH)
    def fetch(ctx: Context) -> StageResult:
        seen.append(ctx.sources)
        return StageResult(stage=Stage.FETCH, written=("x",))

    monkeypatch.setattr(cli, "discover_themes", lambda: {"demo": p})
    monkeypatch.setattr(
        cli,
        "build_context",
        lambda settings, sources=None: Context(
            fetcher=FakeFetcher(),
            raw=InMemoryRawStore(),
            tables=InMemoryTableStore(),
            sources=sources,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli.app, ["run", "demo", "fetch", "--only", "oecd", "--only", "wb"])
    assert r.exit_code == 0 and "written  x" in r.output
    r = runner.invoke(cli.app, ["run", "demo", "fetch"])
    assert r.exit_code == 0
    assert seen == [frozenset({"oecd", "wb"}), None]
