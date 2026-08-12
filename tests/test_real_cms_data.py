"""Against the complete CMS RVU26C release committed to this repo.

Every value asserted here is read from CMS's published files, and the computed
rates are checked against arithmetic worked by hand from those values.
"""
from datetime import date
from pathlib import Path

import pytest

from pfs import FeeSchedulePeriod, RateEngine, Setting, UnknownCPTCode
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"

RVU_FILE = DATA / "PPRRVU2026_Jul_nonQPP.csv"
GPCI_FILE = DATA / "GPCI2026.csv"

pytestmark = pytest.mark.skipif(
    not (RVU_FILE.exists() and GPCI_FILE.exists()),
    reason="full CMS release not present",
)

ALABAMA = "10112-AL-00"
SAN_FRANCISCO = "01112-CA-05"


@pytest.fixture(scope="module")
def rvu_layout():
    return ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")


@pytest.fixture(scope="module")
def rvus(rvu_layout):
    return load_rvus(RVU_FILE, rvu_layout)


@pytest.fixture(scope="module")
def gpcis():
    return load_gpcis(GPCI_FILE, ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))


@pytest.fixture(scope="module")
def conversion_factor(rvu_layout):
    return load_conversion_factor(RVU_FILE, rvu_layout)


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


# --- the release loads whole ------------------------------------------------

def test_whole_release_loads(rvus, gpcis):
    """19,356 priceable lines and 98 localities, with nothing rejected."""
    assert len(rvus) == 19356
    assert len(gpcis) == 98


def test_conversion_factor_is_consistent_across_every_row(conversion_factor):
    """Read from the column CMS repeats on all 19k rows; one value or refuse."""
    assert conversion_factor == 33.4009


def test_footnotes_below_the_data_are_not_read_as_localities(gpcis):
    """GPCI carries footnote prose after a blank row; none of it is a locality."""
    assert all(len(key.split("-")) == 3 for key in gpcis)
    assert not any("Note" in key or "floor" in key for key in gpcis)


# --- keys that are not unique ------------------------------------------------

def test_mac_and_locality_alone_would_collide_two_states(gpcis):
    """MAC 05102 serves Connecticut and Iowa, both locality 00.

    Their indices differ substantially. Keying on MAC+locality would silently
    price one state with the other's practice expense.
    """
    connecticut = gpcis["05102-CT-00"]
    iowa = gpcis["05102-IA-00"]

    assert connecticut.locality_name == "CONNECTICUT"
    assert iowa.locality_name == "IOWA"
    assert connecticut.practice_expense == 1.122
    assert iowa.practice_expense == 0.900


def test_the_other_colliding_mac(gpcis):
    assert gpcis["03502-SD-00"].locality_name.startswith("SOUTH DAKOTA")
    assert gpcis["03502-UT-00"].locality_name == "UTAH"


def test_modifier_variants_load_as_separate_lines(rvus):
    """71046 exists global, professional (26) and technical (TC)."""
    assert {"71046", "71046-26", "71046-TC"} <= set(rvus)
    assert rvus["71046-26"].work == rvus["71046"].work
    assert rvus["71046-TC"].work == 0.00


def test_the_release_really_does_carry_thousands_of_modifier_rows(rvus):
    """Keyed on the code alone, these 2,261 rows would have refused the file."""
    professional = [k for k in rvus if k.endswith("-26")]
    technical = [k for k in rvus if k.endswith("-TC")]

    assert len(professional) == 1138
    assert len(technical) == 1119


# --- real rates --------------------------------------------------------------

def test_published_rvus_for_99214(rvus):
    entry = rvus["99214"]
    assert entry.work == 1.92
    assert entry.practice_expense_non_facility == 2.00
    assert entry.practice_expense_facility == 0.47
    assert entry.malpractice == 0.14
    assert entry.status_code == "A"


