---
name: medicare-rates
description: "Work on the Medicare Physician Fee Schedule rate engine (the `pfs` package) — computing Medicare allowed amounts from CMS published RVU, GPCI and conversion-factor data, loading a new CMS release, pricing a billed-lines CSV, or extending coverage to OPPS/DRG. Use when the user references medicare-Billrosetta, the PFS engine, RVU/GPCI/PPRRVU files, CPT rate lookup, locality or MAC resolution, bill benchmarking against Medicare, or continuing the phased build. Also use when applying this repo's protocol — build, test with warnings as errors, drift diff against a frozen baseline, self-hashed evidence artifact, read-back verify, stop for approval."
license: Proprietary.
---

# Medicare PFS rate engine

Computes the Medicare allowed amount for a CPT code, in a locality, on a date
of service, from CMS's published data — then prices whole bills against it.

Repo: `prestigesf/medicare-Billrosetta-`. Related: `prestigesf/BILLROSETTA`
(the bill-decoding product this exists to supply).

## The calculation

    allowed = [(work RVU x work GPCI)
             + (PE RVU x PE GPCI)
             + (MP RVU x MP GPCI)] x conversion factor

Each RVU takes its own geographic index; the three are not interchangeable.
Money rounds once, at the end, half-up.

## Non-negotiable invariants

1. **REPORT ≠ VERIFIED.** Never claim a result. Produce artifacts: raw test
   output, SHA-256 hashes, a self-hashed evidence JSON read back and
   re-verified. A claim without an artifact is not done.
2. **Rates are data, not code.** No CPT code, rate, GPCI, or conversion factor
   in `pfs/` source. Enforced by `tests/test_invariants.py`, which strips
   docstrings and rejects float literals and CPT-shaped integers. Policy
   numbers are data too — see `policy/materiality.json`.
3. **Never weaken a test to make it pass.** Find the real defect.
4. **No invented rate, ever.** Every failure raises a specific
   `RateUnavailable` subclass naming its reason. No default rate, no fallback
   amount, no zero-instead-of-refusal.
5. **A rate is reproducible.** `(code, modifier, locality, setting, date)`
   against a schedule version always yields the same amount, and the result
   carries its own derivation.
6. **One bad line never fails a batch**, and never inflates a total.
7. **Not legal or medical advice.** Output is analysis and a draft.
8. **No real PHI in fixtures.** Test data is synthetic, always.

## What the real CMS files do that synthetic fixtures never will

These were each found by loading actual releases. Expect them again.

- **The header row moves.** The full July release carries nine banner rows;
  its own excerpt carried eight. Layouts locate the header by its first cell
  (`header_starts_with`), never a fixed offset.
- **Column names repeat.** PPRRVU splits its header across four rows and
  repeats names in the last: `PE RVU` appears twice (non-facility, then
  facility) and `RVU` twice (work, then malpractice). Address those by
  position. Guard by reconciling parsed components against CMS's own published
  totals — that proves positions independently.
- **A CPT code is not unique.** Codes appear global, professional (`26`), and
  technical (`TC`), each with different RVUs — 2,261 such rows in CY2026. Key
  on code + modifier or the file is refused wholesale.
- **MAC + locality is not unique either.** MAC 05102 serves Connecticut and
  Iowa, both locality `00`, with different indices. Key on MAC-State-Locality.
- **Footnote prose follows the data** after a blank row (`stop_at_blank_row`).
- **Status codes gate pricing, not RVU presence.** 158 non-priceable rows
  carry real RVUs — CPT 27215 has a work RVU of 10.19 under status `I`. Only
  `A`, `R`, `T` are priceable.
- **The conversion factor is a column**, repeated on every row. Read it; refuse
  a file carrying more than one value.

## Layout of the repo

```
pfs/            formula, engine, models, errors, loaders, locality, bulk
layouts/*.json  where each CMS file's columns live — config, not code
policy/         business thresholds as data
data/cms/       the committed CMS release
tools/          make_evidence.py, phase_diff.py, price_bill.py, ingest_rvu.py
evidence/       per-phase artifacts and frozen baselines
```

## Per-phase loop

```
1. SPEC       state the scope; do not invent scope
2. BUILD      add; reuse what exists
3. TEST       python -m pytest -v -W error       (warnings are errors)
4. EVIDENCE   python tools/make_evidence.py <N>
5. VERIFY     recompute the payload hash in a separate process
6. DIFF       python tools/phase_diff.py evidence/baseline_code_postPhase<N-1>.txt "<authorized csv>"
7. FREEZE     python tools/phase_diff.py --freeze evidence/baseline_code_postPhase<N>.txt
8. COMMIT     one commit per phase, describing what was established
9. STOP       report and await approval
```

Generate evidence **after** the code is final — an artifact whose file hashes
describe a tree that no longer exists is worse than none.

## Common tasks

- **Load a new CMS release** → drop the files in `data/cms/<release>/`, copy a
  layout in `layouts/`, adjust column positions, run. The loader prints the
  file's actual headers on a mismatch, which is what corrects the layout. Touch
  no engine code.
- **Price a bill** → `python tools/price_bill.py <bill.csv>`. Columns:
  `cpt_code`, `charged_amount`, `date_of_service`, `setting`, and either
  `locality_id` or `state`; optional `modifier`, `description`.
- **Add a schedule year** → a second `FeeSchedulePeriod`. Overlapping periods
  are rejected at construction; date of service selects the edition.
- **Extend to hospital facility charges** → OPPS (outpatient) and DRG
  (inpatient) are separate systems. PFS is the wrong benchmark for them. This
  is real new work, not a layout change.

## Known limits

- **No ZIP-to-locality crosswalk.** CMS does not reliably publish it. 36 of 53
  states resolve from the state alone; the other 17 need an explicit
  `locality_id`: CA, FL, GA, IL, LA, MA, MD, ME, MI, MO, NJ, NY, OR, PA, TX,
  WA, WV.
- **Physician fee schedule only.** Professional services. Hospital facility
  charges price under OPPS or DRGs and are out of scope.
- **One release loaded** (CY2026 RVU26C). Older dates of service need their own
  period loaded.
