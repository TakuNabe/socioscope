from socioscope_core.core.pipeline import Context, Stage
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore
from theme_wealth_population_distribution.wiring import PIPELINE


def test_all_stages_skip_explicitly_and_write_nothing() -> None:
    ctx = Context(fetcher=FakeFetcher(), raw=InMemoryRawStore(), tables=InMemoryTableStore())
    for stage in Stage:
        result = PIPELINE.run(stage, ctx)
        assert result.written == () and result.skipped
    assert ctx.tables.list_tables() == [] and ctx.raw.records() == []
