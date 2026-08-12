#!/usr/bin/env python3
"""One-command demo: real Medicare rates, computed live, then the test suite.

    python demo.py

Everything printed is computed from the CMS files in data/cms/ at runtime.
Nothing is hardcoded for the demo.
"""
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# Windows consoles default to cp1252 and cannot encode the box characters
# below. Force UTF-8 so the banner renders instead of raising mid-demo.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pfs import FeeSchedulePeriod, RateEngine, Setting  # noqa: E402
from pfs.bulk import price_bill, read_bill  # noqa: E402
from pfs.loaders import (  # noqa: E402
    ColumnMap, load_conversion_factor, load_gpcis, load_rvus,
)
from pfs.locality import LocalityDirectory  # noqa: E402

TEAL = "\033[38;5;36m"
GREEN = "\033[38;5;78m"
RUST = "\033[38;5;173m"
DIM = "\033[2m"
BOLD = "\033[1m"
R = "\033[0m"

DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"
DOS = date(2026, 3, 14)

SHOWCASE = [
    ("99214", "", "10112-AL-00", Setting.NON_FACILITY),
    ("99214", "", "01112-CA-05", Setting.NON_FACILITY),
    ("99214", "", "10112-AL-00", Setting.FACILITY),
    ("71046", "", "10112-AL-00", Setting.NON_FACILITY),
    ("71046", "26", "10112-AL-00", Setting.NON_FACILITY),
]


def rule(char="─", width=72):
    print(f"{TEAL}{char * width}{R}")


def banner():
    print(f"""
{TEAL}{BOLD}  ╔══════════════════════════════════════════════════════════════════╗
  ║   M E D I C A R E   R A T E   E N G I N E                        ║
  ║   CMS Physician Fee Schedule · CY2026 RVU26C                     ║
  ╚══════════════════════════════════════════════════════════════════╝{R}
{DIM}  Every figure below is computed from the CMS files in data/cms/
  at runtime. Nothing is hardcoded for this demo.{R}
""")


def main() -> int:
    banner()

    started = time.time()
    print(f"{BOLD}Loading the CY2026 release…{R}")
    layout = ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
    rvu_file = DATA / "PPRRVU2026_Jul_nonQPP.csv"
    rvus = load_rvus(rvu_file, layout)
    gpcis = load_gpcis(DATA / "GPCI2026.csv", ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))
    conversion_factor = load_conversion_factor(rvu_file, layout)
    directory = LocalityDirectory(gpcis)
    engine = RateEngine([FeeSchedulePeriod(
        "2026-RVU26C", date(2026, 1, 1), date(2026, 12, 31),
        conversion_factor, rvus, gpcis,
    )], {})
    elapsed = time.time() - started

    coverage = directory.coverage()
    print(f"  {GREEN}✔{R} {len(rvus):,} priceable lines")
    print(f"  {GREEN}✔{R} {len(gpcis)} localities across {coverage['states_total']} states")
    print(f"  {GREEN}✔{R} conversion factor {BOLD}{conversion_factor}{R} "
          f"{DIM}(read from the file, not hardcoded){R}")
    print(f"  {DIM}loaded in {elapsed:.2f}s{R}\n")

    # ---- the calculation, worked -------------------------------------------
    rule()
    print(f"{BOLD}THE CALCULATION{R}  {DIM}CPT 99214, Alabama, non-facility{R}")
    rule()
    entry = rvus["99214"]
    gpci = gpcis["10112-AL-00"]
    parts = [
        ("work", entry.work, gpci.work),
        ("practice expense", entry.practice_expense_non_facility, gpci.practice_expense),
        ("malpractice", entry.malpractice, gpci.malpractice),
    ]
    total = 0.0
    for label, rvu, index in parts:
        component = rvu * index
        total += component
        print(f"  {label:<18} {rvu:>6.2f} × {index:>6.3f}  =  {component:>8.4f}")
    print(f"  {'':<18} {'':>6}   {'':>6}     {'─' * 8}")
    print(f"  {'total RVU':<18} {'':>6}   {'':>6}     {total:>8.4f}")
    print(f"  {BOLD}{TEAL}{'× ' + str(conversion_factor):<18} {'':>6}   {'':>6}     "
          f"${total * conversion_factor:>7.2f}{R}\n")

    # ---- the same code, priced several ways --------------------------------
    rule()
    print(f"{BOLD}SAME CODE, DIFFERENT ANSWERS{R}  {DIM}geography, setting, modifier{R}")
    rule()
    for code, modifier, locality, setting in SHOWCASE:
        result = engine.rate_for_locality(code, locality, setting, DOS, modifier=modifier)
        label = code + (f"-{modifier}" if modifier else "")
        place = result.locality_name[:28]
        print(f"  {label:<10} {place:<30} {setting.value:<13} "
              f"{BOLD}${result.allowed_amount:>8.2f}{R}")
    print()

    # ---- a real bill -------------------------------------------------------
    example = ROOT / "examples" / "sample_bill.csv"
    if example.exists():
        rule()
        print(f"{BOLD}A BILL, PRICED{R}  {DIM}{example.name}{R}")
        rule()
        pricing = price_bill(read_bill(example), engine, directory)
        for line in pricing.lines:
            code = line.billed.cpt_code + (f"-{line.billed.modifier}" if line.billed.modifier else "")
            if line.priced:
                colour = RUST if line.flagged else ""
                mark = "flagged" if line.flagged else ""
                print(f"  {code:<10} charged ${line.billed.charged_amount:>9,.2f}   "
                      f"medicare ${line.allowed_amount:>8,.2f}   "
                      f"{colour}{line.multiple_of_medicare:>5.2f}× {mark}{R}")
            else:
                reason = (line.unavailable_reason or "").split(";")[0][:44]
                print(f"  {code:<10} charged ${line.billed.charged_amount:>9,.2f}   "
                      f"{DIM}no benchmark — {reason}{R}")
        summary = pricing.summary()
        print()
        print(f"  {'charged (priced lines)':<26} ${summary['total_charged_on_priced_lines']:>10,.2f}")
        print(f"  {'medicare allowed':<26} ${summary['total_medicare_allowed']:>10,.2f}")
        print(f"  {BOLD}{'variance':<26} ${summary['total_variance']:>10,.2f}{R}")
        print(f"  {DIM}{summary['unpriced']} of {summary['lines']} lines had no defensible "
              f"benchmark and contribute nothing to that figure.{R}\n")

    # ---- the limits, said out loud -----------------------------------------
    rule()
    print(f"{BOLD}WHAT THIS WILL NOT DO{R}")
    rule()
    print(f"  {RUST}·{R} invent a rate — every failure names its own reason")
    print(f"  {RUST}·{R} price hospital facility charges (OPPS/DRG, different system)")
    print(f"  {RUST}·{R} resolve a ZIP in {coverage['states_requiring_a_zip']} multi-locality states "
          f"without a crosswalk")
    print(f"  {RUST}·{R} price a date of service outside the loaded schedule year\n")

    # ---- proof -------------------------------------------------------------
    rule()
    print(f"{BOLD}TEST SUITE{R}  {DIM}warnings as errors{R}")
    rule()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-W", "error"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print("  " + (result.stdout.strip().splitlines() or ["no output"])[-1])
    print()
    rule("═")
    if result.returncode == 0:
        print(f"{GREEN}{BOLD}  ✔ Real Medicare rates, computed from CMS data, with the arithmetic attached.{R}")
    else:
        print(f"{RUST}{BOLD}  ✘ Tests failed (exit {result.returncode}){R}")
    rule("═")
    print()
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
