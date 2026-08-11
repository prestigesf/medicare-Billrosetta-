"""The physician fee schedule calculation.

    allowed = [(work RVU x work GPCI)
             + (PE RVU x PE GPCI)
             + (MP RVU x MP GPCI)] x conversion factor

Each RVU is adjusted by its own geographic index before the sum — the three
GPCIs are not interchangeable, and applying one to the wrong component is a
silent error that produces a plausible number.

Money is rounded once, at the end, half-up. Python's built-in round() is
half-to-even, which would round $110.505 down to $110.50 and $110.515 down to
$110.51 — inconsistent in a way nobody wants to explain in an appeal.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .errors import MissingPracticeExpenseRVU, NotPriceableUnderPFS
from .models import GPCI, RVUs, Setting


def round_money(amount: float) -> float:
    """Round to cents, half-up."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def geographic_components(rvus: RVUs, gpci: GPCI, setting: Setting):
    """Return the three GPCI-adjusted RVU components, unrounded.

    Raises rather than substituting a value when the practice-expense RVU for
    the requested setting is missing.
    """
    if not rvus.is_priceable:
        raise NotPriceableUnderPFS(rvus.cpt_code, rvus.status_code, rvus.status_meaning)

    pe_rvu: Optional[float] = rvus.practice_expense_for(setting)
    if pe_rvu is None:
        raise MissingPracticeExpenseRVU(
            f"CPT {rvus.cpt_code} has no {setting.value} practice-expense RVU; "
            "it is not priced in that setting."
        )

    return (
        rvus.work * gpci.work,
        pe_rvu * gpci.practice_expense,
        rvus.malpractice * gpci.malpractice,
    )


def compute_allowed_amount(
    rvus: RVUs,
    gpci: GPCI,
    conversion_factor: float,
    setting: Setting,
) -> float:
    """The Medicare allowed amount for one code in one locality."""
    work, practice_expense, malpractice = geographic_components(rvus, gpci, setting)
    return round_money((work + practice_expense + malpractice) * conversion_factor)
