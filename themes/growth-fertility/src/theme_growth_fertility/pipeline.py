"""fetch -> stage -> mart for growth-fertility. All I/O goes through ports in Context.

Two sources: World Bank WDI (cross-country panel, H1/H2) and e-Stat 国民生活基礎調査
(Japan, income class × marriage / children, H3). Each source stages independently; the
marts are ``growth_fertility_panel`` (WB) and ``jp_income_class_fertility`` (e-Stat).
Third source (H4): DHS Program API, TFR by wealth quintile -> ``dhs_tfr_by_wealth_quintile``.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence

from socioscope_core.core.pipeline import Context, Stage, StageResult
from socioscope_core.ports.fetcher import FetchError
from theme_growth_fertility import dhs, estat, kostat, oecd, surveys
from theme_growth_fertility import eurobarometer as ebm
from theme_growth_fertility import eurostat as es
from theme_growth_fertility import worldbank as wb

THEME = "growth-fertility"
COUNTRIES_TABLE = f"staged/worldbank/{wb.COUNTRIES_KEY}"

ESTAT_TABLES: dict[estat.TableKind, str] = {
    estat.TableKind.INCOME_DIST_TS: "staged/estat/kiso_income_dist_ts",
    estat.TableKind.WORKERS_MARITAL: "staged/estat/kiso_workers_marital_income",
    estat.TableKind.HH_TYPE: "staged/estat/kiso_hh_type_income",
    estat.TableKind.SHUGYO_MARITAL_AGE_INCOME: "staged/estat/shugyo_marital_age_income",
}
_ESTAT_PARSERS: dict[estat.TableKind, Callable[[bytes, estat.Table], list[dict[str, object]]]] = {
    estat.TableKind.INCOME_DIST_TS: estat.income_dist_rows,
    estat.TableKind.WORKERS_MARITAL: estat.workers_marital_rows,
    estat.TableKind.HH_TYPE: estat.hh_type_rows,
    estat.TableKind.SHUGYO_MARITAL_AGE_INCOME: estat.shugyo_marital_age_income_rows,
}
JP_MART = "marts/jp_income_class_fertility"
JP_AGE_MART = "marts/jp_income_age_marital"
# DHS: raw name -> URL (both files are needed at stage; countries give the ISO3 mapping)
DHS_RAW_DATA = "dhs_tfr_wealth.json"
DHS_RAW_COUNTRIES = "dhs_countries.json"
DHS_URLS: dict[str, str] = {DHS_RAW_DATA: dhs.data_url(), DHS_RAW_COUNTRIES: dhs.countries_url()}
DHS_TABLE = "staged/dhs/tfr_by_wealth_quintile"
DHS_MART = "marts/dhs_tfr_by_wealth_quintile"
# ---- H5: OECD / Eurostat (independent of the sources above; see _fetch_h5/_stage_h5/_mart_h5)
OECD_RAW = "socx_family_spending.csv"
OECD_TABLE = "staged/oecd/family_spending"
OECD_MART = "marts/oecd_family_spending"
EU_TABLES: dict[str, str] = {
    "cens_21me_r2": "staged/eurostat/census_marital_education",
    "demo_fordagec": "staged/eurostat/births_by_order",
    "demo_pjan": "staged/eurostat/population_female_age",
    "demo_faeduc": "staged/eurostat/births_by_education",
    "lfsa_pgaed": "staged/eurostat/lfs_population_female_education",
}
_EU_PARSERS: dict[str, Callable[[bytes], list[dict[str, object]]]] = {
    "cens_21me_r2": es.census_rows,
    "demo_fordagec": es.births_order_rows,
    "demo_pjan": es.population_female_rows,
    "demo_faeduc": es.births_education_rows,
    "lfsa_pgaed": es.lfs_population_rows,
}
EU_CENSUS_MART = "marts/eu_census_marital_by_education"
EU_TFR_ORDER_MART = "marts/eu_tfr_by_birth_order"
EU_TFR_EDU_MART = "marts/eu_tfr_by_education"


def _sources() -> dict[str, str]:
    """raw name key -> URL. Country metadata is needed to drop aggregates at stage."""
    urls = {key: wb.indicator_url(code) for key, code in wb.INDICATORS.items()}
    urls[wb.COUNTRIES_KEY] = wb.countries_url()
    return urls


def fetch(ctx: Context) -> StageResult:
    written: list[str] = []
    skipped: list[str] = []
    fetched = rejected = 0
    for key, url in _sources().items():
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{key}: {e}")
            continue
        fetched += 1
        if not wb.is_json_list_payload(payload):
            rejected += 1
            skipped.append(f"{key}: non-JSON-list payload (site down?)")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=wb.SOURCE,
            name=f"{key}.json",
            url=url,
            license=wb.LICENSE,
            payload=payload,
        )
        written.append(rec.relative_path)
    if fetched and rejected == fetched:
        msg = f"{wb.SOURCE}: all {fetched} fetched payloads were rejected (site down?)"
        raise RuntimeError(msg)
    for table in estat.TABLES:
        url = table.url
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{table.key}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=table.source,
            name=table.raw_name,
            url=url,
            license=estat.LICENSE,
            payload=payload,
        )
        written.append(rec.relative_path)
    for name, url in DHS_URLS.items():
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{name}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=dhs.SOURCE,
            name=name,
            url=url,
            license=dhs.LICENSE,
            payload=payload,
        )
        written.append(rec.relative_path)
    # ---- H5: OECD / Eurostat
    h5_written, h5_skipped = _fetch_h5(ctx)
    written.extend(h5_written)
    skipped.extend(h5_skipped)
    written, skipped = _fetch_kostat(ctx, written, skipped)
    written, skipped = _fetch_h6(ctx, written, skipped)
    return StageResult(stage=Stage.FETCH, written=tuple(written), skipped=tuple(skipped))


def _stage_worldbank(ctx: Context) -> tuple[list[str], list[str]]:
    written: list[str] = []
    skipped: list[str] = []
    countries_payload = ctx.raw.get(theme=THEME, source=wb.SOURCE, name=f"{wb.COUNTRIES_KEY}.json")
    if countries_payload is None:
        # Fail closed: without metadata, 3-letter aggregates (WLD, NAC, ...) would leak in.
        skipped.append(f"{wb.COUNTRIES_KEY}: raw missing (run fetch); nothing staged")
        skipped.extend(f"{key}: not staged without country metadata" for key in wb.INDICATORS)
        return written, skipped
    ctx.tables.write_table(COUNTRIES_TABLE, wb.country_rows(countries_payload))
    written.append(COUNTRIES_TABLE)
    countries = wb.country_set(countries_payload)
    for key in wb.INDICATORS:
        payload = ctx.raw.get(theme=THEME, source=wb.SOURCE, name=f"{key}.json")
        if payload is None:
            skipped.append(f"{key}: raw missing (run fetch)")
            continue
        table = f"staged/worldbank/{key}"
        ctx.tables.write_table(table, wb.rows_from_response(payload, key=key, countries=countries))
        written.append(table)
    return written, skipped


def _stage_estat(ctx: Context) -> tuple[list[str], list[str]]:
    """One staged table per TableKind, concatenating every survey wave whose raw exists.

    Missing waves are reported in *skipped* (the staged table carries ``survey_year`` so a
    partial set is visible, not silent). A layout error in any file aborts that kind.
    """
    written: list[str] = []
    skipped: list[str] = []
    for kind, table_name in ESTAT_TABLES.items():
        rows: list[dict[str, object]] = []
        present = 0
        for table in estat.tables_of(kind):
            payload = ctx.raw.get(theme=THEME, source=table.source, name=table.raw_name)
            if payload is None:
                skipped.append(f"{table.key}: raw missing (run fetch)")
                continue
            rows.extend(_ESTAT_PARSERS[kind](payload, table))
            present += 1
        if present == 0:
            continue
        ctx.tables.write_table(table_name, rows)
        written.append(table_name)
    return written, skipped


def _stage_dhs(ctx: Context) -> tuple[list[str], list[str]]:
    """TFR by wealth quintile with ISO3 from the DHS countries file (fail closed without it)."""
    written: list[str] = []
    skipped: list[str] = []
    data = ctx.raw.get(theme=THEME, source=dhs.SOURCE, name=DHS_RAW_DATA)
    countries = ctx.raw.get(theme=THEME, source=dhs.SOURCE, name=DHS_RAW_COUNTRIES)
    if data is None or countries is None:
        for name, payload in ((DHS_RAW_DATA, data), (DHS_RAW_COUNTRIES, countries)):
            if payload is None:
                skipped.append(f"{name}: raw missing (run fetch); DHS not staged")
        return written, skipped
    iso3_by_code = dhs.iso3_map(countries)
    ctx.tables.write_table(DHS_TABLE, dhs.rows_from_response(data, iso3_by_dhs_code=iso3_by_code))
    written.append(DHS_TABLE)
    unmapped = dhs.unmapped_codes(data, iso3_by_dhs_code=iso3_by_code)
    if unmapped:
        skipped.append(f"{DHS_RAW_DATA}: no ISO3 for DHS country codes {unmapped}; rows dropped")
    return written, skipped


def stage(ctx: Context) -> StageResult:
    wb_written, wb_skipped = _stage_worldbank(ctx)
    es_written, es_skipped = _stage_estat(ctx)
    dhs_written, dhs_skipped = _stage_dhs(ctx)
    # ---- H5: OECD / Eurostat
    h5_written, h5_skipped = _stage_h5(ctx)
    dhs_written, dhs_skipped = _stage_kostat(ctx, dhs_written, dhs_skipped)
    dhs_written, dhs_skipped = _stage_h6(ctx, dhs_written, dhs_skipped)
    return StageResult(
        stage=Stage.STAGE,
        written=tuple(wb_written + es_written + dhs_written + h5_written),
        skipped=tuple(wb_skipped + es_skipped + dhs_skipped + h5_skipped),
    )


def build_panel(
    staged: dict[str, list[dict[str, object]]], *, countries: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    """Wide iso3×year panel from per-indicator long tables. Pure; missing stays None.

    *countries* (region / income_group per iso3) is joined in; unknown iso3 get None.
    """
    meta = {str(c["iso3"]): c for c in countries}
    panel: dict[tuple[str, int], dict[str, object]] = defaultdict(dict)
    for key, rows in staged.items():
        for r in rows:
            k = (str(r["iso3"]), int(str(r["year"])))
            cell = panel[k]
            cell["iso3"], cell["year"], cell["country"] = k[0], k[1], r["country"]
            cell[key] = r["value"]
    out: list[dict[str, object]] = []
    for k in sorted(panel):
        cell = panel[k]
        m = meta.get(k[0], {})
        out.append(
            {
                "iso3": cell["iso3"],
                "country": cell["country"],
                "year": cell["year"],
                "region": m.get("region"),
                "income_group": m.get("income_group"),
                **{key: cell.get(key) for key in staged},
            }
        )
    return out


def _f(v: object) -> float | None:
    return None if v is None else float(str(v))


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _jp_row(
    r: dict[str, object],
    *,
    metric: str,
    value: float | None,
    denominator: float | None,
    sex: str | None,
) -> dict[str, object]:
    return {
        "survey": estat.SURVEY,
        "survey_year": int(str(r["survey_year"])),
        "year": int(str(r["year"])),
        "income_class": r["income_class"],
        "income_class_lower_yen": r["income_class_lower_yen"],
        "income_class_upper_yen": r["income_class_upper_yen"],
        "sex": sex,
        "metric": metric,
        "value": value,
        "denominator": denominator,
        "source": estat.SOURCE,
    }


def build_income_class_fertility(
    *,
    income_dist: Sequence[dict[str, object]],
    workers_marital: Sequence[dict[str, object]],
    hh_type: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Long table (one metric per row) for H3. Pure and deterministic.

    - ``married_share`` (by sex): 配偶者あり / (配偶者あり + 配偶者なし) among 有業人員 15+ in the
      income class (配偶者不詳 excluded). ``denominator`` = that sum, in 人員10万対 weights.
    - ``children_household_share``: 児童のいる世帯 / 全世帯 in the household income class.
      ``denominator`` = households in the class, 世帯数1万対.
    - ``household_share_pct`` / ``children_household_share_pct``: the 年次推移 relative
      frequency distribution (%, all households vs households with children), 1985-.
    """
    out: list[dict[str, object]] = []
    for r in income_dist:
        metric = (
            "household_share_pct" if r["population"] == "all" else "children_household_share_pct"
        )
        out.append(_jp_row(r, metric=metric, value=_f(r["share_pct"]), denominator=None, sex=None))

    marital: dict[tuple[int, str, str], dict[str, float | None]] = defaultdict(dict)
    rep: dict[tuple[int, str, str], dict[str, object]] = {}
    for r in workers_marital:
        k = (int(str(r["survey_year"])), str(r["sex"]), str(r["income_class"]))
        marital[k][str(r["marital"])] = _f(r["workers_per_100k"])
        rep[k] = r
    for k, parts in marital.items():
        m, u = parts.get("married"), parts.get("unmarried")
        den = None if m is None or u is None else m + u
        out.append(
            _jp_row(rep[k], metric="married_share", value=_ratio(m, den), denominator=den, sex=k[1])
        )

    for r in hh_type:
        den = _f(r["households_per_10k"])
        out.append(
            _jp_row(
                r,
                metric="children_household_share",
                value=_ratio(_f(r["with_children_per_10k"]), den),
                denominator=den,
                sex=None,
            )
        )

    def key(row: dict[str, object]) -> tuple[str, int, int, str, str]:
        lower = row["income_class_lower_yen"]
        return (
            str(row["metric"]),
            int(str(row["year"])),
            -1 if lower is None else int(str(lower)),
            str(row["income_class"]),
            str(row["sex"] or ""),
        )

    out.sort(key=key)
    return out


