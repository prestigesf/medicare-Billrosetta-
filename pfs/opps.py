"""Outpatient Prospective Payment System — hospital facility pricing.

The physician fee schedule pays the clinician. OPPS pays the hospital for the
room, the equipment and the staff, and it is the larger share of a plan's
outpatient spend. It is a different system, not a variant of PFS:

- Payment is by **APC** (ambulatory payment classification), a group a code is
  assigned to, not by relative value units.
- CMS publishes the national unadjusted payment rate per code in **Addendum B**
  alongside a **status indicator** that decides whether the line is paid at all.
- Geography is applied differently. The labour-related share of the payment is
  adjusted by the hospital's wage index; the remainder is not:

      payment = national x [(labour share x wage index) + (1 - labour share)]

  The labour share is published policy, so it is data here, not a constant.

Payability is led by the file. A line prices when Addendum B carries a rate
for it and its status indicator is one that pays separately; otherwise the
indicator is reported and nothing is computed. That keeps the same rule the
rest of this package follows — no number without a basis for it.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Mapping, Optional

from .errors import RateUnavailable

# Status indicators that carry a separately payable amount. Anything else —
# packaged, inpatient-only, paid under another schedule, not billable — has no
# separate OPPS payment, whatever else the row contains.
SEPARATELY_PAYABLE_INDICATORS = frozenset({
    "S",   # significant procedure, no multiple-procedure discount
    "T",   # significant procedure, multiple-procedure reduction applies
    "V",   # clinic or emergency department visit
    "J1",  # comprehensive APC, single payment for the encounter
    "J2",  # hospital part B services under specific circumstances
    "P",   # partial hospitalisation
    "R",   # blood and blood products
    "U",   # brachytherapy source
    "G",   # pass-through drug or biological
    "K",   # non-pass-through drug, biological or radiopharmaceutical
})

INDICATOR_MEANINGS = {
    "N": "packaged into the payment for another service; no separate payment",
    "Q1": "conditionally packaged — paid separately only when billed alone",
    "Q2": "conditionally packaged — paid separately only when billed alone",
    "Q3": "may be paid through a composite APC",
    "Q4": ("conditionally packaged laboratory test — paid under the clinical "
           "laboratory fee schedule when billed alone, packaged otherwise"),
    "E1": "not payable by Medicare",
    "E2": "not payable under OPPS when submitted on an outpatient claim",
    "B": "not appropriate for billing under OPPS",
    "C": "inpatient-only procedure; not paid under OPPS",
    "A": "paid under a fee schedule other than OPPS",
    "M": "not billable to the fiscal intermediary or MAC",
    "Y": "non-implantable durable medical equipment; paid under the DME schedule",
}


class NotPayableUnderOPPS(RateUnavailable):
    """The code exists in Addendum B but carries no separate OPPS payment."""

    def __init__(self, hcpcs: str, indicator: str, meaning: str):
        self.hcpcs = hcpcs
        self.indicator = indicator
        self.meaning = meaning
        super().__init__(
            f"HCPCS {hcpcs} has OPPS status indicator '{indicator}' ({meaning}); "
            "no separate outpatient payment amount exists for it."
        )


class UnknownHCPCS(RateUnavailable):
    """The code is not in the loaded Addendum B."""


class UnknownWageIndex(RateUnavailable):
    """No wage index loaded for that provider or area."""


class NoAddendumForDate(RateUnavailable):
    """No published Addendum B covers this date of service."""


def round_money(amount: float) -> float:
    """Round to cents, half-up, once — the same rule the PFS side uses."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class APCAssignment:
    """One row of Addendum B."""

    hcpcs: str
    status_indicator: str
    apc: str = ""
    description: str = ""
    national_rate: Optional[float] = None
    modifier: str = ""

    @property
    def key(self) -> str:
        mod = self.modifier.upper().strip()
        code = self.hcpcs.upper().strip()
        return f"{code}-{mod}" if mod else code

    @property
    def separately_payable(self) -> bool:
        return (
            self.status_indicator.upper().strip() in SEPARATELY_PAYABLE_INDICATORS
            and self.national_rate is not None
        )

    @property
    def indicator_meaning(self) -> str:
        indicator = self.status_indicator.upper().strip()
        if indicator in SEPARATELY_PAYABLE_INDICATORS:
            return "separately payable under OPPS"
        return INDICATOR_MEANINGS.get(indicator, "no separate OPPS payment")


