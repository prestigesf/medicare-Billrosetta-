# BillRosetta PFS Engine — Locked Calculation Rules

**Status:** Locked

These rules govern live Medicare baseline pricing in `backend/pfs/` / the rate engine.
They exist to keep every output aligned with official CMS 2026 published values down to the penny.

---

## 1. Data source

- Primary input: official CMS PPRRVU file (e.g. `PPRRVU2026_Jul_nonQPP.csv`)
- Work RVU values in that file are **already pre-adjusted** by CMS for the 2026 efficiency reduction
- Practice Expense RVU and Malpractice RVU are taken as published

**Rule:** Read `Work_RVU` directly from the file. Do not apply any secondary efficiency multiplier on the live payment path.

---

## 2. Conversion factor routing

| Provider status | Conversion Factor (CY 2026) |
|-----------------|-----------------------------|
| Qualifying APM Participant (QP) | $33.5675 |
| Non-QP / Standard | $33.4009 |

Route by explicit provider status (`is_qualifying_apm`). Never default to a single CF.

---

## 3. Core payment formula (live path)

```
Payment = (wRVU × wGPCI + peRVU × peGPCI + mpRVU × mpGPCI) × CF
```

- Use facility or non-facility PE RVU according to place of service
- GPCI values come from the official GPCI file for the payment locality
- No additional 0.975 (or any other) efficiency factor is applied here

---

## 4. Analytical / historical mode only

The -2.5% Work RVU efficiency multiplier (`wRVU × 0.975`) may appear **only** in comparison or impact-modeling modules (e.g. 2025 vs 2026 provider compensation analysis).

It must never run on the base Medicare rate calculation path used for disputes, patient receipts, API responses, or agent queries.

---

## 5. Why this lock exists

- Prevents double-counting of the CMS efficiency cut
- Keeps every BillRosetta price output identical to the official Medicare baseline
- Produces dispute receipts that cannot be challenged on math grounds
- Keeps the core payment path deterministic and decoupled from analytical tooling

---

## 6. Outtake

Rate results intended for legal or patient use should carry a signed audit receipt (ML-DSA-65 / FIPS 204 or equivalent) so the calculation inputs and formula version are immutable.

---

*Locked. No secondary efficiency multiplier on live rates. Dual CF by provider status only.*
