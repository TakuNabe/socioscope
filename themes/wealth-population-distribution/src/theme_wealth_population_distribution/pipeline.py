"""fetch -> stage -> mart for wealth-population-distribution. All I/O goes through ports."""

from collections import defaultdict

from socioscope_core.core.pipeline import Context, Stage, StageResult
from socioscope_core.ports.fetcher import FetchError
from theme_wealth_population_distribution import wid

THEME = "wealth-population-distribution"
SHARES_TABLE = "staged/wid/top_shares"
POPULATION_TABLE = "staged/wid/population"
PANEL_TABLE = "marts/wealth_population_panel"

# mart column -> (variable, percentile) in staged/wid/top_shares
PANEL_SHARES: dict[str, tuple[str, str]] = {
    "top1_income_share": ("sptinc992j", "p99p100"),
    "top10_income_share": ("sptinc992j", "p90p100"),
    "bottom50_income_share": ("sptinc992j", "p0p50"),
    "top1_wealth_share": ("shweal992j", "p99p100"),
    "top10_wealth_share": ("shweal992j", "p90p100"),
}


def _raw_name(iso2: str) -> str:
    return f"WID_fulldataset_{iso2}.zip"


def fetch(ctx: Context) -> StageResult:
    written: list[str] = []
    skipped: list[str] = []
    for iso2 in wid.COUNTRIES:
        url = wid.country_zip_url(iso2)
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{iso2}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=wid.SOURCE,
            name=_raw_name(iso2),
            url=url,
            license=wid.LICENSE,
            payload=payload,
        )
        written.append(rec.relative_path)
    return StageResult(stage=Stage.FETCH, written=tuple(written), skipped=tuple(skipped))


def stage(ctx: Context) -> StageResult:
    shares: list[dict[str, object]] = []
    population: list[dict[str, object]] = []
    skipped: list[str] = []
    for iso2 in wid.COUNTRIES:
        payload = ctx.raw.get(theme=THEME, source=wid.SOURCE, name=_raw_name(iso2))
        if payload is None:
            skipped.append(f"{iso2}: raw missing (run fetch)")
            continue
        s, p = wid.rows_from_csv(wid.extract_data_csv(payload, iso2))
        shares.extend(s)
        population.extend(p)
    if not shares and not population:
        return StageResult(stage=Stage.STAGE, skipped=tuple(skipped))
    ctx.tables.write_table(POPULATION_TABLE, population)
    ctx.tables.write_table(SHARES_TABLE, shares)
    return StageResult(
        stage=Stage.STAGE, written=(POPULATION_TABLE, SHARES_TABLE), skipped=tuple(skipped)
    )


def build_panel(
    shares: list[dict[str, object]], population: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Wide iso3×year panel. Pure; missing stays None; only the pre-registered series are kept."""
    by_series = {v: k for k, v in PANEL_SHARES.items()}
    cells: dict[tuple[str, int], dict[str, object]] = defaultdict(dict)
    for r in shares:
        col = by_series.get((str(r["variable"]), str(r["percentile"])))
        if col is not None:
            cells[(str(r["iso3"]), int(str(r["year"])))][col] = r["value"]
    for r in population:
        cells[(str(r["iso3"]), int(str(r["year"])))]["population"] = r["value"]
    out: list[dict[str, object]] = []
    for iso3, year in sorted(cells):
        cell = cells[(iso3, year)]
        out.append(
            {
                "iso3": iso3,
                "year": year,
                **{col: cell.get(col) for col in PANEL_SHARES},
                "population": cell.get("population"),
                "source": wid.SOURCE,
            }
        )
    return out


def mart(ctx: Context) -> StageResult:
    try:
        shares = ctx.tables.read_table(SHARES_TABLE)
        population = ctx.tables.read_table(POPULATION_TABLE)
    except FileNotFoundError as e:
        return StageResult(stage=Stage.MART, skipped=(f"{e}: staged table missing (run stage)",))
    ctx.tables.write_table(PANEL_TABLE, build_panel(shares, population))
    return StageResult(stage=Stage.MART, written=(PANEL_TABLE,))
