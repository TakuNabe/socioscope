"""fetch -> stage -> mart for wealth-population-distribution. All I/O goes through ports."""

from collections import defaultdict

from socioscope_core.core.pipeline import Context, Stage, StageResult
from socioscope_core.ports.fetcher import FetchError
from theme_wealth_population_distribution import distribution as dist
from theme_wealth_population_distribution import oecd, wid

THEME = "wealth-population-distribution"
SHARES_TABLE = "staged/wid/top_shares"
POPULATION_TABLE = "staged/wid/population"
METADATA_TABLE = "staged/wid/metadata"
DATA_POINTS_TABLE = "staged/wid/data_points"
DISTRIBUTION_TABLE = "staged/wid/distribution"
THRESHOLDS_TABLE = "staged/wid/thresholds"
PANEL_TABLE = "marts/wealth_population_panel"
INSTITUTIONS_TABLE = "marts/wealth_institutions_panel"
INSTITUTIONS_FROM = 1980


def oecd_table(indicator: str) -> str:
    return f"staged/oecd/{indicator}"


# mart observed-flag column -> staged variable whose per-year construction it reports
PANEL_OBSERVED: dict[str, str] = {
    "top1_income_observed": "sptinc992j",
    "top1_wealth_observed": "shweal992j",
}

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
    fetched = rejected = 0
    for name in sorted(oecd.INDICATORS):
        ind = oecd.INDICATORS[name]
        url = oecd.data_url(ind)
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"oecd/{name}: {e}")
            continue
        fetched += 1
        if not oecd.is_csv_payload(payload):
            rejected += 1
            skipped.append(f"oecd/{name}: non-CSV payload (site down?)")
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
    _raise_if_all_rejected(oecd.SOURCE, fetched, rejected)
    return written, skipped


def _raise_if_all_rejected(source: str, fetched: int, rejected: int) -> None:
    """Every fetched body was rejected -> the site is most likely down; exit non-zero."""
    if fetched and rejected == fetched:
        msg = (
            f"{source}: all {fetched} fetched payloads were rejected (site down?); nothing written"
        )
        raise RuntimeError(msg)


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
    fetched = rejected = 0
    for iso2 in wid.COUNTRIES if ctx.wants(wid.SOURCE) else ():
        url = wid.country_zip_url(iso2)
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{iso2}: {e}")
            continue
        fetched += 1
        if not wid.is_zip_payload(payload):
            rejected += 1
            skipped.append(f"{iso2}: non-zip payload (site down?)")
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
    _raise_if_all_rejected(wid.SOURCE, fetched, rejected)
    return StageResult(stage=Stage.FETCH, written=tuple(written), skipped=tuple(skipped))


def stage(ctx: Context) -> StageResult:
    shares: list[dict[str, object]] = []
    population: list[dict[str, object]] = []
    metadata: list[dict[str, object]] = []
    distribution: list[dict[str, object]] = []
    thresholds: list[dict[str, object]] = []
    written, skipped = _stage_oecd(ctx)
    for iso2 in wid.COUNTRIES if ctx.wants(wid.SOURCE) else ():
        payload = ctx.raw.get(theme=THEME, source=wid.SOURCE, name=_raw_name(iso2))
        if payload is None:
            skipped.append(f"{iso2}: raw missing (run fetch)")
            continue
        data_csv = wid.extract_data_csv(payload, iso2)
        s, p = wid.rows_from_csv(data_csv)
        shares.extend(s)
        population.extend(p)
        metadata.extend(wid.metadata_rows_from_csv(wid.extract_metadata_csv(payload, iso2)))
        d, t = wid.distribution_rows_from_csv(data_csv)
        distribution.extend(d)
        thresholds.extend(t)
    if not shares and not population:
        return StageResult(stage=Stage.STAGE, written=tuple(written), skipped=tuple(skipped))
    ctx.tables.write_table(POPULATION_TABLE, population)
    ctx.tables.write_table(SHARES_TABLE, shares)
    ctx.tables.write_table(METADATA_TABLE, metadata)
    ctx.tables.write_table(DATA_POINTS_TABLE, wid.data_point_rows(shares, metadata))
    ctx.tables.write_table(DISTRIBUTION_TABLE, distribution)
    ctx.tables.write_table(THRESHOLDS_TABLE, thresholds)
    return StageResult(
        stage=Stage.STAGE,
        written=(
            *written,
            POPULATION_TABLE,
            SHARES_TABLE,
            METADATA_TABLE,
            DATA_POINTS_TABLE,
            DISTRIBUTION_TABLE,
            THRESHOLDS_TABLE,
        ),
        skipped=tuple(skipped),
    )