def build_income_age_marital(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Long table for H3b (age-adjusted gradient). Pure and deterministic.

    One row per survey_year × sex × age_class × income_class with metric
    ``ever_married_share`` = (総数 − うち未婚) / 総数 among 有業者. The 就業構造基本調査 table
    publishes only 総数 and うち未婚, so the complement is *ever married* (有配偶 + 死別・離別),
    not 有配偶 alone. ``denominator`` = 総数 persons in the cell. Rows with
    age_class/income_class = "total" are kept so an unadjusted gradient can be computed from
    the same source. A missing part -> value None.
    """
    cells: dict[tuple[int, str, str, str], dict[str, float | None]] = defaultdict(dict)
    rep: dict[tuple[int, str, str, str], dict[str, object]] = {}
    for r in rows:
        k = (
            int(str(r["survey_year"])),
            str(r["sex"]),
            str(r["age_class"]),
            str(r["income_class"]),
        )
        cells[k][str(r["marital"])] = _f(r["persons"])
        rep[k] = r
    out: list[dict[str, object]] = []
    for k, parts in cells.items():
        total, never = parts.get("total"), parts.get("never_married")
        value = None if total is None or never is None else _ratio(total - never, total)
        r = rep[k]
        out.append(
            {
                "survey": estat.SURVEY_SHUGYO,
                "survey_year": k[0],
                "year": int(str(r["year"])),
                "sex": k[1],
                "age_class": k[2],
                "age_lower": r["age_lower"],
                "age_upper": r["age_upper"],
                "income_class": k[3],
                "income_class_lower_yen": r["income_class_lower_yen"],
                "income_class_upper_yen": r["income_class_upper_yen"],
                "metric": "ever_married_share",
                "value": value,
                "denominator": total,
                "source": r["source"],
            }
        )

    def key(row: dict[str, object]) -> tuple[int, str, int, int, str]:
        age, lower = row["age_lower"], row["income_class_lower_yen"]
        return (
            int(str(row["year"])),
            str(row["sex"]),
            -1 if age is None else int(str(age)),
            -1 if lower is None else int(str(lower)),
            str(row["income_class"]),
        )

    out.sort(key=key)
    return out


def build_dhs_mart(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Mart = staged rows as-is, sorted by survey_year, iso3, quintile. Pure."""
    return sorted(
        (dict(r) for r in rows),
        key=lambda r: (int(str(r["survey_year"])), str(r["iso3"]), int(str(r["quintile"]))),
    )


def mart(ctx: Context) -> StageResult:
    written: list[str] = []
    skipped: list[str] = []
    staged: dict[str, list[dict[str, object]]] = {}
    for key in wb.INDICATORS:
        try:
            staged[key] = ctx.tables.read_table(f"staged/worldbank/{key}")
        except FileNotFoundError:
            skipped.append(f"{key}: staged table missing (run stage)")
    if staged:
        try:
            countries = ctx.tables.read_table(COUNTRIES_TABLE)
        except FileNotFoundError:
            countries = []
            skipped.append(
                f"{wb.COUNTRIES_KEY}: staged table missing; region/income_group are null"
            )
        table = "marts/growth_fertility_panel"
        ctx.tables.write_table(table, build_panel(staged, countries=countries))
        written.append(table)

    estat_staged: dict[estat.TableKind, list[dict[str, object]]] = {}
    for kind, name in ESTAT_TABLES.items():
        try:
            estat_staged[kind] = ctx.tables.read_table(name)
        except FileNotFoundError:
            skipped.append(f"{name}: staged table missing (run stage)")
    kiso_kinds = (
        estat.TableKind.INCOME_DIST_TS,
        estat.TableKind.WORKERS_MARITAL,
        estat.TableKind.HH_TYPE,
    )
    if any(k in estat_staged for k in kiso_kinds):
        rows = build_income_class_fertility(
            income_dist=estat_staged.get(estat.TableKind.INCOME_DIST_TS, []),
            workers_marital=estat_staged.get(estat.TableKind.WORKERS_MARITAL, []),
            hh_type=estat_staged.get(estat.TableKind.HH_TYPE, []),
        )
        ctx.tables.write_table(JP_MART, rows)
        written.append(JP_MART)
    shugyo = estat_staged.get(estat.TableKind.SHUGYO_MARITAL_AGE_INCOME)
    if shugyo is not None:
        ctx.tables.write_table(JP_AGE_MART, build_income_age_marital(shugyo))
        written.append(JP_AGE_MART)

    try:
        dhs_rows = ctx.tables.read_table(DHS_TABLE)
    except FileNotFoundError:
        skipped.append(f"{DHS_TABLE}: staged table missing (run stage)")
    else:
        ctx.tables.write_table(DHS_MART, build_dhs_mart(dhs_rows))
        written.append(DHS_MART)
    # ---- H5: OECD / Eurostat
    h5_written, h5_skipped = _mart_h5(ctx)
    written.extend(h5_written)
    skipped.extend(h5_skipped)
    written, skipped = _mart_kostat(ctx, written, skipped)
    written, skipped = _mart_h6(ctx, written, skipped)
    return StageResult(stage=Stage.MART, written=tuple(written), skipped=tuple(skipped))


# ---- H5: OECD / Eurostat ----------------------------------------------------------------


def _fetch_h5(ctx: Context) -> tuple[list[str], list[str]]:
    """OECD SOCX family spending (1 CSV) + Eurostat JSON-stat, one request per dataset × country."""
    written: list[str] = []
    skipped: list[str] = []
    items: list[tuple[str, str, str, str]] = [
        (oecd.SOURCE, OECD_RAW, oecd.family_spending_url(), oecd.LICENSE)
    ]
    items.extend((es.SOURCE, r.raw_name, r.url, es.LICENSE) for r in es.requests())
    for source, name, url, license_ in items:
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{name}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME, source=source, name=name, url=url, license=license_, payload=payload
        )
        written.append(rec.relative_path)
    return written, skipped


