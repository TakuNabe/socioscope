"""fetch -> stage -> mart for wealth-population-distribution. All I/O goes through ports."""

from collections import defaultdict

from socioscope_core.core.pipeline import Context, Stage, StageResult
from socioscope_core.ports.fetcher import FetchError
from theme_wealth_population_distribution import oecd, wid

THEME = "wealth-population-distribution"
SHARES_TABLE = "staged/wid/top_shares"
POPULATION_TABLE = "staged/wid/population"
PANEL_TABLE = "marts/wealth_population_panel"
INSTITUTIONS_TABLE = "marts/wealth_institutions_panel"
INSTITUTIONS_FROM = 1980


def oecd_table(indicator: str) -> str:
    return f"staged/oecd/{indicator}"


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


def _fetch_oecd(ctx: Context) -> tuple[list[str], list[str]]:
    """One CSV per OECD indicator (sdmx.oecd.org, no key). Honours the `--only` source filter."""
    written: list[str] = []
    skipped: list[str] = []
    if not ctx.wants(oecd.SOURCE):
        return written, skipped
    for name in sorted(oecd.INDICATORS):
        ind = oecd.INDICATORS[name]
        url = oecd.data_url(ind)
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"oecd/{name}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=oecd.SOURCE,
            name=oecd.raw_name(ind),
            url=url,
            license=oecd.LICENSE,
            payload=payload,
        )
        written.append(rec.relative_path)
    return written, skipped


def _stage_oecd(ctx: Context) -> tuple[list[str], list[str]]:
    written: list[str] = []
    skipped: list[str] = []
    if not ctx.wants(oecd.SOURCE):
        return written, skipped
    for name in sorted(oecd.INDICATORS):
        ind = oecd.INDICATORS[name]
        payload = ctx.raw.get(theme=THEME, source=oecd.SOURCE, name=oecd.raw_name(ind))
        if payload is None:
            skipped.append(f"oecd/{name}: raw missing (run fetch --only oecd)")
            continue
        ctx.tables.write_table(oecd_table(name), oecd.rows_from_csv(payload, ind))
        written.append(oecd_table(name))
    return written, skipped


def fetch(ctx: Context) -> StageResult:
    written, skipped = _fetch_oecd(ctx)
    for iso2 in wid.COUNTRIES if ctx.wants(wid.SOURCE) else ():
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
    written, skipped = _stage_oecd(ctx)
    for iso2 in wid.COUNTRIES if ctx.wants(wid.SOURCE) else ():
        payload = ctx.raw.get(theme=THEME, source=wid.SOURCE, name=_raw_name(iso2))
        if payload is None:
            skipped.append(f"{iso2}: raw missing (run fetch)")
            continue
        s, p = wid.rows_from_csv(wid.extract_data_csv(payload, iso2))
        shares.extend(s)
        population.extend(p)
    if not shares and not population:
        return StageResult(stage=Stage.STAGE, written=tuple(written), skipped=tuple(skipped))
    ctx.tables.write_table(POPULATION_TABLE, population)
    ctx.tables.write_table(SHARES_TABLE, shares)
    return StageResult(
        stage=Stage.STAGE,
        written=(*written, POPULATION_TABLE, SHARES_TABLE),
        skipped=tuple(skipped),
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


INSTITUTION_SHARES = (
    "top1_income_share",
    "top10_income_share",
    "top1_wealth_share",
    "top10_wealth_share",
)
QUALITY_COLUMNS: dict[str, tuple[str, str]] = {  # mart column -> (variable, percentile)
    "top1_income_quality": ("sptinc992j", "p99p100"),
    "top1_wealth_quality": ("shweal992j", "p99p100"),
}


def build_institutions_panel(
    panel: list[dict[str, object]],
    shares: list[dict[str, object]],
    staged_oecd: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """iso3×year for the 38 OECD members from 1980: WID top shares (+ WID data_quality of the
    top-1% series) joined with the OECD institutional indicators. Pure; missing stays None;
    years are the union of both sources so a country-year with only one side is kept."""
    members = set(oecd.OECD_MEMBERS)
    cells: dict[tuple[str, int], dict[str, object]] = defaultdict(dict)

    def key(r: dict[str, object]) -> tuple[str, int] | None:
        iso3, year = str(r["iso3"]), int(str(r["year"]))
        return (iso3, year) if iso3 in members and year >= INSTITUTIONS_FROM else None

    for r in panel:
        if (k := key(r)) is not None:
            cells[k].update({c: r.get(c) for c in INSTITUTION_SHARES})
    by_series = {v: k for k, v in QUALITY_COLUMNS.items()}
    for r in shares:
        col = by_series.get((str(r["variable"]), str(r["percentile"])))
        if col is not None and (k := key(r)) is not None:
            cells[k][col] = r.get("data_quality")
    for indicator, rows in staged_oecd.items():
        for r in rows:
            if (k := key(r)) is not None:
                cells[k][indicator] = r["value"]
    columns = (*INSTITUTION_SHARES, *QUALITY_COLUMNS, *oecd.INDICATORS)
    return [
        {
            "iso3": iso3,
            "year": year,
            **{c: cells[(iso3, year)].get(c) for c in columns},
            "source": f"{wid.SOURCE}+{oecd.SOURCE}",
        }
        for iso3, year in sorted(cells)
    ]


def _mart_institutions(
    ctx: Context, panel: list[dict[str, object]], shares: list[dict[str, object]]
) -> tuple[list[str], list[str]]:
    staged: dict[str, list[dict[str, object]]] = {}
    for name in oecd.INDICATORS:
        try:
            staged[name] = ctx.tables.read_table(oecd_table(name))
        except FileNotFoundError:
            return [], [f"{oecd_table(name)}: staged table missing (run stage --only oecd)"]
    ctx.tables.write_table(INSTITUTIONS_TABLE, build_institutions_panel(panel, shares, staged))
    return [INSTITUTIONS_TABLE], []


def mart(ctx: Context) -> StageResult:
    try:
        shares = ctx.tables.read_table(SHARES_TABLE)
        population = ctx.tables.read_table(POPULATION_TABLE)
    except FileNotFoundError as e:
        return StageResult(stage=Stage.MART, skipped=(f"{e}: staged table missing (run stage)",))
    panel = build_panel(shares, population)
    ctx.tables.write_table(PANEL_TABLE, panel)
    written, skipped = _mart_institutions(ctx, panel, shares)
    return StageResult(stage=Stage.MART, written=(PANEL_TABLE, *written), skipped=tuple(skipped))
