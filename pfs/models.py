"""Data the fee-schedule calculation operates on.

Everything here is *loaded from CMS files*, not written into the code. The
conversion factor in particular is deliberately a field on FeeSchedulePeriod
rather than a module constant: it is republished annually, and a hardcoded
copy is a silent wrong answer the moment it changes.
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, Optional


class Setting(str, Enum):
    """Where the service was rendered.

    This changes the practice-expense RVU, and therefore the amount. There is
    deliberately no default — a caller that does not know the setting cannot
    get a rate, because guessing produces a confidently wrong benchmark.
    """

    FACILITY = "facility"
    NON_FACILITY = "non_facility"


# PFS status codes that carry a computable national amount.
#   A - active, separately payable
#   R - restricted coverage, but priced
#   T - paid only if no other services payable that day, but priced
PRICEABLE_STATUS_CODES = frozenset({"A", "R", "T"})

STATUS_CODE_MEANINGS = {
    "A": "active code",
    "R": "restricted coverage",
    "T": "injections, paid only when no other service is payable that day",
    "B": "bundled into another service",
    "C": "carrier-priced; the MAC sets the amount, there is no national rate",
    "E": "excluded from the physician fee schedule",
    "I": "not valid for Medicare purposes",
    "N": "non-covered service",
    "P": "bundled or excluded, no separate payment",
    "X": "statutory exclusion",
    # Present in the CY2026 release and carrying zero RVUs on every row. The
    # exact wording of their published definitions is not confirmed here, so
    # they are described by what the data shows rather than by a label taken
    # on faith. Both are non-priceable either way.
    "J": "no fee-schedule RVUs; observed only on anaesthesia-range codes, "
         "which are priced under a separate methodology",
    "M": "no fee-schedule RVUs; observed only on measurement-type codes",
}


def rvu_key(cpt_code: str, modifier: str = "") -> str:
    """Key for one priceable line: a code, optionally with its modifier.

    A CPT code alone is not unique in the RVU file. Imaging and similar
    services appear several times — once global, once as the professional
    component (modifier 26), once as the technical component (TC) — each with
    different RVUs. Keying on the code alone collides them.
    """
    code = cpt_code.upper().strip()
    mod = (modifier or "").upper().strip()
    return f"{code}-{mod}" if mod else code


@dataclass(frozen=True)
class RVUs:
    """Relative value units for one priceable line, from the PPRRVU file."""

    cpt_code: str
    work: float
    practice_expense_facility: Optional[float]
    practice_expense_non_facility: Optional[float]
    malpractice: float
    status_code: str
    modifier: str = ""

    @property
    def key(self) -> str:
        return rvu_key(self.cpt_code, self.modifier)

    def practice_expense_for(self, setting: Setting) -> Optional[float]:
        if setting is Setting.FACILITY:
            return self.practice_expense_facility
        return self.practice_expense_non_facility

    @property
    def is_priceable(self) -> bool:
        return self.status_code.upper() in PRICEABLE_STATUS_CODES

    @property
    def status_meaning(self) -> str:
        return STATUS_CODE_MEANINGS.get(self.status_code.upper(), "unrecognised status code")


@dataclass(frozen=True)
class GPCI:
    """Geographic practice cost indices for one MAC locality."""

    locality_id: str
    locality_name: str
    work: float
    practice_expense: float
    malpractice: float


@dataclass(frozen=True)
class FeeSchedulePeriod:
    """One published edition of the fee schedule, with its own effective dates.

    Keeping periods separate is what makes a rate reproducible: an appeal on a
    2024 date of service must be priced against the 2024 schedule.
    """

    period_id: str
    effective_start: date
    effective_end: date
    conversion_factor: float
    rvus: Dict[str, RVUs]
    gpcis: Dict[str, GPCI]

    def covers(self, service_date: date) -> bool:
        return self.effective_start <= service_date <= self.effective_end


@dataclass(frozen=True)
class RateResult:
    """A computed allowed amount, with everything needed to defend it.

    The component breakdown is not decoration. If a claims administrator
    disputes the figure, this is the arithmetic that answers them.
    """

    cpt_code: str
    locality_id: str
    locality_name: str
    setting: Setting
    service_date: date
    period_id: str
    conversion_factor: float
    work_component: float
    practice_expense_component: float
    malpractice_component: float
    allowed_amount: float

    @property
    def source(self) -> str:
        return f"cms-pfs:{self.period_id}:{self.locality_id}"

    def explain(self) -> str:
        """One-line derivation, suitable for putting in front of a human."""
        return (
            f"CPT {self.cpt_code}, {self.locality_name} ({self.locality_id}), "
            f"{self.setting.value}, DOS {self.service_date.isoformat()}: "
            f"({self.work_component:.4f} + {self.practice_expense_component:.4f} + "
            f"{self.malpractice_component:.4f}) x {self.conversion_factor} "
            f"= ${self.allowed_amount:.2f} [{self.period_id}]"
        )
