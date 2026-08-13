"""Outpatient facility pricing.

Fixtures are synthetic — the structure is real, the numbers are not CMS's.
What is verified is the wage-index arithmetic, that status indicators gate
payment, and that Addendum B loads through the same configuration machinery
as every other CMS file.
"""
from datetime import date

import pytest

from pfs.loaders import ColumnMap, FileFormatError
from pfs.opps import (
    APCAssignment,
    NoAddendumForDate,
    NotPayableUnderOPPS,
    OPPSEngine,
    OPPSPeriod,
    UnknownHCPCS,
    UnknownWageIndex,
    WageIndex,
    load_addendum_b,
    load_wage_indices,
    wage_adjust,
)

DOS = date(2026, 3, 14)

# Illustrative. CMS publishes the labour share as policy; it is data here.
LABOUR_SHARE = 0.60

ASSIGNMENTS = {
    "99284": APCAssignment("99284", "V", apc="5023", description="ED visit level 4",
                           national_rate=450.00),
    "71046": APCAssignment("71046", "S", apc="5521", description="Chest x-ray",
                           national_rate=62.00),
    "36415": APCAssignment("36415", "N", apc="", description="Venipuncture"),
    "27130": APCAssignment("27130", "C", apc="", description="Hip replacement"),
    "J1885": APCAssignment("J1885", "K", apc="9999", description="Ketorolac",
                           national_rate=3.20),
}

WAGE_INDICES = {
    "41860": WageIndex("41860", "San Francisco-Oakland-Berkeley, CA", 1.7600),
    "13820": WageIndex("13820", "Birmingham-Hoover, AL", 0.7800),
}


def period(period_id="2026-Q3", start=date(2026, 1, 1), end=date(2026, 12, 31)):
    return OPPSPeriod(period_id, start, end, LABOUR_SHARE, ASSIGNMENTS, WAGE_INDICES)


@pytest.fixture
def engine():
    return OPPSEngine([period()])


# --- the calculation ---------------------------------------------------------

def test_national_rate_when_no_area_is_given(engine):
    """An unadjusted figure is fine, provided the result says it is one."""
    result = engine.rate("71046", DOS)

    assert result.allowed_amount == 62.00
    assert result.wage_index is None
    assert "no wage index applied" in result.explain()
    assert result.source == "cms-opps:2026-Q3:national"


def test_wage_index_applies_to_the_labour_share_only(engine):
    """The whole point of the OPPS geographic adjustment.

        450.00 x [(0.60 x 1.76) + 0.40]
      = 450.00 x [1.056 + 0.40]
      = 450.00 x 1.456
      = 655.20
    """
    result = engine.rate("99284", DOS, area="41860")

    assert result.allowed_amount == 655.20
    assert result.wage_index == 1.76
    assert result.area_name.startswith("San Francisco")


def test_a_low_wage_area_prices_below_national(engine):
    """450.00 x [(0.60 x 0.78) + 0.40] = 450.00 x 0.868 = 390.60"""
    assert engine.rate("99284", DOS, area="13820").allowed_amount == 390.60


def test_adjusting_the_whole_payment_would_give_a_different_answer():
    """Guards against applying the wage index to the full amount.

    A naive implementation multiplies everything by the index: 450 x 1.76 =
    792.00 rather than 655.20. Nearly 21% too high, and entirely plausible
    looking.
    """
    correct = wage_adjust(450.00, LABOUR_SHARE, 1.76)
    naive = 450.00 * 1.76

    assert round(correct, 2) == 655.20
    assert round(naive, 2) == 792.00


def test_labour_share_comes_from_the_period_not_the_code():
    """CMS republishes the labour share; it must be data, not a constant."""
    other = OPPSPeriod("alt", date(2026, 1, 1), date(2026, 12, 31),
                       0.50, ASSIGNMENTS, WAGE_INDICES)
    result = OPPSEngine([other]).rate("99284", DOS, area="41860")

    # 450 x [(0.50 x 1.76) + 0.50] = 450 x 1.38 = 621.00
    assert result.allowed_amount == 621.00


# --- status indicators gate payment ------------------------------------------

def test_packaged_code_is_refused_with_its_indicator(engine):
    with pytest.raises(NotPayableUnderOPPS) as exc:
        engine.rate("36415", DOS, area="41860")

    assert exc.value.indicator == "N"
    assert "packaged" in str(exc.value)


def test_inpatient_only_code_is_refused(engine):
    with pytest.raises(NotPayableUnderOPPS) as exc:
        engine.rate("27130", DOS)
    assert exc.value.indicator == "C"
    assert "inpatient" in str(exc.value).lower()


