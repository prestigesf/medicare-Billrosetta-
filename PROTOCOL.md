# Build protocol

The output of this package is a number someone relies on in a quasi-legal
document. A claim about the system is worth nothing without an artifact behind
it, so each phase produces evidence rather than a report.

## Invariants

1. **REPORT ≠ VERIFIED.** Never claim a result. Produce artifacts: raw test
   output, SHA-256 hashes, a self-hashed evidence JSON read back and
   re-verified. A claim without an artifact is not done.
2. **Rates are data, not code.** No CPT code, rate, GPCI, or conversion factor
   may appear in `pfs/` source. Enforced by `tests/test_invariants.py`, which
   strips docstrings and asserts no float literals and no CPT-shaped integers
   survive in executable code. Loading a new schedule year must never require
   editing this package.
3. **Never weaken a test to make it pass.** Find the real defect.
4. **No invented rate, ever.** Every failure raises a specific
   `RateUnavailable` subclass naming its reason. There is no default rate, no
   fallback amount, and no zero-instead-of-refusal.
5. **A rate is reproducible.** `(cpt_code, locality, setting, date_of_service)`
   against a given schedule version always yields the same amount, and the
   result carries its own derivation.
6. **Don't touch prior-phase code without authorization.** Each phase adds.
7. **Not legal or medical advice.** Output is analysis and a draft.
8. **No real PHI in fixtures.** Test data is synthetic, always.

## Per-phase loop

```
1. SPEC       state the phase scope; do not invent scope
2. BUILD      add new files; reuse what exists, don't reimplement
3. TEST       python -m pytest -v -W error        (warnings are errors)
4. EVIDENCE   python tools/make_evidence.py <N>
              -> preserves raw output to evidence/phaseN_raw_test_output.txt
              -> writes evidence/phase_N_validation_<ts>.json, self-hashed
              -> reads the artifact back and recomputes the payload hash
5. VERIFY     recompute the payload hash from a separate process, not the
              generator's own word
6. COMMIT     one commit per phase, describing what was established
7. STOP       report and await approval. Do NOT begin the next phase.
```

Git handles drift detection, so there is no separately frozen code baseline.
What git does not provide is proof that a test run happened and what it
produced — hence the evidence artifact and the read-back verify. Every
artifact records `git_commit`, tying the evidence to an exact tree.

Evidence files are excluded from the hashed source set, so generated artifacts
never register as source drift.

## Phases

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Calculation, lookup, refusal paths, invariant enforcement | **Complete** — 43 tests, artifact verified |
| 2 | CMS loaders: PPRRVU, GPCI, ZIP-to-locality crosswalk | Blocked: needs the three files |
| 3 | Bulk input/output: CSV in, priced results with derivation out | — |
| 4 | Integrate the engine into the bill-decoding application | — |
| 5 | OPPS pricing for hospital facility charges | Conditional — only if it proves to be the blocker |

## Phase 1 result

- 43 tests passed, 0 failed, 0 error, 0 skipped, exit 0, warnings as errors
- Artifact: `evidence/phase_1_validation_20260811T190809Z.json`
- Payload SHA-256: `3f8828912f495f7ec313e2fe59937338fd4dd340cf667d8f4b785d19febe746e`
- Read-back verified, and independently recomputed in a separate process
- 11 source files hashed

Loaders are deliberately unwritten. Writing a parser against a guessed file
layout produces code that looks finished and is not.