# ---- H4 columns (appended after the existing ones; all None when the inputs are missing)
TAIL_COLUMNS: dict[
    str, tuple[str, str]
] = {  # mart column -> (variable, percentile) in distribution
    "top01_income_share": ("sptinc992j", "p99.9p100"),
    "top001_income_share": ("sptinc992j", "p99.99p100"),
    "top01_wealth_share": ("shweal992j", "p99.9p100"),
    "top001_wealth_share": ("shweal992j", "p99.99p100"),
}
GINI_COLUMNS: dict[str, str] = {"gini_income": "sptinc992j", "gini_wealth": "shweal992j"}
MIDDLE40_COLUMNS: dict[str, str] = {  # 1 - p0p50 - p90p100 of the same variable (top_shares)
    "middle40_income_share": "sptinc992j",
    "middle40_wealth_share": "shweal992j",
}
RATIO_COLUMNS: dict[str, tuple[str, int, int]] = {  # mart column -> (threshold variable, num, den)
    "p90_p50_income": ("tptinc992j", 90, 50),
    "p50_p10_income": ("tptinc992j", 50, 10),
    "p90_p50_wealth": ("thweal992j", 90, 50),
    "p50_p10_wealth": ("thweal992j", 50, 10),
}
H4_COLUMNS: tuple[str, ...] = (*TAIL_COLUMNS, *GINI_COLUMNS, *MIDDLE40_COLUMNS, *RATIO_COLUMNS)
N_G_PERCENTILES = len(wid.G_PERCENTILES)


def _gini_or_none(brackets: list[dist.Bracket]) -> float | None:
    """Gini only when the full 127-bracket partition is present and its shares are consistent.
    Anything else is None (not imputed, not raised: a single odd country-year must not stop
    the mart)."""
    if len(brackets) != N_G_PERCENTILES:
        return None
    try:
        return dist.gini_from_brackets(brackets)
    except ValueError:
        return None


