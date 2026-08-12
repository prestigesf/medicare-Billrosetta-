#!/usr/bin/env python3
"""Price a billed-lines CSV against Medicare and write the results out.

    python tools/price_bill.py <bill.csv> [-o priced.csv]

Input columns: cpt_code, charged_amount, date_of_service, setting, and either
locality_id or state. Optional: modifier, description.

Every figure in the output carries its derivation. Lines that cannot be priced
are returned with the reason rather than dropped or estimated.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pfs import FeeSchedulePeriod, RateEngine  # noqa: E402
from pfs.bulk import (  # noqa: E402
    BillFormatError,
    price_bill,
    read_bill,
    write_priced_csv,
)
from pfs.loaders import (  # noqa: E402
    ColumnMap,
    load_conversion_factor,
    load_gpcis,
    load_rvus,
)
from pfs.locality import LocalityDirectory  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"

RVU_FILE = DATA / "PPRRVU2026_Jul_nonQPP.csv"
GPCI_FILE = DATA / "GPCI2026.csv"

# The release currently loaded. Rates are only defensible for dates it covers.
PERIOD_ID = "2026-RVU26C"
PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 12, 31)


def build_engine():
    rvu_layout = ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
    rvus = load_rvus(RVU_FILE, rvu_layout)
    gpcis = load_gpcis(GPCI_FILE, ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))
    conversion_factor = load_conversion_factor(RVU_FILE, rvu_layout)

    period = FeeSchedulePeriod(
        period_id=PERIOD_ID,
        effective_start=PERIOD_START,
        effective_end=PERIOD_END,
        conversion_factor=conversion_factor,
        rvus=rvus,
        gpcis=gpcis,
    )
    return RateEngine([period], zip_to_locality={}), LocalityDirectory(gpcis), conversion_factor


def money(value):
    return f"${value:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bill", help="CSV of billed lines")
    parser.add_argument("-o", "--out", help="where to write the priced CSV")
    args = parser.parse_args()

    bill_path = Path(args.bill)
    out_path = Path(args.out) if args.out else bill_path.with_name(
        bill_path.stem + "_priced.csv"
    )

    for required in (RVU_FILE, GPCI_FILE):
        if not required.exists():
            print(f"missing CMS data file: {required}", file=sys.stderr)
            return 2

    try:
        billed = read_bill(bill_path)
    except BillFormatError as exc:
        print(exc, file=sys.stderr)
        return 2

    engine, directory, conversion_factor = build_engine()
    pricing = price_bill(billed, engine, directory)
    write_priced_csv(pricing, out_path)

    summary = pricing.summary()
    print(f"\nBill: {bill_path.name}")
    print(f"Schedule: {PERIOD_ID}, conversion factor {conversion_factor}")
    print("-" * 68)
    print(f"{'line':>5}  {'code':<9} {'charged':>11} {'medicare':>11} {'x':>6}  status")
    print("-" * 68)
    for line in pricing.lines:
        code = line.billed.cpt_code + (f"-{line.billed.modifier}" if line.billed.modifier else "")
        if line.priced:
            mark = "  <-- flagged" if line.flagged else ""
            print(
                f"{line.billed.line_number:>5}  {code:<9} "
                f"{money(line.billed.charged_amount):>11} "
                f"{money(line.allowed_amount):>11} "
                f"{line.multiple_of_medicare:>6.2f}{mark}"
            )
        else:
            print(
                f"{line.billed.line_number:>5}  {code:<9} "
                f"{money(line.billed.charged_amount):>11} "
                f"{'—':>11} {'—':>6}  no benchmark"
            )
    print("-" * 68)
    print(f"  lines            {summary['lines']}  "
          f"({summary['priced']} priced, {summary['unpriced']} without a benchmark)")
    print(f"  charged          {money(summary['total_charged'])}")
    print(f"  charged (priced) {money(summary['total_charged_on_priced_lines'])}")
    print(f"  medicare allowed {money(summary['total_medicare_allowed'])}")
    print(f"  variance         {money(summary['total_variance'])}")
    print(f"  flagged lines    {summary['flagged']} "
          f"(over {summary['materiality_multiple']}x medicare), "
          f"{money(summary['total_variance_on_flagged_lines'])}")
    print()
    if pricing.unpriced_lines:
        print("Lines without a benchmark:")
        for line in pricing.unpriced_lines:
            print(f"  line {line.billed.line_number} ({line.billed.cpt_code}): "
                  f"{line.unavailable_reason}")
        print()
    print(f"written: {out_path}")
    print("\nFigures are Medicare allowed amounts computed from CMS published data.")
    print("They are not a determination of what is owed, and not legal advice.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
