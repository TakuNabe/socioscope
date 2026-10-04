"""fetch -> stage -> mart for growth-fertility. All I/O goes through ports in Context."""

from collections import defaultdict
from collections.abc import Sequence

from socioscope_core.core.pipeline import Context, Stage, StageResult
from socioscope_core.ports.fetcher import FetchError
from theme_growth_fertility import worldbank as wb

THEME = "growth-fertility"
COUNTRIES_TABLE = f"staged/worldbank/{wb.COUNTRIES_KEY}"


def _sources() -> dict[str, str]:
    """raw name key -> URL. Country metadata is needed to drop aggregates at stage."""
    urls = {key: wb.indicator_url(code) for key, code in wb.INDICATORS.items()}
    urls[wb.COUNTRIES_KEY] = wb.countries_url()
    return urls


def fetch(ctx: Context) -> StageResult:
    written: list[str] = []
    skipped: list[str] = []
    for key, url in _sources().items():
        try:
            payload = ctx.fetcher.fetch(url)
        except FetchError as e:
            skipped.append(f"{key}: {e}")
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
    return StageResult(stage=Stage.FETCH, written=tuple(written), skipped=tuple(skipped))


def stage(ctx: Context) -> StageResult:
    written: list[str] = []
    skipped: list[str] = []
    countries_payload = ctx.raw.get(theme=THEME, source=wb.SOURCE, name=f"{wb.COUNTRIES_KEY}.json")
    if countries_payload is None:
        # Fail closed: without metadata, 3-letter aggregates (WLD, NAC, ...) would leak in.
        skipped.append(f"{wb.COUNTRIES_KEY}: raw missing (run fetch); nothing staged")
        skipped.extend(f"{key}: not staged without country metadata" for key in wb.INDICATORS)
        return StageResult(stage=Stage.STAGE, skipped=tuple(skipped))
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
    return StageResult(stage=Stage.STAGE, written=tuple(written), skipped=tuple(skipped))


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


def mart(ctx: Context) -> StageResult:
    staged: dict[str, list[dict[str, object]]] = {}
    skipped: list[str] = []
    for key in wb.INDICATORS:
        try:
            staged[key] = ctx.tables.read_table(f"staged/worldbank/{key}")
        except FileNotFoundError:
            skipped.append(f"{key}: staged table missing (run stage)")
    if not staged:
        return StageResult(stage=Stage.MART, skipped=tuple(skipped))
    try:
        countries = ctx.tables.read_table(COUNTRIES_TABLE)
    except FileNotFoundError:
        countries = []
        skipped.append(f"{wb.COUNTRIES_KEY}: staged table missing; region/income_group are null")
    table = "marts/growth_fertility_panel"
    ctx.tables.write_table(table, build_panel(staged, countries=countries))
    return StageResult(stage=Stage.MART, written=(table,), skipped=tuple(skipped))