def build_panel(
    shares: list[dict[str, object]],
    population: list[dict[str, object]],
    data_points: list[dict[str, object]] | None = None,
    distribution: list[dict[str, object]] | None = None,
    thresholds: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Wide iso3×year panel. Pure; missing stays None; only the pre-registered series are kept.

    `data_points` (staged/wid/data_points) adds the *_observed flags; unknown/missing -> None.
    `distribution` (staged/wid/distribution) adds the top-0.1%/0.01% tails and the trapezoid
    Gini over the 127 g-percentiles; `thresholds` (staged/wid/thresholds) adds P90/P50 and
    P50/P10. The middle-40% share needs only `shares`. Existing columns keep their order and
    values; the H4 columns are appended after them (H4_COLUMNS).
    """
    by_series = {v: k for k, v in PANEL_SHARES.items()}
    by_variable = {v: k for k, v in PANEL_OBSERVED.items()}
    by_tail = {v: k for k, v in TAIL_COLUMNS.items()}
    cells: dict[tuple[str, int], dict[str, object]] = defaultdict(dict)
    raw_shares: dict[tuple[str, int, str, str], float] = {}
    for r in shares:
        key = (str(r["iso3"]), int(str(r["year"])))
        col = by_series.get((str(r["variable"]), str(r["percentile"])))
        if col is not None:
            cells[key][col] = r["value"]
        raw_shares[(*key, str(r["variable"]), str(r["percentile"]))] = float(str(r["value"]))
    for r in population:
        cells[(str(r["iso3"]), int(str(r["year"])))]["population"] = r["value"]
    for r in data_points or ():
        col = by_variable.get(str(r["variable"]))
        key = (str(r["iso3"]), int(str(r["year"])))
        if col is not None and key in cells:
            cells[key][col] = r["is_observed"]
    brackets: dict[tuple[str, int, str], list[dist.Bracket]] = defaultdict(list)
    for r in distribution or ():
        key = (str(r["iso3"]), int(str(r["year"])))
        variable, pct = str(r["variable"]), str(r["percentile"])
        col = by_tail.get((variable, pct))
        if col is not None:
            cells[key][col] = r["share"]
        if pct in wid.G_PERCENTILES:
            brackets[(*key, variable)].append(
                (float(str(r["p_lower"])), float(str(r["p_upper"])), float(str(r["share"])))
            )
    for (iso3, year, variable), bs in brackets.items():
        for col, var in GINI_COLUMNS.items():
            if var == variable:
                cells[(iso3, year)][col] = _gini_or_none(bs)
    levels: dict[tuple[str, int, str], dict[int, float | None]] = defaultdict(dict)
    for r in thresholds or ():
        tkey = (str(r["iso3"]), int(str(r["year"])), str(r["variable"]))
        levels[tkey][int(str(r["percentile"]))] = (
            None if r["value"] is None else float(str(r["value"]))
        )
    for (iso3, year, variable), th in levels.items():
        for col, (var, num, den) in RATIO_COLUMNS.items():
            if var == variable:
                cells[(iso3, year)][col] = dist.ratio(th, num, den)
    out: list[dict[str, object]] = []
    for iso3, year in sorted(cells):
        cell = cells[(iso3, year)]
        for col, variable in MIDDLE40_COLUMNS.items():
            cell[col] = dist.middle40_share(
                raw_shares.get((iso3, year, variable, "p0p50")),
                raw_shares.get((iso3, year, variable, "p90p100")),
            )
        out.append(
            {
                "iso3": iso3,
                "year": year,
                **{col: cell.get(col) for col in PANEL_SHARES},
                "population": cell.get("population"),
                "source": wid.SOURCE,
                **{col: cell.get(col) for col in PANEL_OBSERVED},
                **{col: cell.get(col) for col in H4_COLUMNS},
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
INSTITUTION_OBSERVED = ("top1_income_observed", "top1_wealth_observed")  # copied from panel


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
            cells[k].update({c: r.get(c) for c in (*INSTITUTION_SHARES, *INSTITUTION_OBSERVED)})
    by_series = {v: k for k, v in QUALITY_COLUMNS.items()}
    for r in shares:
        col = by_series.get((str(r["variable"]), str(r["percentile"])))
        if col is not None and (k := key(r)) is not None:
            cells[k][col] = r.get("data_quality")
    for indicator, rows in staged_oecd.items():
        for r in rows:
            if (k := key(r)) is not None:
                cells[k][indicator] = r["value"]
    columns = (*INSTITUTION_SHARES, *QUALITY_COLUMNS, *INSTITUTION_OBSERVED, *oecd.INDICATORS)
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
    notes: list[str] = []

    def optional(table: str, what: str) -> list[dict[str, object]] | None:
        try:
            return ctx.tables.read_table(table)
        except FileNotFoundError:
            notes.append(f"{table} missing: {what} left null (re-run stage)")
            return None

    data_points = optional(DATA_POINTS_TABLE, "*_observed flags")
    distribution = optional(DISTRIBUTION_TABLE, "top0.1/0.01 tails and Gini")
    thresholds = optional(THRESHOLDS_TABLE, "P90/P50 and P50/P10")
    panel = build_panel(shares, population, data_points, distribution, thresholds)
    ctx.tables.write_table(PANEL_TABLE, panel)
    written, skipped = _mart_institutions(ctx, panel, shares)
    return StageResult(
        stage=Stage.MART,
        written=(PANEL_TABLE, *written),
        skipped=tuple(skipped),
        notes=tuple(notes),
    )
