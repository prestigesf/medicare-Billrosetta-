"""Medicare Physician Fee Schedule rate calculation.

Computes the allowed amount for a CPT code in a locality on a date of service,
from CMS's published RVU, GPCI, and conversion-factor data.

No rate is ever invented. Every failure path raises a specific
`RateUnavailable` subclass explaining why no defensible number exists.
"""
from .engine import RateEngine
from .errors import (
    MissingPracticeExpenseRVU,
    NoFeeScheduleForDate,
    NotPriceableUnderPFS,
    RateUnavailable,
    UnknownCPTCode,
    UnknownLocality,
    UnmappedZipCode,
)
from .formula import compute_allowed_amount, round_money
from .models import (
    GPCI,
    FeeSchedulePeriod,
    RateResult,
    RVUs,
    Setting,
)

__all__ = [
    "RateEngine",
    "RateResult",
    "FeeSchedulePeriod",
    "RVUs",
    "GPCI",
    "Setting",
    "compute_allowed_amount",
    "round_money",
    "RateUnavailable",
    "UnknownCPTCode",
    "UnknownLocality",
    "UnmappedZipCode",
    "NoFeeScheduleForDate",
    "NotPriceableUnderPFS",
    "MissingPracticeExpenseRVU",
]
