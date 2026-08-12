"""Against the real CMS files committed to this repo.

These are the tests that make the layouts more than a guess. Every value
asserted here was taken from CMS's own published file, and the computed rate
is checked against arithmetic worked by hand from those values.

The committed files are excerpts, not complete releases — the GPCI extract
stops partway through California and the PPRRVU sample carries ten codes. That
is enough to verify structure and arithmetic, which is what these cover.
"""
from datetime import date
from pathlib import Path

import pytest

from pfs import (
    FeeSchedulePeriod,
    RateEngine,
    Setting,
    UnknownCPTCode,
)
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"

RVU_FILE = DATA / "PPRRVU2026_Jul_nonQPP_SAMPLE.csv"
GPCI_FILE = DATA / "GPCI2026.csv"

pytestmark = pytest.mark.skipif(
    not (RVU_FILE.exists() and GPCI_FILE.exists()),
    reason="CMS data files not present",
)


@pytest.fixture(scope="module")
def rvus():
    return load_rvus(RVU_FILE, ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json"))


@pytest.fixture(scope="module")
def gpcis():
    return load_gpcis(GPCI_FILE, ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))


@pytest.fixture(scope="module")
def conversion_factor():
    return load_conversion_factor(RVU_FILE, ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json"))


@pytest.fixture(scope="module")
def engine(rvus, gpcis, conversion_factor):
    period = FeeSchedulePeriod(
        period_id="2026-RVU26C",
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        conversion_factor=conversion_factor,
        rvus=rvus,
        gpcis=gpcis,
    )
    return RateEngine([period], zip_to_locality={})


def test_conversion_factor_comes_from_the_file(conversion_factor):
    """Not hardcoded — read from the column CMS repeats on every row."""
    assert conversion_factor == 33.4009


def test_real_rvus_match_the_published_file(rvus):
    """Values read straight off PPRRVU2026_Jul_nonQPP."""
    entry = rvus["99214"]
    assert entry.work == 1.92
    assert entry.practice_expense_non_facility == 1.83
    assert entry.practice_expense_facility == 0.79
    assert entry.malpractice == 0.13
    assert entry.status_code == "A"


def test_split_header_columns_are_not_confused(rvus):
    """'PE RVU' appears twice in the header row; position must tell them apart.

    If facility and non-facility were swapped, these would trade places — and
    the published totals below would not reconcile.
    """
    entry = rvus["99213"]
    assert entry.practice_expense_non_facility == 1.35
    assert entry.practice_expense_facility == 0.57
    assert entry.practice_expense_non_facility > entry.practice_expense_facility


@pytest.mark.parametrize(
    "code,non_facility_total,facility_total",
    [("99213", 2.74, 1.96), ("99214", 3.88, 2.84)],
)
def test_components_reconcile_to_the_published_totals(
    rvus, code, non_facility_total, facility_total
):
    """CMS publishes the totals; our parsed components must sum to them.

    This is the check that proves the column positions are right, independent
    of anything asserted by hand.
    """
    entry = rvus[code]
    assert entry.work + entry.practice_expense_non_facility + entry.malpractice == pytest.approx(
        non_facility_total, abs=0.005
    )
    assert entry.work + entry.practice_expense_facility + entry.malpractice == pytest.approx(
        facility_total, abs=0.005
    )


def test_locality_key_is_mac_plus_locality_number(gpcis):
    """Locality number alone is ambiguous — Alabama and Arizona are both '00'."""
    assert gpcis["10112-00"].locality_name == "ALABAMA"
    assert gpcis["03102-00"].locality_name == "ARIZONA"
    assert gpcis["10112-00"].practice_expense != gpcis["03102-00"].practice_expense


def test_real_gpci_values(gpcis):
    alabama = gpcis["10112-00"]
    assert alabama.work == 1.000
    assert alabama.practice_expense == 0.875
    assert alabama.malpractice == 0.566


def test_end_to_end_rate_matches_hand_calculation(engine):
    """CPT 99214, Alabama, non-facility, from real CMS data.

        work  1.92 x 1.000 = 1.920000
        PE    1.83 x 0.875 = 1.601250
        MP    0.13 x 0.566 = 0.073580
                       sum = 3.594830
        3.594830 x 33.4009 = 120.070557  ->  $120.07
    """
    result = engine.rate_for_locality(
        "99214", "10112-00", Setting.NON_FACILITY, date(2026, 3, 14)
    )

    assert result.allowed_amount == 120.07
    assert result.locality_name == "ALABAMA"
    assert result.conversion_factor == 33.4009
    assert result.source == "cms-pfs:2026-RVU26C:10112-00"


def test_same_code_costs_more_in_a_high_cost_locality(engine):
    """Geography is the product. San Francisco against Alabama, same code."""
    alabama = engine.rate_for_locality(
        "99214", "10112-00", Setting.NON_FACILITY, date(2026, 3, 14)
    )
    san_francisco = engine.rate_for_locality(
        "99214", "01112-05", Setting.NON_FACILITY, date(2026, 3, 14)
    )
    assert san_francisco.allowed_amount > alabama.allowed_amount


def test_facility_setting_prices_lower_on_real_data(engine):
    """Facility PE RVU is smaller, so the facility rate must come out lower."""
    non_facility = engine.rate_for_locality(
        "99214", "10112-00", Setting.NON_FACILITY, date(2026, 3, 14)
    )
    facility = engine.rate_for_locality(
        "99214", "10112-00", Setting.FACILITY, date(2026, 3, 14)
    )
    assert facility.allowed_amount < non_facility.allowed_amount


def test_a_code_outside_the_sample_is_refused_not_estimated(engine):
    with pytest.raises(UnknownCPTCode):
        engine.rate_for_locality("99999", "10112-00", Setting.FACILITY, date(2026, 3, 14))


def test_derivation_is_reproducible_from_the_result(engine):
    """The result must carry enough to re-derive itself."""
    result = engine.rate_for_locality(
        "99214", "10112-00", Setting.NON_FACILITY, date(2026, 3, 14)
    )
    total = (
        result.work_component
        + result.practice_expense_component
        + result.malpractice_component
    )
    assert round(total * result.conversion_factor, 2) == result.allowed_amount
    assert "99214" in result.explain()
    assert "ALABAMA" in result.explain()
