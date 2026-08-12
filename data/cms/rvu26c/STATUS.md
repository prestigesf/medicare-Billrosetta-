# CMS Data Status – RVU26C (July 2026)

## Conversion Factor (sourced from the official file)

**33.4009** (non-qualifying APM / non-QP)

- Extracted directly from every data row of `PPRRVU2026_Jul_nonQPP.csv` (column ~25).
- Confirmed against CY 2026 PFS Final Rule and data.cms.gov indicators.
- There is a separate QP conversion factor (~33.5675). Use 33.4009 for standard rate work.
- The ingestion script (`tools/ingest_rvu.py`) reads this value from the file — it is never hardcoded.

## Files we have

| File | Location | Notes |
|------|----------|-------|
| PPRRVU (full) | Local: `cms_data/RVU26C/PPRRVU2026_Jul_nonQPP.csv` | 19,356 rows |
| PPRRVU (sample) | Repo: `data/cms/rvu26c/PPRRVU2026_Jul_nonQPP_SAMPLE.csv` | Header + first ~200 rows |
| GPCI | Repo + local | Full locality GPCIs |
| Documentation PDF | Local: `cms_data/RVU26C/RVU26C.pdf` | Official RVU26C documentation |
| Ingestion script | Repo: `tools/ingest_rvu.py` | Additive, does not touch existing `pfs/` code |

## ZIP Code to Carrier Locality File (ZIP5 / ZIP9)

These files map ZIP codes to Medicare payment localities.

**Current reality (Aug 2026):**
- CMS releases ZIP5 and ZIP9 quarterly.
- They are primarily distributed to Medicare Administrative Contractors (MACs) via secure channels (Direct Connect / Cloud).
- Public web links are not stably published on the main PFS Relative Value Files page.
- Change Request R13661CP (and similar) describes the schedule: roughly 6 weeks before each quarter (Feb 15 / May 15 / Aug 15).
- Older year-end ZIP files sometimes appear on mirrors of the ProspMedicareFeeSvcPmtGen downloads directory, but current quarterly files are restricted.

**Practical approach until a public link is available:**
- Use the GPCI locality file we already have for rate calculations when the locality is known.
- For ZIP → locality resolution, either:
  1. Obtain the current ZIP5/ZIP9 from a MAC contact or CMS contractor channel, or
  2. Use a commercial / derived locality lookup service that is updated from the official files.

## How to load rates right now

```bash
# Ensure full PPRRVU CSV is next to the sample, then:
python tools/ingest_rvu.py
```

Creates `data/cms/pfs_2026.db` with clean `rvu` + `gpci` tables. Conversion factor is pulled from the data automatically.

## Nothing was overwritten

All additions are under `data/cms/` and `tools/`. Existing `pfs/` engine code is untouched.
