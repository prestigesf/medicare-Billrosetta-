"""Price a whole bill at once.

Takes billed lines — the way they appear on a statement — and returns each one
priced against Medicare, with the arithmetic attached and a reason wherever a
line could not be priced.

Two rules carried over from the engine:

- One bad line never fails the batch. It is returned unpriced, with the reason
  named, alongside the lines that did price.
- Nothing is estimated. A line with no defensible benchmark reports that it
  has none rather than carrying a plausible number into a demand letter.
"""
import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from .engine import RateEngine
from .errors import RateUnavailable
from .locality import AmbiguousLocality, LocalityDirectory, UnknownState
from .models import Setting

# Where the materiality policy lives. It is a business rule, not CMS data, and
# not a rate — but it is still a number that changes an output, so it is kept
# as data rather than written into the code.
POLICY_FILE = Path(__file__).resolve().parent.parent / "policy" / "materiality.json"


def load_materiality_multiple(path=None) -> float:
    """The multiple above which a charge is called out.

    A line is flagged when the charge exceeds the Medicare allowed amount by
    more than this multiple. Below it the difference is still reported, just
    not framed as a finding.
    """
    source = Path(path) if path else POLICY_FILE
    return float(json.loads(source.read_text())["materiality_multiple"])


MATERIALITY_MULTIPLE = load_materiality_multiple()

# Accepted spellings for the setting column.
SETTING_ALIASES = {
    "facility": Setting.FACILITY,
    "f": Setting.FACILITY,
    "inpatient": Setting.FACILITY,
    "hospital": Setting.FACILITY,
    "non-facility": Setting.NON_FACILITY,
    "non_facility": Setting.NON_FACILITY,
    "nonfacility": Setting.NON_FACILITY,
    "nf": Setting.NON_FACILITY,
    "office": Setting.NON_FACILITY,
}

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y")


class BillFormatError(Exception):
    """The bill file could not be read."""


@dataclass(frozen=True)
class BilledLine:
    """One line as it appears on the statement."""

    line_number: int
    cpt_code: str
    charged_amount: float
    service_date: date
    setting: Setting
    modifier: str = ""
    locality_id: Optional[str] = None
    state: Optional[str] = None
    description: str = ""


@dataclass(frozen=True)
class PricedLine:
    """A billed line with its benchmark, or the reason it has none."""

    billed: BilledLine
    allowed_amount: Optional[float] = None
    locality_id: Optional[str] = None
    locality_name: Optional[str] = None
    derivation: Optional[str] = None
    unavailable_reason: Optional[str] = None
    rate_source: Optional[str] = None

    @property
    def priced(self) -> bool:
        return self.allowed_amount is not None

    @property
    def variance(self) -> Optional[float]:
        """Charge minus the Medicare allowed amount. Negative means under."""
        if self.allowed_amount is None:
            return None
        return round(self.billed.charged_amount - self.allowed_amount, 2)

    @property
    def exact_multiple_of_medicare(self) -> Optional[float]:
        """Unrounded ratio of charge to benchmark."""
        if not self.allowed_amount:
            return None
        return self.billed.charged_amount / self.allowed_amount

    @property
    def multiple_of_medicare(self) -> Optional[float]:
        """Ratio rounded for display."""
        exact = self.exact_multiple_of_medicare
        return None if exact is None else round(exact, 2)

    @property
    def flagged(self) -> bool:
        """Materially above the benchmark, and therefore worth raising.

        Compares the unrounded ratio. Comparing the displayed value would let
        a charge at 1.504x round down to 1.50 and slip under the threshold.
        """
        exact = self.exact_multiple_of_medicare
        return exact is not None and exact > MATERIALITY_MULTIPLE


@dataclass
class BillPricing:
    """Every line of a bill, priced."""

    lines: List[PricedLine] = field(default_factory=list)

    @property
    def priced_lines(self) -> List[PricedLine]:
        return [line for line in self.lines if line.priced]

    @property
    def unpriced_lines(self) -> List[PricedLine]:
        return [line for line in self.lines if not line.priced]

    @property
    def flagged_lines(self) -> List[PricedLine]:
        return [line for line in self.lines if line.flagged]

    @property
    def total_charged(self) -> float:
        return round(sum(line.billed.charged_amount for line in self.lines), 2)

    @property
    def total_charged_on_priced_lines(self) -> float:
        return round(sum(line.billed.charged_amount for line in self.priced_lines), 2)

    @property
    def total_allowed(self) -> float:
        return round(sum(line.allowed_amount for line in self.priced_lines), 2)

    @property
    def total_variance(self) -> float:
        """Only over priced lines — an unpriced line contributes nothing."""
        return round(self.total_charged_on_priced_lines - self.total_allowed, 2)

    @property
    def total_variance_on_flagged(self) -> float:
        return round(sum(line.variance or 0 for line in self.flagged_lines), 2)

    def summary(self) -> Dict[str, object]:
        return {
            "lines": len(self.lines),
            "priced": len(self.priced_lines),
            "unpriced": len(self.unpriced_lines),
            "flagged": len(self.flagged_lines),
            "total_charged": self.total_charged,
            "total_charged_on_priced_lines": self.total_charged_on_priced_lines,
            "total_medicare_allowed": self.total_allowed,
            "total_variance": self.total_variance,
            "total_variance_on_flagged_lines": self.total_variance_on_flagged,
            "materiality_multiple": MATERIALITY_MULTIPLE,
        }