def _stage_h5(ctx: Context) -> tuple[list[str], list[str]]:
    """One staged table per Eurostat dataset (countries concatenated) + the OECD table.

    Missing countries are reported in *skipped*; a dataset with no raw at all is not written.
    """
    written: list[str] = []
    skipped: list[str] = []
    socx = ctx.raw.get(theme=THEME, source=oecd.SOURCE, name=OECD_RAW)
    if socx is None:
        skipped.append(f"{OECD_RAW}: raw missing (run fetch)")
    else:
        ctx.tables.write_table(OECD_TABLE, oecd.family_spending_rows(socx))
        written.append(OECD_TABLE)
    by_dataset: dict[str, list[dict[str, object]]] = {}
    for req in es.requests():
        payload = ctx.raw.get(theme=THEME, source=es.SOURCE, name=req.raw_name)
        if payload is None:
            skipped.append(f"{req.raw_name}: raw missing (run fetch)")
            continue
        by_dataset.setdefault(req.dataset, []).extend(_EU_PARSERS[req.dataset](payload))
    for dataset, table in EU_TABLES.items():
        if dataset in by_dataset:
            ctx.tables.write_table(table, by_dataset[dataset])
            written.append(table)
    return written, skipped


def _mart_h5(ctx: Context) -> tuple[list[str], list[str]]:
    written: list[str] = []
    skipped: list[str] = []
    staged: dict[str, list[dict[str, object]]] = {}
    for table in (OECD_TABLE, *EU_TABLES.values()):
        try:
            staged[table] = ctx.tables.read_table(table)
        except FileNotFoundError:
            skipped.append(f"{table}: staged table missing (run stage)")
    if OECD_TABLE in staged:
        rows = sorted(
            staged[OECD_TABLE],
            key=lambda r: (str(r["iso3"]), int(str(r["year"])), str(r["spending_type"])),
        )
        ctx.tables.write_table(OECD_MART, rows)
        written.append(OECD_MART)
    census = staged.get(EU_TABLES["cens_21me_r2"])
    if census is not None:
        ctx.tables.write_table(EU_CENSUS_MART, es.build_census_mart(census))
        written.append(EU_CENSUS_MART)
    births = staged.get(EU_TABLES["demo_fordagec"])
    women = staged.get(EU_TABLES["demo_pjan"])
    if births is not None and women is not None:
        ctx.tables.write_table(EU_TFR_ORDER_MART, es.build_tfr_by_order(births, women))
        written.append(EU_TFR_ORDER_MART)
    births_edu = staged.get(EU_TABLES["demo_faeduc"])
    lfs = staged.get(EU_TABLES["lfsa_pgaed"])
    if births_edu is not None and lfs is not None:
        ctx.tables.write_table(EU_TFR_EDU_MART, es.build_tfr_by_education(births_edu, lfs))
        written.append(EU_TFR_EDU_MART)
    return written, skipped


