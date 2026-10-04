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


# -------------------------------------- 就業構造基本調査 第40表 (xlsx, 配偶関係×年齢×所得)

SHUGYO = (FIXTURES / "estat_shugyo_marital_age_income.xlsx").read_bytes()
SHUGYO_TABLE = next(t for t in estat.TABLES if t.key == "shugyo_marital_age_income_2022")


def test_shugyo_table_is_excel_download_without_app_id() -> None:
    assert SHUGYO_TABLE.url == (
        "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040077301&fileKind=0"
    )
    assert SHUGYO_TABLE.raw_name == "shugyo_marital_age_income_2022.xlsx"
    assert SHUGYO_TABLE.source == "estat_shugyo"
    assert MARITAL_TABLE.source == "estat_kiso" and MARITAL_TABLE.raw_name.endswith(".csv")
    assert MARITAL_TABLE.url.endswith("fileKind=1")


@pytest.mark.parametrize(
    ("label", "code", "lower", "upper"),
    [
        ("00_総数", "total", None, None),
        ("01_15～19歳", "15-19", 15, 20),
        ("03_25～29歳", "25-29", 25, 30),
        ("15_85歳以上", "85-", 85, None),
    ],
)
def test_parse_age_class(label: str, code: str, lower: int | None, upper: int | None) -> None:
    ac = estat.parse_age_class(label)
    assert ac is not None
    assert (ac.code, ac.lower, ac.upper) == (code, lower, upper)
    assert estat.parse_age_class("0_総数") is not None
    assert estat.parse_age_class("1_男") is None


@pytest.mark.parametrize(
    ("label", "code", "lower", "upper"),
    [
        ("00_総数", "total", None, None),
        ("01_50万円未満", "0-50", 0, 500_000),
        ("02_50～99万円", "50-100", 500_000, 1_000_000),  # 99 means '< 100': upper = hi + 1
        ("14_1000～1249万円", "1000-1250", 10_000_000, 12_500_000),
        ("16_1500万円以上", "1500-", 15_000_000, None),
    ],
)
def test_parse_income_class_shugyo(
    label: str, code: str, lower: int | None, upper: int | None
) -> None:
    ic = estat.parse_income_class_shugyo(label)
    assert ic is not None
    assert (ic.code, ic.lower_yen, ic.upper_yen) == (code, lower, upper)


def test_xlsx_rows_reads_shared_strings_and_numbers() -> None:
    rows = estat.xlsx_rows(SHUGYO)
    assert rows[1][1].startswith("第４０表")
    assert rows[9][2] == "00_全国" and rows[9][13] == "67060400"  # first data row: 総数/総数
    with pytest.raises(ValueError, match="not an xlsx"):
        estat.xlsx_rows(MARITAL)


def test_shugyo_rows_keep_status_total_and_education_total_only() -> None:
    rows = estat.shugyo_marital_age_income_rows(SHUGYO, SHUGYO_TABLE)
    # fixture: 2 sexes x 2 marital x 3 ages x 4 income classes, 従業上の地位 = 総数 only
    assert len(rows) == 48
    assert {r["sex"] for r in rows} == {"total", "male"}
    assert {r["marital"] for r in rows} == {"total", "never_married"}
    assert all(
        r["survey_year"] == 2022
        and r["year"] == 2022
        and r["source"] == "estat_shugyo"
        and r["stat_inf_id"] == "000040077301"
        for r in rows
    )
    by = {(r["sex"], r["marital"], r["age_class"], r["income_class"]): r for r in rows}
    assert by[("male", "total", "25-29", "total")]["persons"] == 2_928_900
    assert by[("male", "never_married", "25-29", "total")]["persons"] == 2_200_100
    r = by[("male", "never_married", "25-29", "0-50")]
    assert r["persons"] == 44_800 and r["age_lower"] == 25 and r["age_upper"] == 30
    assert r["income_class_lower_yen"] == 0 and r["income_class_upper_yen"] == 500_000
    r = by[("male", "never_married", "85-", "1500-")]
    assert r["persons"] == 0.0  # '-' = none
    assert r["age_upper"] is None and r["income_class_upper_yen"] is None
    assert by[("total", "total", "total", "total")]["persons"] == 67_060_400
    assert rows == estat.shugyo_marital_age_income_rows(SHUGYO, SHUGYO_TABLE)


def test_shugyo_wrong_table_fails_closed() -> None:
    with pytest.raises(ValueError, match="not an xlsx"):
        estat.parse_shugyo_marital_age_income(HH_TYPE)
    with pytest.raises(ValueError, match="not a 就業構造基本調査"):
        estat.shugyo_marital_age_income_rows(SHUGYO, MARITAL_TABLE)
    with pytest.raises(ValueError, match="not an income-distribution"):
        estat.income_dist_rows(SHUGYO, SHUGYO_TABLE)
