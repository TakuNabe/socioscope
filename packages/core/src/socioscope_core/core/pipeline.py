"""Theme pipeline definition: fetch -> stage -> mart (design/overview.md). No external deps."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from socioscope_core.ports.fetcher import SourceFetcher
from socioscope_core.ports.store import RawStore, TableStore
from socioscope_core.ports.structurer import Structurer


class Stage(StrEnum):
    FETCH = "fetch"
    STAGE = "stage"
    MART = "mart"


@dataclass(frozen=True)
class Context:
    """Bundle of ports handed to every stage function. Wiring happens in cli.py / wiring.py only."""

    fetcher: SourceFetcher
    raw: RawStore
    tables: TableStore
    structurer: Structurer | None = None


StageFn = Callable[[Context], "StageResult"]


@dataclass(frozen=True)
class StageResult:
    """What a stage did, for the CLI report and for state-based tests."""

    stage: Stage
    written: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass
class Pipeline:
    slug: str
    title: str
    stages: dict[Stage, StageFn] = field(default_factory=dict)

    def register(self, stage: Stage) -> Callable[[StageFn], StageFn]:
        def deco(fn: StageFn) -> StageFn:
            if stage in self.stages:
                msg = f"stage {stage} already registered for {self.slug}"
                raise ValueError(msg)
            self.stages[stage] = fn
            return fn

        return deco

    def run(self, stage: Stage, ctx: Context) -> StageResult:
        fn = self.stages.get(stage)
        if fn is None:
            return StageResult(stage=stage, notes=(f"{self.slug}: no '{stage}' stage registered",))
        return fn(ctx)
