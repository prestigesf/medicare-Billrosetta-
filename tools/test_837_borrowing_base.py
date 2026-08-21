#!/usr/bin/env python3
"""Build unbound 837 packet and check title-gate numbers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd):
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def main():
    edi = ROOT / "examples/claims_q1_2026.837"
    if not edi.exists():
        run([sys.executable, "tools/csv_to_837.py"])

    out = ROOT / "evidence/claims_q1_2026_837_unbound.json"
    run([sys.executable, "tools/build_837_borrowing_base.py", "--out", str(out)])
    packet = json.loads(out.read_text())
    r = packet["rollup"]
    assert r["priced_medicare_allowed"] == 35601.32, r
    assert r["eligible_ar_allowed"] == 0.0, r
    assert r["advance_amount_t0"] == 0.0, r
    assert packet["eligibility_attestation"]["title_assigned"] is False
    print("[OK] unbound 837 book: priced $35,601.32 eligible $0.00 advance $0.00")

    run(
        [
            sys.executable,
            "tools/verify_borrowing_base.py",
            str(out),
            str(ROOT / "data/cms/rvu26c/PPRRVU2026_Jul_nonQPP.csv"),
            str(ROOT / "data/cms/rvu26c/GPCI2026.csv"),
            str(ROOT / "layouts/pprrvu_2026.json"),
            str(ROOT / "layouts/gpci_2026.json"),
        ]
    )


if __name__ == "__main__":
    main()
