examples/claims_q1_2026.837 is generated, not a live MAC submission.

```
python tools/csv_to_837.py
```

- 260 CLM / SV1 loops from examples/claims_q1_2026.csv
- Synthetic MBIs (prefix T) and test NPIs
- No live PHI
- Regenerated hash at last run: 8fd7246c5ad17e7ae2c0a57e0f4f785dc515417afc290fb4df42724c31c27031

This is Path 2 (dev fixture). Live underwriting still needs the provider's outbound 837 batch plus a real assignment.
