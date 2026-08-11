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

## Status

The calculation and lookup are built and tested — 27 tests, run with warnings
as errors. **No CMS data is loaded yet.** The fixtures in `tests/` are
illustrative: the structure is real, the numbers are not CMS's.

To make rates real, three CMS files are needed:

| File | Provides |
| --- | --- |
| PPRRVU (Physician Fee Schedule RVU file) | work / PE / MP RVUs and status code per CPT |
| GPCI file | the three geographic indices per MAC locality |
| ZIP-to-locality crosswalk | maps a ZIP to its locality id |

Loaders are deliberately not written yet. They will be written against the
real column layouts rather than assumed ones — writing a parser against a
guessed format is how you get code that looks finished and is not.

## Scope

This prices services under the **Physician Fee Schedule** — the professional
component. Hospital facility charges are priced under OPPS (outpatient) or
DRGs (inpatient) and are *not* covered here. Comparing a facility line to PFS
is the wrong benchmark. Office visits, labs, and the professional component of
imaging are the correct cases.

## Tests

    python -m pytest -W error
