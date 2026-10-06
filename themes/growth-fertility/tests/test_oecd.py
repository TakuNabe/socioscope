from pathlib import Path

import pytest

from theme_growth_fertility import oecd

FIXTURE = (Path(__file__).parent / "fixtures" / "oecd_socx_family.csv").read_bytes()


def test_family_spending_url_targets_public_family_programmes_by_spending_type() -> None:
    url = oecd.family_spending_url()
    assert url.startswith(
        "https://sdmx.oecd.org/public/rest/data/OECD.ELS.SPD,DSD_SOCX_AGG@DF_SOCX_AGG,1.0/"
    )
    assert "/.A.SOCX.PT_B1GQ.ES10._T+C+K.TP51._Z?" in url
    assert "startPeriod=1980" in url and "format=csvfilewithlabels" in url


def test_family_spending_rows_keep_members_drop_aggregates_and_blanks() -> None:
    rows = oecd.family_spending_rows(FIXTURE)
    assert {r["iso3"] for r in rows} == {"FIN", "KOR"}  # OECD aggregate + blank LVA dropped
    assert rows[0] == {
        "iso3": "FIN",
        "year": 2019,
        "spending_type": "C",
        "value": 1.113,
        "unit": "PT_B1GQ",
        "source": "oecd_socx",
    }
    assert [(r["iso3"], r["year"], r["spending_type"]) for r in rows[:3]] == [
        ("FIN", 2019, "C"),
        ("FIN", 2019, "K"),
        ("FIN", 2019, "_T"),
    ]
    assert len(rows) == 12
    assert {r["spending_type"] for r in rows} == {"_T", "C", "K"}


def test_family_spending_rows_fail_closed_on_other_dataflow_or_dimension() -> None:
    other = FIXTURE.replace(b"DSD_SOCX_AGG@DF_SOCX_AGG(1.0)", b"DSD_X@DF_X(1.0)")
    with pytest.raises(ValueError, match="STRUCTURE_ID"):
        oecd.family_spending_rows(other)
    pension = FIXTURE.replace(b",TP51,Family,", b",TP10,Old age,")
    with pytest.raises(ValueError, match="PROGRAMME_TYPE"):
        oecd.family_spending_rows(pension)
    with pytest.raises(ValueError, match="header"):
        oecd.family_spending_rows(b"a,b,c\n1,2,3\n")


def test_oecd_members_are_38_iso3() -> None:
    assert len(oecd.OECD_MEMBERS) == 38 and all(len(c) == 3 for c in oecd.OECD_MEMBERS)
