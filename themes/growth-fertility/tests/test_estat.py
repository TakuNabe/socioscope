from pathlib import Path

import pytest

from theme_growth_fertility import estat

FIXTURES = Path(__file__).parent / "fixtures"
TS = (FIXTURES / "estat_children_hh_income_dist_ts.csv").read_bytes()
MARITAL = (FIXTURES / "estat_workers_marital_income.csv").read_bytes()
HH_TYPE = (FIXTURES / "estat_hh_type_income.csv").read_bytes()

TS_TABLE = next(t for t in estat.TABLES if t.key == "children_hh_income_dist_ts")
MARITAL_TABLE = next(t for t in estat.TABLES if t.key == "workers_marital_income_2025")
HH_TABLE = next(t for t in estat.TABLES if t.key == "hh_type_income_2013")


def test_file_download_url_is_csv_without_app_id() -> None:
    assert estat.file_download_url("000040473361") == (
        "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040473361&fileKind=1"
    )
    with pytest.raises(ValueError, match="12 digits"):
        estat.file_download_url("123")


def test_table_registry_is_unique_and_complete() -> None:
    assert len({t.key for t in estat.TABLES}) == len(estat.TABLES)
    assert len({t.stat_inf_id for t in estat.TABLES}) == len(estat.TABLES)
    assert sorted(t.survey_year for t in estat.tables_of(estat.TableKind.WORKERS_MARITAL)) == [
        2013,
        2016,
        2019,
        2022,
        2025,
    ]


@pytest.mark.parametrize(
    ("label", "code", "lower", "upper"),
    [
        ("総　　数", "total", None, None),
        ("　所得なし", "none", None, None),
        ("　５０万円未満", "0-50", 0, 500_000),
        ("　　５０～１００", "50-100", 500_000, 1_000_000),
        ("　１２００～１５００", "1200-1500", 12_000_000, 15_000_000),
        ("　２０００万円以上", "2000-", 20_000_000, None),
    ],
)
def test_parse_income_class(label: str, code: str, lower: int | None, upper: int | None) -> None:
    ic = estat.parse_income_class(label)
    assert ic is not None
    assert (ic.code, ic.lower_yen, ic.upper_yen) == (code, lower, upper)


def test_parse_income_class_rejects_non_class_labels() -> None:
    assert estat.parse_income_class("相対度数分布") is None
    assert estat.parse_income_class("　男") is None


def test_income_dist_ts_rows_use_income_year_and_keep_missing_as_none() -> None:
    rows = estat.income_dist_rows(TS, TS_TABLE)
    # 3 classes × 3 year columns; 総数 and the 累積度数分布 block are dropped
    assert len(rows) == 9
    assert rows[0] == {
        "population": "with_children",
        "survey_year": 2025,
        "year": 1985,
        "source": "estat_kiso",
        "stat_inf_id": "000040473376",
        "income_class": "0-50",
        "income_class_lower_yen": 0,
        "income_class_upper_yen": 500_000,
        "share_pct": 0.0,
    }
    by = {(r["income_class"], r["year"]): r["share_pct"] for r in rows}
    assert by[("2000-", 2024)] == 3.3
    assert by[("2000-", 2019)] is None  # '…': the 2020 survey was not conducted


def test_workers_marital_rows_track_blocks_and_sex() -> None:
    rows = estat.workers_marital_rows(MARITAL, MARITAL_TABLE)
    assert {(r["marital"], r["sex"]) for r in rows} == {
        (m, s) for m in ("total", "married", "unmarried") for s in ("total", "male", "female")
    }
    assert all(r["year"] == 2024 and r["survey_year"] == 2025 for r in rows)
    by = {(r["marital"], r["sex"], r["income_class"]): r["workers_per_100k"] for r in rows}
    assert by[("total", "total", "total")] == 53919
    assert by[("married", "male", "50-100")] == 286
    assert by[("unmarried", "female", "none")] == 1520
    assert by[("married", "male", "0-50")] == 107
    # '-' means none -> 0 (役員 column is not kept; check via a kept cell elsewhere)
    assert by[("unmarried", "male", "1000-")] == 267


def test_hh_type_rows_find_columns_from_joined_headers() -> None:
    rows = estat.hh_type_rows(HH_TYPE, HH_TABLE)
    assert [r["income_class"] for r in rows] == ["total", "0-50", "50-100", "2000-"]
    assert rows[1] == {
        "survey_year": 2013,
        "year": 2012,
        "source": "estat_kiso",
        "stat_inf_id": "000026222010",
        "income_class": "0-50",
        "income_class_lower_yen": 0,
        "income_class_upper_yen": 500_000,
        "households_per_10k": 129.0,
        "with_children_per_10k": 2.0,
        "single_mother_per_10k": 0.0,  # '-'
    }


def test_parsing_is_deterministic() -> None:
    assert estat.workers_marital_rows(MARITAL, MARITAL_TABLE) == estat.workers_marital_rows(
        MARITAL, MARITAL_TABLE
    )


def test_wrong_table_or_layout_fails_closed() -> None:
    with pytest.raises(ValueError, match="title"):
        estat.parse_workers_marital(HH_TYPE)
    with pytest.raises(ValueError, match="title"):
        estat.parse_hh_type(TS)
    with pytest.raises(ValueError, match="not cp932"):
        estat.parse_hh_type("所得金額階級,総数\n".encode("utf-16"))
    truncated = MARITAL.decode("cp932").split("配偶者なし")[0].encode("cp932")
    with pytest.raises(ValueError, match="incomplete"):
        estat.parse_workers_marital(truncated)
    with pytest.raises(ValueError, match="not an income-distribution"):
        estat.income_dist_rows(TS, HH_TABLE)


def test_unexpected_numeric_cell_fails_closed() -> None:
    bad = TS.decode("cp932").replace("0.5,…,0.6", "abc,…,0.6").encode("cp932")
    with pytest.raises(ValueError, match="numeric"):
        estat.parse_income_dist_ts(bad, population="with_children")
