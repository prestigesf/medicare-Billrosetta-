#!/usr/bin/env python3
"""Audit a quarter of paid claims against Medicare.

    python tools/audit_claims.py examples/claims_q1_2026.csv

Reports what a plan sponsor needs, in the order they need it: how much of the
spend could be benchmarked at all, then the variance across those dollars,
then where it concentrates — and finally why the rest could not be measured.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pfs import FeeSchedulePeriod, RateEngine  # noqa: E402
from pfs.audit import audit_claims, read_claims  # noqa: E402
from pfs.ledger import SourceRecord, record_audit, sha256_file  # noqa: E402
from pfs.loaders import (  # noqa: E402
    ColumnMap, load_conversion_factor, load_gpcis, load_rvus,
)
from pfs.locality import LocalityDirectory  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
PERIOD_ID = "2026-RVU26C"
LAYOUTS = ROOT / "layouts"

TEAL, RUST, GREEN, DIM, BOLD, R = (
    "\033[38;5;36m", "\033[38;5;173m", "\033[38;5;78m", "\033[2m", "\033[1m", "\033[0m",
)
WIDTH = 78


def money(value):
    return f"${value:,.2f}"


def rule(char="─"):
    print(f"{TEAL}{char * WIDTH}{R}")


def build_engine():
    layout = ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
    rvu_file = DATA / "PPRRVU2026_Jul_nonQPP.csv"
    rvus = load_rvus(rvu_file, layout)
    gpcis = load_gpcis(DATA / "GPCI2026.csv", ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))
    engine = RateEngine([FeeSchedulePeriod(
        "2026-RVU26C", date(2026, 1, 1), date(2026, 12, 31),
        load_conversion_factor(rvu_file, layout), rvus, gpcis,
    )], {})
    return engine, LocalityDirectory(gpcis)


def print_groups(title, groups, limit=None):
    rule()
    print(f"{BOLD}{title}{R}")
    rule()
    print(f"  {'':<32}{'paid':>12}{'benchmark':>12}{'variance':>12}{'×':>7}{'cov':>7}")
    for group in (groups[:limit] if limit else groups):
        multiple = f"{group.multiple:.2f}" if group.multiple else "—"
        colour = RUST if group.multiple and group.multiple >= 3 else ""
        print(f"  {group.key[:31]:<32}{money(group.paid):>12}"
              f"{money(group.benchmark):>12}{colour}{money(group.variance):>12}"
              f"{multiple:>7}{R}{group.coverage:>7.0%}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claims", nargs="?",
                        default=str(ROOT / "examples" / "claims_q1_2026.csv"))
    parser.add_argument("--layout", default=str(LAYOUTS / "claims_extract.json"))
    args = parser.parse_args()

    claims_path = Path(args.claims)
    claims = read_claims(claims_path, ColumnMap.from_json(args.layout))
    engine, directory = build_engine()
    audit = audit_claims(claims, engine, directory)
    summary = audit.summary()

    print(f"\n{BOLD}CLAIMS AUDIT — MEDICARE VARIANCE{R}")
    print(f"{DIM}{claims_path.name} · {summary['lines']} lines · "
          f"CMS Physician Fee Schedule 2026-RVU26C{R}\n")

    # Coverage first. A variance figure without it overstates its own authority.
    rule("═")
    coverage = summary["coverage_of_paid_dollars"]
    colour = GREEN if coverage >= 0.8 else RUST
    print(f"  {BOLD}Benchmarkable spend{R}      {colour}{coverage:>6.0%}{R} of paid dollars "
          f"({money(summary['benchmarked_paid'])} of {money(summary['total_paid'])})")
    print(f"  {DIM}Everything below is measured across that share only, never "
          f"projected onto the rest.{R}")
    rule("═")
    print()
    print(f"  {'Paid on benchmarkable lines':<34}{money(summary['benchmarked_paid']):>14}")
    print(f"  {'Medicare allowed for the same':<34}{money(summary['total_benchmark']):>14}")
    print(f"  {BOLD}{'Variance':<34}{money(summary['total_variance']):>14}{R}")
    print(f"  {BOLD}{'Paid as a multiple of Medicare':<34}"
          f"{summary['overall_multiple_of_medicare']:>13.2f}×{R}\n")

    print_groups("BY PROVIDER — largest variance first", audit.by_provider())
    print_groups("BY SERVICE CATEGORY", audit.by_category())
    print_groups("BY MONTH", audit.by_month())

    concentration = audit.concentration(top=3)
    rule()
    print(f"{BOLD}CONCENTRATION{R}")
    rule()
    print(f"  {concentration['share_in_top']:.0%} of the variance sits with "
          f"{len(concentration['top'])} of {concentration['providers_with_variance']} providers:")
    for name, variance in concentration["top"]:
        print(f"    {name[:44]:<45}{money(variance):>14}")
    print()

    rule()
    print(f"{BOLD}WHY THE REST COULD NOT BE BENCHMARKED{R}")
    rule()
    for reason, count, paid in audit.reasons():
        print(f"  {money(paid):>13}  {count:>4} lines   {reason[:52]}")
    print()
    print(f"  {DIM}Those dollars are not a finding of zero variance. They are "
          f"unmeasured,{R}")
    print(f"  {DIM}and most of them need OPPS or DRG pricing rather than the "
          f"physician schedule.{R}\n")

    # The ledger is the thing that outlives the report.
    ledger = record_audit(
        audit,
        sources=[
            SourceRecord("claims extract", "input", claims_path.name,
                         sha256_file(claims_path)),
            SourceRecord("PPRRVU", "cms-file", (DATA / "PPRRVU2026_Jul_nonQPP.csv").name,
                         sha256_file(DATA / "PPRRVU2026_Jul_nonQPP.csv")),
            SourceRecord("GPCI", "cms-file", (DATA / "GPCI2026.csv").name,
                         sha256_file(DATA / "GPCI2026.csv")),
        ],
        parameters={"schedule": PERIOD_ID, "lines": str(summary["lines"])},
    )
    ledger_path = claims_path.with_name(claims_path.stem + "_ledger.json")
    ledger.write(ledger_path)
    check = ledger.verify()

    rule()
    print(f"{BOLD}AUDIT LEDGER{R}")
    rule()
    print(f"  run           {ledger.run_id}")
    print(f"  entries       {check['entries']} chained")
    print(f"  head          {ledger.head[:32]}…")
    print(f"  integrity     {GREEN if check['intact'] else RUST}"
          f"{'VERIFIED — chain intact' if check['intact'] else check['detail']}{R}")
    print(f"  written       {ledger_path.name}")
    print(f"  {DIM}Claim identifiers are stored as salted digests. Altering any "
          f"line breaks{R}")
    print(f"  {DIM}every hash after it, which is what makes this evidence rather "
          f"than a report.{R}\n")

    rule("═")
    print(f"{DIM}  Medicare allowed amounts computed from CMS published data. "
          f"Benchmarks, not{R}")
    print(f"{DIM}  a determination of what was owed. Not legal advice.{R}")
    rule("═")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
