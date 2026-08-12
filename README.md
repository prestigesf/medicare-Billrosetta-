# pfs — Medicare Physician Fee Schedule rates

Computes the Medicare allowed amount for a CPT code, in a locality, on a date
of service, from CMS's published data.

```python
from datetime import date
from pfs import RateEngine, Setting

engine = RateEngine(periods, zip_to_locality)
result = engine.rate("99214", "94110", Setting.NON_FACILITY, date(2026, 3, 14))

result.allowed_amount   # 137.35
result.source           # 'cms-pfs:2026:01-05'
result.explain()        # full derivation, one line
```

## What this does differently

**No rate is ever invented.** Every failure raises a specific
`RateUnavailable` subclass — `UnknownCPTCode`, `UnmappedZipCode`,
`NotPriceableUnderPFS`, `NoFeeScheduleForDate`, `MissingPracticeExpenseRVU` —
naming the reason. A wrong benchmark in an appeal letter is worse than no
benchmark, so there is no default rate anywhere in this package.

**Date of service decides the schedule.** A bill from March 2024 is priced
against the 2024 fee schedule, not today's. Overlapping periods are rejected
at construction, so a date can never silently resolve to whichever edition
happened to be loaded first. This is the requirement most rate lookups miss,
and it cannot be retrofitted cheaply.

**Setting is required, not defaulted.** The practice-expense RVU differs
between facility and non-facility, so the same code in a hospital and in a
doctor's office are different amounts. A caller who does not know the setting
does not get a rate.

**Status codes are honoured.** Bundled, non-covered, statutorily excluded and
carrier-priced codes have no national amount. Carrier-priced (`C`) genuinely
has none — the MAC sets it — so the package refuses rather than computing
zero.

**The conversion factor is data, not a constant.** It is republished
annually, and a hardcoded copy becomes a silent wrong answer the moment it
changes. It lives on `FeeSchedulePeriod`, loaded from CMS.

## The calculation

    allowed = [(work RVU x work GPCI)
             + (PE RVU x PE GPCI)
             + (MP RVU x MP GPCI)] x conversion factor

Each RVU is adjusted by its own geographic index before the sum — the three
GPCIs are not interchangeable. Money is rounded once, at the end, half-up
(Python's built-in `round()` is half-to-even, which rounds inconsistently in a
way nobody wants to explain to a claims administrator).

## Pricing a whole bill

    python tools/price_bill.py examples/sample_bill.csv

Input columns: `cpt_code`, `charged_amount`, `date_of_service`, `setting`, and
either `locality_id` or `state`. Optional: `modifier`, `description`.

Output is one row per billed line carrying the Medicare allowed amount, the
variance, the multiple of Medicare, the rate source, and the full derivation —
or, where a line has no defensible benchmark, the reason why. One bad line
never fails the batch, and nothing is estimated.

A line is flagged when the charge exceeds the benchmark by more than the
multiple in `policy/materiality.json` (currently 1.5). Below that the
difference is reported but not framed as a finding.

## Status

Loaded and verified against the complete CMS RVU26C release (July 2026):
**19,356 priceable lines, 98 localities, conversion factor 33.4009** read from
the file rather than hardcoded. 142 tests, run with warnings as errors.

| File | Status |
| --- | --- |
| `PPRRVU2026_Jul_nonQPP.csv` | loaded — `data/cms/rvu26c/` |
| `GPCI2026.csv` | loaded — `data/cms/rvu26c/` |
| ZIP-to-locality crosswalk | **not available**; CMS does not reliably publish it |

Without the crosswalk, 36 of 53 states and territories still resolve from the
state alone, because they contain exactly one locality. The other 17 need
either an explicit `locality_id` or a crosswalk: CA, FL, GA, IL, LA, MA, MD,
ME, MI, MO, NJ, NY, OR, PA, TX, WA, WV.

## Scope

This prices services under the **Physician Fee Schedule** — the professional
component. Hospital facility charges are priced under OPPS (outpatient) or
DRGs (inpatient) and are *not* covered here. Comparing a facility line to PFS
is the wrong benchmark. Office visits, labs, and the professional component of
imaging are the correct cases.

## Tests

    python -m pytest -W error

## Demo

    python demo.py

Loads the CMS release, works the calculation for one code, prices the same
code across localities and settings, prices a whole bill, states its own
limits, and runs the suite. Everything printed is computed at runtime.
