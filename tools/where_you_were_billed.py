#!/usr/bin/env python3
"""The same bill, priced in every Medicare locality in the country.

A charge is only "3x Medicare" somewhere. Move the same bill across the map
and the number every other tool reports as fact moves with it.

    python tools/where_you_were_billed.py examples/sample_bill.csv
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pfs import FeeSchedulePeriod, RateEngine, Setting  # noqa: E402
from pfs.bulk import read_bill  # noqa: E402
from pfs.errors import RateUnavailable  # noqa: E402
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"

TEAL, RUST, GREEN, DIM, BOLD, R = (
    "\033[38;5;36m", "\033[38;5;173m", "\033[38;5;78m", "\033[2m", "\033[1m", "\033[0m",
)

BAR_WIDTH = 34


def main() -> int:
    bill_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples" / "sample_bill.csv"

    layout = ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
    rvu_file = DATA / "PPRRVU2026_Jul_nonQPP.csv"
    rvus = load_rvus(rvu_file, layout)
    gpcis = load_gpcis(DATA / "GPCI2026.csv", ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))
    engine = RateEngine([FeeSchedulePeriod(
        "2026-RVU26C", date(2026, 1, 1), date(2026, 12, 31),
        load_conversion_factor(rvu_file, layout), rvus, gpcis,
    )], {})

    billed = read_bill(bill_path)
    charged_total = sum(line.charged_amount for line in billed)

    # Price the whole bill in every locality that can price all of it, so the
    # comparison is like for like rather than a different subset each time.
    results = []
    for locality_id, gpci in gpcis.items():
        allowed = 0.0
        complete = True
        for line in billed:
            try:
                allowed += engine.rate_for_locality(
                    line.cpt_code, locality_id, line.setting,
                    line.service_date, modifier=line.modifier,
                ).allowed_amount
            except RateUnavailable:
                complete = False
                break
        if complete:
            results.append((locality_id, gpci.locality_name, allowed))

    if not results:
        print("No locality can price every line of this bill.")
        return 1

    results.sort(key=lambda row: row[2])
    lowest, highest = results[0], results[-1]
    priced_total = sum(
        line.charged_amount for line in billed
    )

    print(f"\n{BOLD}THE SAME BILL, PRICED ACROSS THE COUNTRY{R}")
    print(f"{DIM}{bill_path.name} · {len(billed)} lines · charged "
          f"${charged_total:,.2f} · {len(results)} of {len(gpcis)} localities "
          f"can price every line{R}\n")

    span = highest[2] - lowest[2]
    shown = results[:3] + [None] + results[-3:] if len(results) > 7 else results

    for row in shown:
        if row is None:
            print(f"  {DIM}{'…':>34}{R}")
            continue
        locality_id, name, allowed = row
        filled = int(BAR_WIDTH * (allowed - lowest[2]) / span) if span else BAR_WIDTH
        bar = "█" * max(filled, 1)
        multiple = priced_total / allowed
        colour = RUST if multiple >= 3 else TEAL
        print(f"  {name[:30]:<31} {colour}{bar:<{BAR_WIDTH}}{R} "
              f"${allowed:>9,.2f}  {BOLD}{multiple:>5.2f}×{R}")

    lowest_multiple = priced_total / highest[2]   # biggest allowance, smallest multiple
    highest_multiple = priced_total / lowest[2]   # smallest allowance, biggest multiple
    swing = (highest_multiple / lowest_multiple - 1) * 100

    print(f"\n  {DIM}{'─' * 74}{R}")
    print(f"  Highest allowance   {highest[1][:34]:<35} ${highest[2]:>9,.2f}  "
          f"{lowest_multiple:>5.2f}×")
    print(f"  Lowest allowance    {lowest[1][:34]:<35} ${lowest[2]:>9,.2f}  "
          f"{highest_multiple:>5.2f}×")
    print()
    print(f"  {BOLD}The same bill is {lowest_multiple:.2f}× Medicare in "
          f"{highest[1].split('(')[0].strip().title()}{R}")
    print(f"  {BOLD}and {highest_multiple:.2f}× in {lowest[1].split('(')[0].strip().title()}. "
          f"A {swing:.0f}% swing in the headline number.{R}")
    print()
    print(f"  {RUST}That headline number is what every flat-rate tool reports as a fact.{R}")
    print(f"  {DIM}It is only true in one place, and none of them say which.{R}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