@dataclass(frozen=True)
class WageIndex:
    """A hospital's wage index, by CBSA or by provider number."""

    area: str
    area_name: str
    index: float


@dataclass(frozen=True)
class OPPSPeriod:
    """One published edition of Addendum B, with its effective dates."""

    period_id: str
    effective_start: date
    effective_end: date
    labour_share: float
    assignments: Dict[str, APCAssignment]
    wage_indices: Mapping[str, WageIndex]

    def covers(self, service_date: date) -> bool:
        return self.effective_start <= service_date <= self.effective_end


@dataclass(frozen=True)
class OPPSResult:
    """A computed outpatient payment, with everything needed to defend it."""

    hcpcs: str
    modifier: str
    apc: str
    status_indicator: str
    service_date: date
    period_id: str
    national_rate: float
    labour_share: float
    wage_index: Optional[float]
    area: Optional[str]
    area_name: Optional[str]
    allowed_amount: float

    @property
    def source(self) -> str:
        area = self.area or "national"
        return f"cms-opps:{self.period_id}:{area}"

    def explain(self) -> str:
        if self.wage_index is None:
            return (
                f"HCPCS {self.hcpcs} (APC {self.apc}, status {self.status_indicator}), "
                f"DOS {self.service_date.isoformat()}: national unadjusted "
                f"${self.national_rate:.2f} = ${self.allowed_amount:.2f} "
                f"[{self.period_id}, no wage index applied]"
            )
        labour = self.labour_share
        return (
            f"HCPCS {self.hcpcs} (APC {self.apc}, status {self.status_indicator}), "
            f"{self.area_name} ({self.area}), DOS {self.service_date.isoformat()}: "
            f"${self.national_rate:.2f} x [({labour:.4f} x {self.wage_index:.4f}) "
            f"+ {1 - labour:.4f}] = ${self.allowed_amount:.2f} [{self.period_id}]"
        )


def wage_adjust(national_rate: float, labour_share: float, wage_index: float) -> float:
    """Apply the wage index to the labour-related share only."""
    return national_rate * ((labour_share * wage_index) + (1 - labour_share))


class OPPSEngine:
    """What Medicare allowed a hospital outpatient department, and why not.

    Mirrors RateEngine deliberately: same period handling, same refusal
    discipline, same provenance on every result, so an audit can hold PFS and
    OPPS lines side by side without special-casing either.
    """

    def __init__(self, periods: Iterable[OPPSPeriod]):
        self._periods: List[OPPSPeriod] = sorted(periods, key=lambda p: p.effective_start)
        for earlier, later in zip(self._periods, self._periods[1:]):
            if later.effective_start <= earlier.effective_end:
                raise ValueError(
                    f"OPPS periods overlap: {earlier.period_id} ends "
                    f"{earlier.effective_end} but {later.period_id} starts "
                    f"{later.effective_start}."
                )

    def period_for(self, service_date: date) -> OPPSPeriod:
        for period in self._periods:
            if period.covers(service_date):
                return period
        raise NoAddendumForDate(
            f"No loaded Addendum B covers {service_date.isoformat()}. "
            f"Loaded: {[p.period_id for p in self._periods] or 'none'}."
        )

    def rate(
        self,
        hcpcs: str,
        service_date: date,
        area: Optional[str] = None,
        modifier: str = "",
    ) -> OPPSResult:
        """The outpatient allowed amount, or a specific reason there isn't one.

        Without an area the national unadjusted rate is returned and the
        result says so — an unadjusted figure labelled as such is honest; one
        presented as local is not.
        """
        period = self.period_for(service_date)
        code = hcpcs.upper().strip()
        mod = (modifier or "").upper().strip()
        key = f"{code}-{mod}" if mod else code

        assignment = period.assignments.get(key) or period.assignments.get(code)
        if assignment is None:
            raise UnknownHCPCS(
                f"HCPCS {key} is not in the {period.period_id} Addendum B."
            )
        if not assignment.separately_payable:
            raise NotPayableUnderOPPS(
                key, assignment.status_indicator, assignment.indicator_meaning
            )

        national = assignment.national_rate
        wage_index_value = None
        area_name = None

        if area:
            entry = period.wage_indices.get(area.strip())
            if entry is None:
                raise UnknownWageIndex(
                    f"No wage index loaded for area {area!r} in {period.period_id}."
                )
            wage_index_value = entry.index
            area_name = entry.area_name
            allowed = wage_adjust(national, period.labour_share, wage_index_value)
        else:
            allowed = national

        return OPPSResult(
            hcpcs=code,
            modifier=mod,
            apc=assignment.apc,
            status_indicator=assignment.status_indicator,
            service_date=service_date,
            period_id=period.period_id,
            national_rate=national,
            labour_share=period.labour_share,
            wage_index=wage_index_value,
            area=area.strip() if area else None,
            area_name=area_name,
            allowed_amount=round_money(allowed),
        )


