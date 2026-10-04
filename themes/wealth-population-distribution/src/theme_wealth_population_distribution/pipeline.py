"""Placeholder stages: every stage reports an explicit skip until sources are adopted (ADR 0004)."""

from socioscope_core.core.pipeline import Context, Stage, StageResult

THEME = "wealth-population-distribution"
_TODO = (
    "no data source adopted yet — start with `/new-source WID.world wealth-population-distribution`"
)


def fetch(ctx: Context) -> StageResult:
    return StageResult(stage=Stage.FETCH, skipped=(_TODO,))


def stage(ctx: Context) -> StageResult:
    return StageResult(stage=Stage.STAGE, skipped=(_TODO,))


def mart(ctx: Context) -> StageResult:
    return StageResult(stage=Stage.MART, skipped=(_TODO,))
