#!/usr/bin/env python3
"""Serialize examples/claims_q1_2026.csv into a sanitized X12 837P.

No live MBI, SSN, or EIN. Provider NPIs are deterministic test numbers.
This file is for parser/engine tests, not MAC submission.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from pfs.pos import infer_pos_from_rev_code

ISA_DATE = "260620"
ISA_TIME = "1823"
GS_DATE = "20260620"


def npi_for_provider(name: str) -> str:
    """10-digit test NPI, Luhn-valid, not a live identifier."""
    digest = hashlib.sha256(name.encode()).hexdigest()
    body = "".join(str(int(digest[i], 16) % 10) for i in range(9))
    prefix = "80840" + body

    def luhn_check(digits: str) -> int:
        total = 0
        reverse = digits[::-1]
        for i, ch in enumerate(reverse):
            n = int(ch)
            if i % 2 == 0:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        return (10 - (total % 10)) % 10

    return body + str(luhn_check(prefix))


def test_mbi(claim_id: str) -> str:
    digest = hashlib.sha256(claim_id.encode()).hexdigest()[:11].upper()
    return "T" + digest


def pad(value: str, width: int) -> str:
    return value[:width].ljust(width)


def emit(rows, submitter="BILLROSETTA TEST", receiver="NORIDIAN TEST"):
    segs = []

    def add(*parts):
        segs.append("*".join(str(p) for p in parts))

    add(
        "ISA",
        "00",
        pad("", 10),
        "00",
        pad("", 10),
        "ZZ",
        pad("TESTSUB01", 15),
        "ZZ",
        pad("01112", 15),
        ISA_DATE,
        ISA_TIME,
        "^",
        "00501",
        "000000001",
        "0",
        "T",
        ":",
    )
    add("GS", "HC", "TESTSUB01", "01112", GS_DATE, ISA_TIME, "1", "X", "005010X222A1")
    add("ST", "837", "0001", "005010X222A1")
    add("BHT", "0019", "00", "Q12026BOOK", GS_DATE, ISA_TIME, "CH")
    add("NM1", "41", "2", submitter, "", "", "", "", "46", "TESTSUB01")
    add("PER", "IC", "TEST CONTACT", "TE", "5555551212")
    add("NM1", "40", "2", receiver, "", "", "", "", "46", "01112")

    by_provider = defaultdict(list)
    for row in rows:
        by_provider[row["provider"]].append(row)

    hl = 0
    for provider, claims in by_provider.items():
        hl += 1
        billing_hl = hl
        add("HL", str(billing_hl), "", "20", "1")
        add("NM1", "85", "2", provider, "", "", "", "", "XX", npi_for_provider(provider))
        add("N3", "100 TEST STREET")
        add("N4", "BIRMINGHAM", "AL", "35203")
        add("REF", "EI", "000000000")

        for row in claims:
            hl += 1
            add("HL", str(hl), str(billing_hl), "22", "0")
            add("SBR", "P", "18", "", "", "", "", "", "", "MB")
            add("NM1", "IL", "1", "TEST", row["claim_id"], "", "", "", "MI", test_mbi(row["claim_id"]))
            add("N3", "1 SYNTHETIC AVE")
            add("N4", "BIRMINGHAM", "AL", "35203")
            add("NM1", "PR", "2", "MEDICARE", "", "", "", "", "PI", "10112")

            pos = infer_pos_from_rev_code(row.get("rev_code") or "")
            billed = f"{float(row['billed']):.2f}"
            add(
                "CLM",
                row["claim_id"],
                billed,
                "",
                "",
                f"{pos}:B:1",
                "Y",
                "A",
                "Y",
                "Y",
            )
            dos = row["dos"].replace("-", "")
            add("DTP", "431", "D8", dos)
            add("HI", "ABK:Z0000")
            add("LX", "1")
            proc = row["cpt"].strip().upper()
            mod = (row.get("mod") or "").strip().upper()
            hc = f"HC:{proc}:{mod}" if mod else f"HC:{proc}"
            units = row.get("units") or "1"
            add("SV1", hc, billed, "UN", units, "", "", "1")
            add("DTP", "472", "D8", dos)

    st_index = next(i for i, s in enumerate(segs) if s.startswith("ST*"))
    st_count = len(segs) - st_index + 1
    add("SE", str(st_count), "0001")
    add("GE", "1", "1")
    add("IEA", "1", "000000001")
    return "~\n".join(segs) + "~\n"


def hashlib_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", default=str(ROOT / "examples/claims_q1_2026.csv"))
    ap.add_argument("--out", default=str(ROOT / "examples/claims_q1_2026.837"))
    args = ap.parse_args()

    with open(args.claims, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    text = emit(rows)
    out = Path(args.out)
    out.write_text(text)
    print(f"wrote {out} ({len(rows)} claims, {text.count('~')} segments)")
    print(f"sha256 {hashlib_file(out)}")


if __name__ == "__main__":
    main()