# --- loading Addendum B -------------------------------------------------------

def load_addendum_b(path, colmap) -> Dict[str, APCAssignment]:
    """Read Addendum B into {code: APCAssignment}.

    Column layout is configuration, as it is for every other CMS file, because
    the release format shifts between quarters. Required fields are the code
    and the status indicator; APC, description, payment rate and modifier are
    optional so a release that omits one still loads.

    A blank payment rate stays None. Packaged and inpatient-only codes are
    published with no rate, and turning that into 0.00 would be a payment
    amount rather than the absence of one.
    """
    from pathlib import Path

    from .loaders import FileFormatError, _number, _rows

    path = Path(path)
    colmap.require("hcpcs", "status_indicator")

    table: Dict[str, APCAssignment] = {}
    problems: List[str] = []

    for line_no, raw in _rows(path, colmap):
        code = (raw.get("hcpcs") or "").upper().strip()
        if not code:
            continue
        indicator = (raw.get("status_indicator") or "").upper().strip()
        if not indicator:
            problems.append(f"line {line_no}, {code}: blank status indicator")
            continue
        try:
            rate_text = (raw.get("national_rate") or "").strip()
            entry = APCAssignment(
                hcpcs=code,
                modifier=(raw.get("modifier") or "").strip(),
                status_indicator=indicator,
                apc=(raw.get("apc") or "").strip(),
                description=(raw.get("description") or "").strip(),
                national_rate=_number(rate_text) if rate_text else None,
            )
        except ValueError as exc:
            problems.append(f"line {line_no}, {code}: {exc}")
            continue

        if entry.key in table and table[entry.key] != entry:
            problems.append(f"line {line_no}, {entry.key}: conflicting duplicate row")
            continue
        table[entry.key] = entry

    if problems:
        raise FileFormatError(path, problems)
    if not table:
        raise FileFormatError(path, ["no Addendum B rows parsed"])
    return table


def load_wage_indices(path, colmap) -> Dict[str, WageIndex]:
    """Read a wage index file into {area: WageIndex}."""
    from pathlib import Path

    from .loaders import FileFormatError, _number, _rows

    path = Path(path)
    colmap.require("area", "wage_index")

    table: Dict[str, WageIndex] = {}
    problems: List[str] = []

    for line_no, raw in _rows(path, colmap):
        area = (raw.get("area") or "").strip()
        if not area:
            continue
        try:
            entry = WageIndex(
                area=area,
                area_name=(raw.get("area_name") or area).strip(),
                index=_number(raw["wage_index"]),
            )
        except ValueError as exc:
            problems.append(f"line {line_no}, area {area}: {exc}")
            continue
        if area in table and table[area] != entry:
            problems.append(f"line {line_no}, area {area}: conflicting duplicate row")
            continue
        table[area] = entry

    if problems:
        raise FileFormatError(path, problems)
    if not table:
        raise FileFormatError(path, ["no wage index rows parsed"])
    return table
