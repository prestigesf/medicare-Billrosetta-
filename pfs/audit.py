"""Audit a claims portfolio against Medicare.

The employer question is not "was this bill high." It is "across a quarter of
paid claims, where did the plan pay above the benchmark, how much, and with
whom does it concentrate."

Two things separate this from pricing one bill.

**Paid, not billed.** A self-insured plan's exposure is what it paid after the
network discount, not what the provider charged. Variance is measured against
the paid amount; the billed amount is carried for context only.

**Coverage is a headline number, not a footnote.** An audit that silently
benchmarks a third of the spend and reports a total is worse than useless to
a fiduciary — it understates exposure while looking authoritative. Every
summary here leads with how much of the dollar volume could be benchmarked at
all, and every unpriceable line carries its reason.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from .engine import RateEngine
from .errors import RateUnavailable
from .locality import AmbiguousLocality, LocalityDirectory, UnknownState
from .models import Setting

# How many bad rows to list before truncating a claims-file error.
MAX_PROBLEMS_SHOWN = 20

# Rounding for reported shares: coverage and concentration are fractions, kept
# to four places so a percentage renders exactly.
SHARE_PRECISION = 4

# Money is rounded to cents wherever it is aggregated.
CENTS = 2

# Service families, by the HCPCS ranges CMS itself organises the schedule
# around. Used for grouping only — never for pricing.
SERVICE_CATEGORIES = (
    ("Evaluation & management", "99201", "99499"),
    ("Anesthesia", "00100", "01999"),
    ("Surgery", "10004", "69990"),
    ("Radiology", "70010", "79999"),
    ("Pathology & laboratory", "80047", "89398"),
    ("Medicine & therapy", "90281", "99199"),
)


def categorise(cpt_code: str) -> str:
    code = (cpt_code or "").upper().strip()
    if not code[:5].isdigit():
        return "Other / HCPCS level II"
    for name, low, high in SERVICE_CATEGORIES:
        if low <= code[:5] <= high:
            return name
    return "Other / HCPCS level II"


@dataclass(frozen=True)
class ClaimLine:
    """One adjudicated claim line as a plan's claims extract carries it."""

    line_number: int
    cpt_code: str
    service_date: date
    paid_amount: float
    setting: Setting
    modifier: str = ""
    units: int = 1
    billed_amount: Optional[float] = None
    provider: str = ""
    claim_id: str = ""
    locality_id: Optional[str] = None
    state: Optional[str] = None
    revenue_code: str = ""


@dataclass(frozen=True)
class AuditedLine:
    """A claim line with its benchmark, or the reason it has none."""

    claim: ClaimLine
    benchmark: Optional[float] = None
    locality_name: Optional[str] = None
    derivation: Optional[str] = None
    rate_source: Optional[str] = None
    unavailable_reason: Optional[str] = None

    @property
    def benchmarked(self) -> bool:
        return self.benchmark is not None

    @property
    def variance(self) -> Optional[float]:
        """Paid minus benchmark. Negative means the plan paid under Medicare."""
        if self.benchmark is None:
            return None
        return round(self.claim.paid_amount - self.benchmark, CENTS)

    @property
    def multiple_of_medicare(self) -> Optional[float]:
        if not self.benchmark:
            return None
        return round(self.claim.paid_amount / self.benchmark, CENTS)

    @property
    def category(self) -> str:
        return categorise(self.claim.cpt_code)


@dataclass
class Grouping:
    """One row of a rollup: a provider, a category, or a month."""

    key: str
    lines: int = 0
    benchmarked_lines: int = 0
    paid: float = 0.0
    benchmarked_paid: float = 0.0
    benchmark: float = 0.0

    @property
    def variance(self) -> float:
        return round(self.benchmarked_paid - self.benchmark, CENTS)

    @property
    def multiple(self) -> Optional[float]:
        if not self.benchmark:
            return None
        return round(self.benchmarked_paid / self.benchmark, CENTS)

    @property
    def coverage(self) -> float:
        """Share of this group's paid dollars that could be benchmarked."""
        if not self.paid:
            return 0.0
        return round(self.benchmarked_paid / self.paid, SHARE_PRECISION)


