import pytest

from socioscope_core.core.pipeline import Context, Pipeline, Stage, StageResult
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore


def make_ctx() -> Context:
    return Context(fetcher=FakeFetcher(), raw=InMemoryRawStore(), tables=InMemoryTableStore())


def test_registered_stage_runs_and_can_write_tables() -> None:
    p = Pipeline(slug="demo", title="Demo")

    @p.register(Stage.STAGE)
    def stage(ctx: Context) -> StageResult:
        ctx.tables.write_table("staged/demo/t", [{"iso3": "JPN", "year": 2000, "v": 1.0}])
        return StageResult(stage=Stage.STAGE, written=("staged/demo/t",))

    ctx = make_ctx()
    result = p.run(Stage.STAGE, ctx)
    assert result.written == ("staged/demo/t",)
    assert ctx.tables.read_table("staged/demo/t") == [{"iso3": "JPN", "year": 2000, "v": 1.0}]


def test_missing_stage_is_reported_not_raised() -> None:
    p = Pipeline(slug="demo", title="Demo")
    result = p.run(Stage.MART, make_ctx())
    assert result.written == ()
    assert "no 'mart' stage" in result.notes[0]


def test_double_registration_is_an_error() -> None:
    p = Pipeline(slug="demo", title="Demo")

    @p.register(Stage.FETCH)
    def a(ctx: Context) -> StageResult:
        return StageResult(stage=Stage.FETCH)

    with pytest.raises(ValueError, match="already registered"):

        @p.register(Stage.FETCH)
        def b(ctx: Context) -> StageResult:
            return StageResult(stage=Stage.FETCH)
