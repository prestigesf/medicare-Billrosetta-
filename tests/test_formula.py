"""The calculation, checked against arithmetic worked by hand.

The RVU and GPCI values here are illustrative fixtures, not CMS data. What is
being verified is that the formula composes correctly — each RVU adjusted by
its own GPCI, summed, then multiplied by the conversion factor, rounded once.
"""
import pytest

from pfs import (
    GPCI,
    MissingPracticeExpenseRVU,
    NotPriceableUnderPFS,
    RVUs,
    Setting,
    compute_allowed_amount,
    round_money,
)

# Illustrative fixture. Structure is real; the numbers are not CMS's.
CODE = RVUs(
    cpt_code="99214",
    work=1.92,
    practice_expense_facility=0.80,
    practice_expense_non_facility=1.73,
    malpractice=0.14,
    status_code="A",
)

# A locality with every index at 1.000 — national, unadjusted.
NATIONAL = GPCI(
    locality_id="00-00",
    locality_name="National (unadjusted)",
    work=1.000,
    practice_expense=1.000,
    malpractice=1.000,
)

# A high-cost locality, each index different so a mis-applied GPCI shows up.
HIGH_COST = GPCI(
    locality_id="01-05",
    locality_name="High cost",
    work=1.050,
    practice_expense=1.200,
    malpractice=0.500,
)

CF = 33.0000


def test_national_non_facility_matches_hand_calculation():
    # (1.92*1.0 + 1.73*1.0 + 0.14*1.0) * 33.00 = 3.79 * 33.00 = 125.07
    assert compute_allowed_amount(CODE, NATIONAL, CF, Setting.NON_FACILITY) == 125.07


def test_national_facility_uses_the_facility_pe_rvu():
    # (1.92 + 0.80 + 0.14) * 33.00 = 2.86 * 33.00 = 94.38
    assert compute_allowed_amount(CODE, NATIONAL, CF, Setting.FACILITY) == 94.38


def test_facility_and_non_facility_differ():
    """The setting is not cosmetic — it changes the amount."""
    facility = compute_allowed_amount(CODE, NATIONAL, CF, Setting.FACILITY)
    non_facility = compute_allowed_amount(CODE, NATIONAL, CF, Setting.NON_FACILITY)
    assert facility != non_facility


def test_each_rvu_is_adjusted_by_its_own_gpci():
    """Catches a GPCI applied to the wrong component.

    work 1.92*1.050 = 2.0160
    pe   1.73*1.200 = 2.0760
    mp   0.14*0.500 = 0.0700
    sum  4.1620 * 33.00 = 137.346 -> 137.35
    """
    assert compute_allowed_amount(CODE, HIGH_COST, CF, Setting.NON_FACILITY) == 137.35


def test_swapping_two_gpcis_changes_the_answer():
    """If the components were interchangeable this test would be meaningless."""
    swapped = GPCI(
        locality_id=HIGH_COST.locality_id,
        locality_name=HIGH_COST.locality_name,
        work=HIGH_COST.practice_expense,
        practice_expense=HIGH_COST.work,
        malpractice=HIGH_COST.malpractice,
    )
    assert compute_allowed_amount(CODE, swapped, CF, Setting.NON_FACILITY) != 137.35


def test_conversion_factor_scales_the_result():
    doubled = compute_allowed_amount(CODE, NATIONAL, CF * 2, Setting.NON_FACILITY)
    single = compute_allowed_amount(CODE, NATIONAL, CF, Setting.NON_FACILITY)
    assert doubled == pytest.approx(single * 2, abs=0.01)


def test_non_priceable_status_code_raises_rather_than_returning_zero():
    bundled = RVUs(
        cpt_code="99211",
        work=0.0,
        practice_expense_facility=0.0,
        practice_expense_non_facility=0.0,
        malpractice=0.0,
        status_code="B",
    )
    with pytest.raises(NotPriceableUnderPFS) as exc:
        compute_allowed_amount(bundled, NATIONAL, CF, Setting.NON_FACILITY)
    assert "bundled" in str(exc.value).lower()


def test_carrier_priced_code_raises():
    """'C' means the MAC sets the price — there is no national amount."""
    carrier_priced = RVUs(
        cpt_code="99199",
        work=0.0,
        practice_expense_facility=0.0,
        practice_expense_non_facility=0.0,
        malpractice=0.0,
        status_code="C",
    )
    with pytest.raises(NotPriceableUnderPFS):
        compute_allowed_amount(carrier_priced, NATIONAL, CF, Setting.NON_FACILITY)


def test_missing_pe_rvu_for_setting_raises_rather_than_substituting():
    """A code priced only in one setting must not borrow the other's PE RVU."""
    non_facility_only = RVUs(
        cpt_code="99999",
        work=1.00,
        practice_expense_facility=None,
        practice_expense_non_facility=2.00,
        malpractice=0.10,
        status_code="A",
    )
    with pytest.raises(MissingPracticeExpenseRVU):
        compute_allowed_amount(non_facility_only, NATIONAL, CF, Setting.FACILITY)

    assert compute_allowed_amount(
        non_facility_only, NATIONAL, CF, Setting.NON_FACILITY
    ) == 102.30


@pytest.mark.parametrize(
    "amount,expected",
    [
        (110.504, 110.50),
        (110.505, 110.51),  # half-up, not half-to-even
        (110.515, 110.52),
        (0.005, 0.01),
        (125.0, 125.00),
    ],
)
def test_money_rounds_half_up(amount, expected):
    assert round_money(amount) == expected


def test_rounding_happens_once_at_the_end():
    """Rounding components before summing would drift."""
    fractional = RVUs(
        cpt_code="12345",
        work=0.333,
        practice_expense_facility=0.333,
        practice_expense_non_facility=0.333,
        malpractice=0.333,
        status_code="A",
    )
    # (0.999) * 33.00 = 32.967 -> 32.97, not 33.00 from pre-rounded parts.
    assert compute_allowed_amount(fractional, NATIONAL, CF, Setting.FACILITY) == 32.97