@dataclass
class PortfolioAudit:
    """Every line audited, with the rollups a plan sponsor actually reads."""

    lines: List[AuditedLine] = field(default_factory=list)

    # -- totals ---------------------------------------------------------------

    @property
    def benchmarked_lines(self) -> List[AuditedLine]:
        return [line for line in self.lines if line.benchmarked]

    @property
    def unbenchmarked_lines(self) -> List[AuditedLine]:
        return [line for line in self.lines if not line.benchmarked]

    @property
    def total_paid(self) -> float:
        return round(sum(line.claim.paid_amount for line in self.lines), CENTS)

    @property
    def benchmarked_paid(self) -> float:
        return round(sum(line.claim.paid_amount for line in self.benchmarked_lines), CENTS)

    @property
    def total_benchmark(self) -> float:
        return round(sum(line.benchmark for line in self.benchmarked_lines), CENTS)

    @property
    def total_variance(self) -> float:
        """Only across benchmarked dollars. Never inferred onto the rest."""
        return round(self.benchmarked_paid - self.total_benchmark, CENTS)

    @property
    def coverage(self) -> float:
        """Share of paid dollars that could be benchmarked at all.

        The number a fiduciary needs first: a variance figure covering a third
        of the spend understates exposure while sounding authoritative.
        """
        if not self.total_paid:
            return 0.0
        return round(self.benchmarked_paid / self.total_paid, SHARE_PRECISION)

    @property
    def overall_multiple(self) -> Optional[float]:
        if not self.total_benchmark:
            return None
        return round(self.benchmarked_paid / self.total_benchmark, CENTS)

    # -- rollups --------------------------------------------------------------

    def _group(self, key_of) -> List[Grouping]:
        groups: Dict[str, Grouping] = defaultdict(lambda: Grouping(key=""))
        for line in self.lines:
            key = key_of(line)
            group = groups[key]
            group.key = key
            group.lines += 1
            group.paid += line.claim.paid_amount
            if line.benchmarked:
                group.benchmarked_lines += 1
                group.benchmarked_paid += line.claim.paid_amount
                group.benchmark += line.benchmark
        for group in groups.values():
            group.paid = round(group.paid, CENTS)
            group.benchmarked_paid = round(group.benchmarked_paid, CENTS)
            group.benchmark = round(group.benchmark, CENTS)
        return sorted(groups.values(), key=lambda g: g.variance, reverse=True)

    def by_provider(self) -> List[Grouping]:
        return self._group(lambda line: line.claim.provider or "(unnamed provider)")

    def by_category(self) -> List[Grouping]:
        return self._group(lambda line: line.category)

    def by_month(self) -> List[Grouping]:
        rows = self._group(lambda line: line.claim.service_date.strftime("%Y-%m"))
        return sorted(rows, key=lambda g: g.key)

    def concentration(self, top: int = 5) -> dict:
        """How much of the variance sits with a handful of providers."""
        providers = [g for g in self.by_provider() if g.variance > 0]
        total = sum(g.variance for g in providers)
        head = providers[:top]
        return {
            "providers_with_variance": len(providers),
            "top": [(g.key, g.variance) for g in head],
            "share_in_top": round(sum(g.variance for g in head) / total, SHARE_PRECISION) if total else 0.0,
        }

    def reasons(self) -> List[tuple]:
        """Why the unbenchmarked dollars could not be benchmarked, by size."""
        totals: Dict[str, List[float]] = defaultdict(lambda: [0, 0.0])
        for line in self.unbenchmarked_lines:
            reason = (line.unavailable_reason or "unknown").split(";")[0].split(".")[0]
            totals[reason][0] += 1
            totals[reason][1] += line.claim.paid_amount
        return sorted(
            ((reason, count, round(paid, CENTS)) for reason, (count, paid) in totals.items()),
            key=lambda row: row[2],
            reverse=True,
        )

    def summary(self) -> dict:
        return {
            "lines": len(self.lines),
            "benchmarked_lines": len(self.benchmarked_lines),
            "total_paid": self.total_paid,
            "benchmarked_paid": self.benchmarked_paid,
            "coverage_of_paid_dollars": self.coverage,
            "total_benchmark": self.total_benchmark,
            "total_variance": self.total_variance,
            "overall_multiple_of_medicare": self.overall_multiple,
        }