def test_a_payable_indicator_with_no_rate_is_still_refused():
    """A payable status and a missing amount is not a payment of zero."""
    sparse = OPPSPeriod(
        "2026-Q3", date(2026, 1, 1), date(2026, 12, 31), LABOUR_SHARE,
        {"12345": APCAssignment("12345", "S", apc="1", national_rate=None)},
        WAGE_INDICES,
    )
    with pytest.raises(NotPayableUnderOPPS):
        OPPSEngine([sparse]).rate("12345", DOS)


def test_drug_pass_through_prices(engine):
    assert engine.rate("J1885", DOS).allowed_amount == 3.20


# --- refusals ----------------------------------------------------------------

def test_unknown_code_is_refused(engine):
    with pytest.raises(UnknownHCPCS):
        engine.rate("00000", DOS)


def test_unknown_area_is_refused_rather_than_falling_back_to_national(engine):
    """Silently dropping to the national rate would misprice by the index."""
    with pytest.raises(UnknownWageIndex):
        engine.rate("99284", DOS, area="99999")


def test_date_outside_the_loaded_release_is_refused(engine):
    with pytest.raises(NoAddendumForDate):
        engine.rate("99284", date(2024, 6, 1))


def test_overlapping_periods_are_rejected_at_construction():
    with pytest.raises(ValueError, match="overlap"):
        OPPSEngine([
            period("a", date(2026, 1, 1), date(2026, 12, 31)),
            period("b", date(2026, 6, 1), date(2027, 6, 1)),
        ])


def test_result_carries_a_reproducible_derivation(engine):
    result = engine.rate("99284", DOS, area="41860")
    text = result.explain()

    assert "99284" in text and "5023" in text
    assert "1.7600" in text
    assert "655.20" in text
    assert result.source == "cms-opps:2026-Q3:41860"


# --- loading -----------------------------------------------------------------

ADDENDUM = """HCPCS Code,Modifier,Short Descriptor,SI,APC,Payment Rate
99284,,ED visit level 4,V,5023,450.00
71046,,Chest x-ray 2 views,S,5521,62.00
36415,,Venipuncture,N,,
27130,,Hip replacement,C,,
"""

ADDENDUM_MAP = ColumnMap(fields={
    "hcpcs": "HCPCS Code", "modifier": "Modifier", "description": "Short Descriptor",
    "status_indicator": "SI", "apc": "APC", "national_rate": "Payment Rate",
})

WAGES = """CBSA,Area Name,Wage Index
41860,San Francisco-Oakland-Berkeley CA,1.7600
13820,Birmingham-Hoover AL,0.7800
"""

WAGE_MAP = ColumnMap(fields={
    "area": "CBSA", "area_name": "Area Name", "wage_index": "Wage Index",
})


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_loads_addendum_b(tmp_path):
    table = load_addendum_b(write(tmp_path, "b.csv", ADDENDUM), ADDENDUM_MAP)

    assert set(table) == {"99284", "71046", "36415", "27130"}
    assert table["99284"].national_rate == 450.00
    assert table["99284"].status_indicator == "V"
    assert table["99284"].separately_payable


def test_a_blank_payment_rate_stays_none(tmp_path):
    """Packaged codes publish no rate. None is not zero."""
    table = load_addendum_b(write(tmp_path, "b.csv", ADDENDUM), ADDENDUM_MAP)

    assert table["36415"].national_rate is None
    assert not table["36415"].separately_payable


def test_blank_status_indicator_is_rejected(tmp_path):
    broken = ADDENDUM + "99285,,ED visit level 5,,5024,600.00\n"
    with pytest.raises(FileFormatError, match="blank status indicator"):
        load_addendum_b(write(tmp_path, "b.csv", broken), ADDENDUM_MAP)


def test_conflicting_duplicate_is_rejected(tmp_path):
    broken = ADDENDUM + "99284,,ED visit level 4,V,5023,999.00\n"
    with pytest.raises(FileFormatError, match="conflicting duplicate"):
        load_addendum_b(write(tmp_path, "b.csv", broken), ADDENDUM_MAP)


def test_loads_wage_indices(tmp_path):
    table = load_wage_indices(write(tmp_path, "w.csv", WAGES), WAGE_MAP)

    assert table["41860"].index == 1.76
    assert table["13820"].area_name.startswith("Birmingham")


def test_loaded_files_price_end_to_end(tmp_path):
    """Real files in, a real outpatient payment out."""
    assignments = load_addendum_b(write(tmp_path, "b.csv", ADDENDUM), ADDENDUM_MAP)
    wages = load_wage_indices(write(tmp_path, "w.csv", WAGES), WAGE_MAP)

    engine = OPPSEngine([OPPSPeriod(
        "2026-Q3", date(2026, 1, 1), date(2026, 12, 31),
        LABOUR_SHARE, assignments, wages,
    )])
    assert engine.rate("99284", DOS, area="41860").allowed_amount == 655.20