# ---- H5: Korea newlywed statistics (PDF) ------------------------------------------------
# 국가데이터처 신혼부부통계 press releases (one PDF per reference year, KOGL type 1). Fetched,
# staged and marted independently of the sources above; every helper appends to and returns the
# accumulators it is given so the fetch/stage/mart bodies only need one extra line each.

KOSTAT_TABLE = "staged/kostat/newlywed_income_children"
KOSTAT_MART = "marts/kr_newlywed_income_children"
KOSTAT_METRICS: tuple[str, ...] = (
    "with_children_share",
    "mean_children",
    "couples",
    "children_1_share",
    "children_2_share",
    "children_3plus_share",
)


def _fetch_kostat(
    ctx: Context, written: list[str], skipped: list[str]
) -> tuple[list[str], list[str]]:
    for release in kostat.RELEASES:
        try:
            payload = ctx.fetcher.fetch(release.url)
        except FetchError as e:
            skipped.append(f"{release.raw_name}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=kostat.SOURCE,
            name=release.raw_name,
            url=release.url,
            license=kostat.LICENSE,
            payload=payload,
        )
        written.append(rec.relative_path)
    return written, skipped


def _stage_kostat(
    ctx: Context, written: list[str], skipped: list[str]
) -> tuple[list[str], list[str]]:
    """One staged table concatenating every release whose PDF parses. A release whose table
    layout is not recognised is reported in *skipped* and does not block the others."""
    rows: list[dict[str, object]] = []
    for release in kostat.RELEASES:
        payload = ctx.raw.get(theme=THEME, source=kostat.SOURCE, name=release.raw_name)
        if payload is None:
            skipped.append(f"{release.raw_name}: raw missing (run fetch)")
            continue
        try:
            rows.extend(kostat.income_children_rows(payload, release))
        except ValueError as e:
            skipped.append(f"{release.raw_name}: layout not recognised ({e})")
    if rows:
        ctx.tables.write_table(KOSTAT_TABLE, rows)
        written.append(KOSTAT_TABLE)
    return written, skipped


