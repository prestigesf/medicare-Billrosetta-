# CMS PFS Relative Value Files – RVU26C (July 2026)

Source: https://www.cms.gov/medicare/payment/fee-schedules/physician/pfs-relative-value-files/rvu26c

## Files included

- `PPRRVU2026_Jul_nonQPP.csv` – Full HCPCS/CPT relative value units (non-QPP)
- `GPCI2026.csv` – Geographic Practice Cost Indices by locality

## Conversion factor

Extracted from the official file: **33.4009** (non-qualifying APM / non-QP)

## How to load

```bash
python tools/ingest_rvu.py
```

This creates `data/cms/pfs_2026.db` with clean `rvu` and `gpci` tables.

## Notes

- These files are additive. Nothing in the existing `pfs/` engine was modified.
- Re-run the ingest script whenever a new quarterly RVU release is published.
