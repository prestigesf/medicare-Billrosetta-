# CMS PFS Relative Value Files – RVU26C (July 2026)

Source: https://www.cms.gov/medicare/payment/fee-schedules/physician/pfs-relative-value-files/rvu26c

## Files in this folder

| File | Description |
|------|-------------|
| `PPRRVU2026_Jul_nonQPP_SAMPLE.csv` | Header + first ~200 data rows (shows exact column layout) |
| `GPCI2026.csv` | Geographic Practice Cost Indices by locality |
| `README.md` | This file |

## Full data

The complete `PPRRVU2026_Jul_nonQPP.csv` (~2.6 MB, 19k+ rows) is kept local / downloaded from CMS each quarter. Do not commit the full file unless you move to Git LFS.

## Conversion factor

Extracted from the official file: **33.4009** (non-qualifying APM / non-QP)

## How to load

```bash
# Place the full PPRRVU CSV next to the sample, then:
python tools/ingest_rvu.py
```

Creates `data/cms/pfs_2026.db` with clean `rvu` and `gpci` tables.

## Notes

- Additive only — nothing in the existing `pfs/` engine was modified.
- Re-run the ingest script whenever a new quarterly RVU release is published.