def parse_setting(text: str) -> Setting:
    key = (text or "").strip().lower().replace(" ", "_")
    try:
        return SETTING_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"setting {text!r} not recognised; use one of "
            f"{sorted(set(SETTING_ALIASES))}"
        ) from None


def parse_date(text: str) -> date:
    raw = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"date {text!r} not recognised; use YYYY-MM-DD")


def parse_money(text: str) -> float:
    cleaned = (text or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        raise ValueError("charged amount is blank")
    return float(cleaned)


def read_bill(path: Union[str, Path]) -> List[BilledLine]:
    """Read a billed-lines CSV.

    Required columns: cpt_code, charged_amount, date_of_service, setting.
    Location: either locality_id, or state (resolved when unambiguous).
    Optional: modifier, description.
    """
    path = Path(path)
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        raise BillFormatError(f"{path.name}: no billed lines found")

    headers = {(h or "").strip().lower() for h in rows[0]}
    required = {"cpt_code", "charged_amount", "date_of_service", "setting"}
    missing = required - headers
    if missing:
        raise BillFormatError(
            f"{path.name}: missing required column(s): {sorted(missing)}; "
            f"found {sorted(headers)}"
        )
    if not ({"locality_id", "state"} & headers):
        raise BillFormatError(
            f"{path.name}: needs either a locality_id or a state column"
        )

    def cell(row, name):
        for key, value in row.items():
            if (key or "").strip().lower() == name:
                return (value or "").strip()
        return ""

    lines, problems = [], []
    for offset, row in enumerate(rows, start=2):
        code = cell(row, "cpt_code").upper()
        if not code:
            continue
        try:
            lines.append(
                BilledLine(
                    line_number=offset,
                    cpt_code=code,
                    modifier=cell(row, "modifier"),
                    charged_amount=parse_money(cell(row, "charged_amount")),
                    service_date=parse_date(cell(row, "date_of_service")),
                    setting=parse_setting(cell(row, "setting")),
                    locality_id=cell(row, "locality_id") or None,
                    state=cell(row, "state") or None,
                    description=cell(row, "description"),
                )
            )
        except ValueError as exc:
            problems.append(f"line {offset}, CPT {code}: {exc}")

    if problems:
        raise BillFormatError(f"{path.name}:\n  " + "\n  ".join(problems))
    if not lines:
        raise BillFormatError(f"{path.name}: no billed lines found")
    return lines


def price_bill(
    billed_lines: Sequence[BilledLine],
    engine: RateEngine,
    directory: Optional[LocalityDirectory] = None,
) -> BillPricing:
    """Price every line, carrying reasons instead of failing the batch."""
    pricing = BillPricing()

    for billed in billed_lines:
        locality_id = billed.locality_id

        if not locality_id:
            if directory is None:
                pricing.lines.append(
                    PricedLine(
                        billed=billed,
                        unavailable_reason=(
                            "no locality_id given and no locality directory available"
                        ),
                    )
                )
                continue
            try:
                locality_id = directory.for_state(billed.state or "")
            except (AmbiguousLocality, UnknownState) as exc:
                pricing.lines.append(
                    PricedLine(billed=billed, unavailable_reason=str(exc))
                )
                continue

        try:
            result = engine.rate_for_locality(
                billed.cpt_code,
                locality_id,
                billed.setting,
                billed.service_date,
                modifier=billed.modifier,
            )
        except RateUnavailable as exc:
            pricing.lines.append(
                PricedLine(
                    billed=billed,
                    locality_id=locality_id,
                    unavailable_reason=str(exc),
                )
            )
            continue

        pricing.lines.append(
            PricedLine(
                billed=billed,
                allowed_amount=result.allowed_amount,
                locality_id=result.locality_id,
                locality_name=result.locality_name,
                derivation=result.explain(),
                rate_source=result.source,
            )
        )

    return pricing


PRICED_COLUMNS = [
    "line_number", "cpt_code", "modifier", "description", "date_of_service",
    "setting", "locality_id", "locality_name", "charged_amount",
    "medicare_allowed", "variance", "multiple_of_medicare", "flagged",
    "status", "reason", "rate_source", "derivation",
]


def write_priced_csv(pricing: BillPricing, path: Union[str, Path]) -> Path:
    """Write the priced bill out, one row per billed line."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRICED_COLUMNS)
        writer.writeheader()
        for line in pricing.lines:
            writer.writerow({
                "line_number": line.billed.line_number,
                "cpt_code": line.billed.cpt_code,
                "modifier": line.billed.modifier,
                "description": line.billed.description,
                "date_of_service": line.billed.service_date.isoformat(),
                "setting": line.billed.setting.value,
                "locality_id": line.locality_id or "",
                "locality_name": line.locality_name or "",
                "charged_amount": f"{line.billed.charged_amount:.2f}",
                "medicare_allowed": "" if line.allowed_amount is None else f"{line.allowed_amount:.2f}",
                "variance": "" if line.variance is None else f"{line.variance:.2f}",
                "multiple_of_medicare": "" if line.multiple_of_medicare is None else f"{line.multiple_of_medicare:.2f}",
                "flagged": "yes" if line.flagged else "no",
                "status": "priced" if line.priced else "no benchmark",
                "reason": line.unavailable_reason or "",
                "rate_source": line.rate_source or "",
                "derivation": line.derivation or "",
            })
    return path