def audit_claims(
    claims: Sequence[ClaimLine],
    engine: RateEngine,
    directory: Optional[LocalityDirectory] = None,
) -> PortfolioAudit:
    """Benchmark every claim line, carrying reasons rather than dropping lines."""
    audit = PortfolioAudit()

    for claim in claims:
        # A revenue code means the hospital billed for its own facility, which
        # is paid under OPPS or DRGs. Saying so is not the same as failing.
        if claim.revenue_code:
            audit.lines.append(AuditedLine(
                claim=claim,
                unavailable_reason=(
                    f"Facility charge (revenue code {claim.revenue_code}); paid "
                    "under OPPS or DRGs, not the physician fee schedule"
                ),
            ))
            continue

        locality_id = claim.locality_id
        if not locality_id:
            if directory is None:
                audit.lines.append(AuditedLine(
                    claim=claim,
                    unavailable_reason="No locality given and no locality directory loaded",
                ))
                continue
            try:
                locality_id = directory.for_state(claim.state or "")
            except (AmbiguousLocality, UnknownState) as exc:
                audit.lines.append(AuditedLine(claim=claim, unavailable_reason=str(exc)))
                continue

        try:
            result = engine.rate_for_locality(
                claim.cpt_code, locality_id, claim.setting,
                claim.service_date, modifier=claim.modifier,
            )
        except RateUnavailable as exc:
            audit.lines.append(AuditedLine(claim=claim, unavailable_reason=str(exc)))
            continue

        # Units scale the benchmark: four units of therapy are compared
        # against four units of Medicare.
        audit.lines.append(AuditedLine(
            claim=claim,
            benchmark=round(result.allowed_amount * max(claim.units, 1), CENTS),
            locality_name=result.locality_name,
            derivation=result.explain(),
            rate_source=result.source,
        ))

    return audit


# --- reading a claims extract ------------------------------------------------

CLAIM_FIELDS = (
    "cpt_code", "service_date", "paid_amount", "setting",
    "modifier", "units", "billed_amount", "provider", "claim_id",
    "locality_id", "state", "revenue_code",
)

REQUIRED_CLAIM_FIELDS = ("cpt_code", "service_date", "paid_amount")


class ClaimsFormatError(Exception):
    """The claims extract could not be read."""


def read_claims(path, colmap) -> List[ClaimLine]:
    """Read a claims extract into ClaimLines using a declared ColumnMap.

    Extracts differ by TPA, so the column mapping is configuration exactly as
    it is for the CMS files. Nothing here assumes a particular vendor layout.

    Setting defaults to facility when a revenue code is present and
    non-facility otherwise — the two are the same distinction seen from
    different sides of the claim.
    """
    from pathlib import Path

    from .bulk import parse_date, parse_money, parse_setting
    from .loaders import _rows

    path = Path(path)
    colmap.require(*REQUIRED_CLAIM_FIELDS)

    claims, problems = [], []
    for line_no, raw in _rows(path, colmap):
        code = (raw.get("cpt_code") or "").upper().strip()
        if not code:
            continue
        try:
            revenue_code = (raw.get("revenue_code") or "").strip()
            setting_text = (raw.get("setting") or "").strip()
            setting = (
                parse_setting(setting_text) if setting_text
                else (Setting.FACILITY if revenue_code else Setting.NON_FACILITY)
            )
            units_text = (raw.get("units") or "").strip()
            billed_text = (raw.get("billed_amount") or "").strip()

            claims.append(ClaimLine(
                line_number=line_no,
                cpt_code=code,
                modifier=(raw.get("modifier") or "").strip(),
                service_date=parse_date(raw["service_date"]),
                paid_amount=parse_money(raw["paid_amount"]),
                billed_amount=parse_money(billed_text) if billed_text else None,
                units=int(float(units_text)) if units_text else 1,
                setting=setting,
                provider=(raw.get("provider") or "").strip(),
                claim_id=(raw.get("claim_id") or "").strip(),
                locality_id=(raw.get("locality_id") or "").strip() or None,
                state=(raw.get("state") or "").strip() or None,
                revenue_code=revenue_code,
            ))
        except ValueError as exc:
            problems.append(f"line {line_no}, {code}: {exc}")

    if problems:
        shown = "\n  ".join(problems[:MAX_PROBLEMS_SHOWN])
        raise ClaimsFormatError(f"{path.name}: {len(problems)} problem(s)\n  {shown}")
    if not claims:
        raise ClaimsFormatError(f"{path.name}: no claim lines found")
    return claims
