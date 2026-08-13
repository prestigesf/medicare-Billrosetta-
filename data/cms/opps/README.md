# CMS Hospital Outpatient PPS (OPPS) Addendum B

**Source:** https://www.cms.gov/medicare/payment/prospective-payment-systems/hospital-outpatient-pps/quarterly-addenda-updates

**Current file:** July 2026 Addendum B (updated July 21, 2026)

## What this is

Addendum B maps **HCPCS/CPT → Status Indicator + APC + Payment Rate** under the Hospital Outpatient Prospective Payment System.

This is the facility outpatient pricing counterpart to the PFS Relative Value Files used for physician/non-facility rates.

## Columns (header row)

```
HCPCS Code, Short Descriptor, SI, APC, Relative Weight, Payment Rate,
National Unadjusted Copayment, Minimum Unadjusted Copayment,
IRA Coinsurance Percentage, Adjusted Beneficiary Copayment,
Drug and Device Pass-Through Expiration during Calendar Year, Note, * Indicates a Change
```

Key fields for rate lookup:
- `HCPCS Code`
- `SI` (status indicator — determines packaging / separate payment)
- `APC`
- `Payment Rate`

## Files

| File | Notes |
|------|-------|
| `July2026_Addendum_B_SAMPLE.csv` | Header + first ~50 data rows (layout visible) |
| Full CSV / XLSX | Local only until committed (~1.1 MB). Same pattern as PPRRVU. |

## Download

```
https://www.cms.gov/files/zip/july-2026-opps-addendum-b.zip
```

(License interstitial may appear on the CMS site.)

## Usage note

Facility outpatient pricing follows the same overall pattern as PFS:
1. Look up HCPCS in Addendum B
2. Apply status indicator rules (packaged vs separately payable)
3. Use the published Payment Rate (or APC relative weight × conversion factor when applicable)

ZIP → locality is still a separate gap for geographic adjustment where required.