def build_kostat_mart(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Long table (one metric per row). Pure and deterministic.

    Consecutive releases re-publish the previous reference year; for each
    (ref_year, income_concept, income_class) the row from the latest release wins (revisions,
    and exact counts instead of the thousands printed by older releases).
    """
    latest: dict[tuple[int, str, str], dict[str, object]] = {}
    for r in rows:
        k = (int(str(r["ref_year"])), str(r["income_concept"]), str(r["income_class"]))
        cur = latest.get(k)
        if cur is None or int(str(r["release_year"])) > int(str(cur["release_year"])):
            latest[k] = r

    def key(k: tuple[int, str, str]) -> tuple[int, str, int]:
        lower = latest[k]["income_lower_10k_krw"]
        return (k[0], k[1], -1 if lower is None else int(str(lower)))

    out: list[dict[str, object]] = []
    for k in sorted(latest, key=key):
        r = latest[k]
        for metric in KOSTAT_METRICS:
            out.append(
                {
                    "ref_year": r["ref_year"],
                    "release_year": r["release_year"],
                    "income_class": r["income_class"],
                    "income_lower_10k_krw": r["income_lower_10k_krw"],
                    "income_upper_10k_krw": r["income_upper_10k_krw"],
                    "metric": metric,
                    "value": r[metric],
                    "income_concept": r["income_concept"],
                    "source": r["source"],
                }
            )
    return out


def _mart_kostat(
    ctx: Context, written: list[str], skipped: list[str]
) -> tuple[list[str], list[str]]:
    try:
        staged_rows = ctx.tables.read_table(KOSTAT_TABLE)
    except FileNotFoundError:
        skipped.append(f"{KOSTAT_TABLE}: staged table missing (run stage)")
        return written, skipped
    ctx.tables.write_table(KOSTAT_MART, build_kostat_mart(staged_rows))
    written.append(KOSTAT_MART)
    return written, skipped


# ---- H6: fertility ideals / expectations surveys ------------------------------------------
# Two PDFs (Testa 2012 = Eurobarometer 75.4 appendix; BiB 2025 = GGS-II Table 1) and the
# Standard Eurobarometer Volume A workbooks (STD91-). The workbook URL is resolved per wave from
# the dataset's JSON-LD (raw ``eb_<code>_meta.json``) so fetch is two steps; a wave whose record
# cannot be fetched or has no Volume A is skipped. Same accumulator style as the kostat block.

SURVEYS_EB_TABLE = "staged/surveys/eb2011_ideals"
SURVEYS_GGS_TABLE = "staged/surveys/ggs2020_ideals"
EB_EXPECT_TABLE = "staged/eurobarometer/expectations"
IDEALS_MART = "marts/eu_fertility_ideals"
EXPECT_MART = "marts/eu_expectations"
_H6_PDFS: tuple[tuple[str, str, str, str], ...] = (
    (surveys.TESTA_SOURCE, surveys.TESTA_RAW, surveys.TESTA_URL, surveys.TESTA_LICENSE),
    (surveys.BIB_SOURCE, surveys.BIB_RAW, surveys.BIB_URL, surveys.BIB_LICENSE),
)


def _fetch_h6(ctx: Context, written: list[str], skipped: list[str]) -> tuple[list[str], list[str]]:
    for source, name, url, license_ in _H6_PDFS:
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{name}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME, source=source, name=name, url=url, license=license_, payload=payload
        )
        written.append(rec.relative_path)
    for wave in ebm.WAVES:
        try:
            meta = ctx.fetcher.fetch(wave.jsonld_url)
        except FetchError as e:
            skipped.append(f"{wave.meta_raw_name}: {e}; Volume A not attempted")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=ebm.SOURCE,
            name=wave.meta_raw_name,
            url=wave.jsonld_url,
            license=ebm.LICENSE,
            payload=meta,
        )
        written.append(rec.relative_path)
        try:
            dist = ebm.vol_a(meta)
        except ValueError as e:
            skipped.append(f"eb_{wave.code}_vol_a: Volume A not resolved ({e})")
            continue
        try:
            workbook = ctx.fetcher.fetch(dist.url)
        except FetchError as e:
            skipped.append(f"{dist.raw_name(wave.code)}: {e}")
            continue
        rec = ctx.raw.put(
            theme=THEME,
            source=ebm.SOURCE,
            name=dist.raw_name(wave.code),
            url=dist.url,
            license=ebm.LICENSE,
            payload=workbook,
        )
        written.append(rec.relative_path)
    return written, skipped


def _stage_h6(ctx: Context, written: list[str], skipped: list[str]) -> tuple[list[str], list[str]]:
    """Each PDF -> its own staged table; all waves -> one expectations table. A PDF or workbook
    whose layout is not recognised is reported in *skipped* and does not block the others."""
    testa = ctx.raw.get(theme=THEME, source=surveys.TESTA_SOURCE, name=surveys.TESTA_RAW)
    if testa is None:
        skipped.append(f"{surveys.TESTA_RAW}: raw missing (run fetch)")
    else:
        try:
            eb_rows, issues = surveys.eb2011_rows(testa)
        except ValueError as e:
            skipped.append(f"{surveys.TESTA_RAW}: layout not recognised ({e})")
        else:
            ctx.tables.write_table(SURVEYS_EB_TABLE, eb_rows)
            written.append(SURVEYS_EB_TABLE)
            skipped.extend(f"{surveys.TESTA_RAW}: {issue}" for issue in issues)
    bib = ctx.raw.get(theme=THEME, source=surveys.BIB_SOURCE, name=surveys.BIB_RAW)
    if bib is None:
        skipped.append(f"{surveys.BIB_RAW}: raw missing (run fetch)")
    else:
        try:
            ggs = surveys.ggs_rows(bib)
        except ValueError as e:
            skipped.append(f"{surveys.BIB_RAW}: layout not recognised ({e})")
        else:
            ctx.tables.write_table(SURVEYS_GGS_TABLE, ggs)
            written.append(SURVEYS_GGS_TABLE)
    rows: list[dict[str, object]] = []
    for wave in ebm.WAVES:
        meta = ctx.raw.get(theme=THEME, source=ebm.SOURCE, name=wave.meta_raw_name)
        if meta is None:
            skipped.append(f"{wave.meta_raw_name}: raw missing (run fetch)")
            continue
        try:
            name = ebm.vol_a(meta).raw_name(wave.code)
        except ValueError as e:
            skipped.append(f"eb_{wave.code}_vol_a: Volume A not resolved ({e})")
            continue
        workbook = ctx.raw.get(theme=THEME, source=ebm.SOURCE, name=name)
        if workbook is None:
            skipped.append(f"{name}: raw missing (run fetch)")
            continue
        try:
            wave_rows = ebm.expectation_rows(workbook, wave)
        except ValueError as e:
            skipped.append(f"{name}: layout not recognised ({e})")
            continue
        if not wave_rows:
            skipped.append(f"{name}: no 'expectations for the next twelve months' sheet")
            continue
        rows.extend(wave_rows)
    if rows:
        ctx.tables.write_table(EB_EXPECT_TABLE, rows)
        written.append(EB_EXPECT_TABLE)
    return written, skipped


def _mart_h6(ctx: Context, written: list[str], skipped: list[str]) -> tuple[list[str], list[str]]:
    """``eu_fertility_ideals`` from whichever survey tables exist; ``eu_expectations`` from the
    Standard Eurobarometer table."""
    ideals: dict[str, list[dict[str, object]]] = {}
    for table in (SURVEYS_EB_TABLE, SURVEYS_GGS_TABLE):
        try:
            ideals[table] = ctx.tables.read_table(table)
        except FileNotFoundError:
            skipped.append(f"{table}: staged table missing (run stage)")
    if ideals:
        mart_rows = surveys.build_ideals_mart(
            ideals.get(SURVEYS_EB_TABLE, []), ideals.get(SURVEYS_GGS_TABLE, [])
        )
        ctx.tables.write_table(IDEALS_MART, mart_rows)
        written.append(IDEALS_MART)
    try:
        expectations = ctx.tables.read_table(EB_EXPECT_TABLE)
    except FileNotFoundError:
        skipped.append(f"{EB_EXPECT_TABLE}: staged table missing (run stage)")
    else:
        ctx.tables.write_table(EXPECT_MART, ebm.build_expectations_mart(expectations))
        written.append(EXPECT_MART)
    return written, skipped
