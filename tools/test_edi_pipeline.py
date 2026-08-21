#!/usr/bin/env python3
"""Parse the sanitized Q1 837P and price it against July 2026 CMS files."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pfs.edi_parser import EDI837Parser
from pfs.formula import compute_allowed_amount
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus
from pfs.models import PRICEABLE_STATUS_CODES, rvu_key
from pfs.pos import setting_for_pos


def main():
    if len(sys.argv) < 6:
        print(
            "Usage: python tools/test_edi_pipeline.py "
            "<837_file> <pprrvu_csv> <gpci_csv> <pprrvu_layout_json> <gpci_layout_json>"
        )
        sys.exit(1)

    edi_path, pprrvu_csv, gpci_csv, pprrvu_layout, gpci_layout = sys.argv[1:6]
    raw_edi_bytes = Path(edi_path).read_bytes()
    edi_sha256 = hashlib.sha256(raw_edi_bytes).hexdigest()
    claim_lines = EDI837Parser(raw_edi_bytes.decode("utf-8", errors="replace")).parse()

    rvus = load_rvus(pprrvu_csv, ColumnMap.from_json(pprrvu_layout))
    gpcis = load_gpcis(gpci_csv, ColumnMap.from_json(gpci_layout))
    cf = load_conversion_factor(pprrvu_csv, ColumnMap.from_json(pprrvu_layout))

    al_gpci = gpcis["10112-AL-00"]

    total_face = 0.0
    eligible_allowed_accum = 0.0
    status_x_count = 0
    mod26_count = 0

    for line in claim_lines:
        total_face += line.billed_amount
        first_mod = line.modifiers[0] if line.modifiers else ""
        if first_mod == "26":
            mod26_count += 1

        key = rvu_key(line.cpt_hcpcs, first_mod)
        if key not in rvus:
            continue
        r = rvus[key]
        if r.status_code == "X":
            status_x_count += 1
            continue
        if r.status_code not in PRICEABLE_STATUS_CODES:
            continue

        try:
            unit_allowed = compute_allowed_amount(r, al_gpci, cf, setting_for_pos(line.pos))
        except Exception:
            continue
        eligible_allowed_accum += round(unit_allowed * line.units, 2)

    rounded_face = round(total_face, 2)
    rounded_allowed = round(eligible_allowed_accum, 2)

    print("=== EDI 837P PARSER & PRICING VERIFICATION ===")
    print(f"837 Source File:     {edi_path}")
    print(f"837 File SHA-256:    {edi_sha256}")
    print(f"Total Lines Parsed:  {len(claim_lines)}")
    print(f"Status X Excluded:   {status_x_count}")
    print(f"Modifier 26 Splits:  {mod26_count}")
    print(f"Total Face Billed:   ${rounded_face:,.2f}")
    print(f"PFS Allowed Base:    ${rounded_allowed:,.2f}")

    assert len(claim_lines) == 260
    assert rounded_face == 467518.99
    assert rounded_allowed == 35601.32
    assert status_x_count == 24
    assert mod26_count == 48
    print("\n[OK] 837P parser matches the $35,601.32 candidate AR base.")


if __name__ == "__main__":
    main()