@pytest.mark.parametrize(
    "code,non_facility_total,facility_total",
    [("99213", 2.85, 1.72), ("99214", 4.06, 2.53)],
)
def test_components_reconcile_to_cms_published_totals(
    rvus, code, non_facility_total, facility_total
):
    """Independent proof the column positions are right.

    CMS publishes the totals in their own columns; our separately-parsed
    components must sum to them. If facility and non-facility PE were swapped,
    these would not reconcile.
    """
    entry = rvus[code]
    assert entry.work + entry.practice_expense_non_facility + entry.malpractice == pytest.approx(
        non_facility_total, abs=0.005
    )
    assert entry.work + entry.practice_expense_facility + entry.malpractice == pytest.approx(
        facility_total, abs=0.005
    )


def test_rate_matches_hand_calculation(engine):
    """CPT 99214, Alabama, non-facility, 2026 date of service.

        work  1.92 x 1.000 = 1.920000
        PE    2.00 x 0.875 = 1.750000
        MP    0.14 x 0.566 = 0.079240
                       sum = 3.749240
        3.749240 x 33.4009 = 125.227990  ->  $125.23
    """
    result = engine.rate_for_locality(
        "99214", ALABAMA, Setting.NON_FACILITY, date(2026, 3, 14)
    )

    assert result.allowed_amount == 125.23
    assert result.locality_name == "ALABAMA"
    assert result.conversion_factor == 33.4009
    assert result.source == "cms-pfs:2026-RVU26C:10112-AL-00"


def test_facility_rate_matches_hand_calculation(engine):
    """Same code and locality, facility setting.

        work  1.92 x 1.000 = 1.920000
        PE    0.47 x 0.875 = 0.411250
        MP    0.14 x 0.566 = 0.079240
                       sum = 2.410490
        2.410490 x 33.4009 = 80.512... ->  $80.51
    """
    result = engine.rate_for_locality(
        "99214", ALABAMA, Setting.FACILITY, date(2026, 3, 14)
    )
    assert result.allowed_amount == 80.51


def test_geography_moves_the_rate(engine):
    """San Francisco against Alabama, same code, same day."""
    alabama = engine.rate_for_locality(
        "99214", ALABAMA, Setting.NON_FACILITY, date(2026, 3, 14)
    )
    san_francisco = engine.rate_for_locality(
        "99214", SAN_FRANCISCO, Setting.NON_FACILITY, date(2026, 3, 14)
    )

    assert alabama.allowed_amount == 125.23
    assert san_francisco.allowed_amount == 166.40
    assert san_francisco.allowed_amount > alabama.allowed_amount


def test_professional_component_prices_below_the_global_service(engine):
    """A line billed -26 is the physician's read, not the whole study.

    Pricing it against the global RVUs would overstate the benchmark, which is
    the practical reason modifiers had to become part of the key.
    """
    global_service = engine.rate_for_locality(
        "71046", ALABAMA, Setting.NON_FACILITY, date(2026, 3, 14)
    )
    professional = engine.rate_for_locality(
        "71046", ALABAMA, Setting.NON_FACILITY, date(2026, 3, 14), modifier="26"
    )

    assert global_service.allowed_amount == 29.60
    assert professional.allowed_amount == 9.54
    assert professional.allowed_amount < global_service.allowed_amount


def test_unknown_code_is_refused_not_estimated(engine):
    with pytest.raises(UnknownCPTCode):
        engine.rate_for_locality("99999", ALABAMA, Setting.FACILITY, date(2026, 3, 14))


def test_result_carries_a_reproducible_derivation(engine):
    result = engine.rate_for_locality(
        "99214", ALABAMA, Setting.NON_FACILITY, date(2026, 3, 14)
    )
    total = (
        result.work_component
        + result.practice_expense_component
        + result.malpractice_component
    )
    assert round(total * result.conversion_factor, 2) == result.allowed_amount
    assert "99214" in result.explain()
    assert "ALABAMA" in result.explain()
