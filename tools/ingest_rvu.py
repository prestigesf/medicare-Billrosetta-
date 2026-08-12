#!/usr/bin/env python3
"""
CMS PFS Relative Value File Ingestion (additive module)

Purpose
-------
Load the official CMS RVU release (PPRRVU + GPCI) into a clean, queryable
SQLite database that BillRosetta / medicare-Billrosetta can consume.

Does NOT modify any existing code in BILLROSETTA or medicare-Billrosetta-.
This is a standalone, additive data pipeline.

Sources (as of RVU26C – July 2026)
----------------------------------
- PPRRVU2026_Jul_nonQPP.csv   → Work / PE / MP RVUs + status + conversion factor
- GPCI2026.csv               → Locality-level geographic adjusters

Conversion factor is extracted from the data itself (column present on every row).
Official non-QP CY 2026 CF: 33.4009
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration – point these at the unzipped CMS release
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cms" / "rvu26c"
PPRRVU_FILE = DATA_DIR / "PPRRVU2026_Jul_nonQPP.csv"
GPCI_FILE = DATA_DIR / "GPCI2026.csv"
OUTPUT_DB = Path(__file__).resolve().parent.parent / "data" / "cms" / "pfs_2026.db"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_header_row(path: Path, key: str = "HCPCS") -> int:
    """Return the 0-based index of the real header row."""
    with open(path, newline="", encoding="latin-1") as f:
        for i, row in enumerate(csv.reader(f)):
            if row and row[0].strip() == key:
                return i
    raise ValueError(f"Could not find header row containing '{key}' in {path}")


def extract_conversion_factor(path: Path, header_idx: int) -> float:
    """
    Read the conversion factor that CMS embeds in every data row.
    Official non-QP CY 2026 value is 33.4009.
    """
    with open(path, newline="", encoding="latin-1") as f:
        reader = csv.reader(f)
        for _ in range(header_idx + 1):
            next(reader)
        row = next(reader)
        for cell in row:
            try:
                val = float(cell)
                if 30.0 < val < 40.0:  # plausible range for recent CFs
                    return val
            except (ValueError, TypeError):
                continue
    raise ValueError("Could not extract conversion factor from PPRRVU file")


def load_pprrvu(conn: sqlite3.Connection, path: Path) -> int:
    header_idx = find_header_row(path, "HCPCS")
    cf = extract_conversion_factor(path, header_idx)
    print(f"[+] Conversion factor extracted from file: {cf}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rvu (
            hcpcs        TEXT NOT NULL,
            mod          TEXT,
            description  TEXT,
            status       TEXT,
            work_rvu     REAL,
            pe_nfac_rvu  REAL,
            pe_fac_rvu   REAL,
            mp_rvu       REAL,
            global_days  TEXT,
            conv_factor   REAL,
            PRIMARY KEY (hcpcs, mod)
        )
        """
    )
    conn.execute("DELETE FROM rvu")  # clean reload for this release

    count = 0
    with open(path, newline="", encoding="latin-1") as f:
        reader = csv.reader(f)
        for _ in range(header_idx + 1):
            next(reader)

        for row in reader:
            if not row or not row[0].strip():
                continue
            hcpcs = row[0].strip()
            mod = (row[1] or "").strip()
            desc = (row[2] or "").strip()
            status = (row[3] or "").strip()

            def fnum(idx: int) -> Optional[float]:
                try:
                    return float(row[idx]) if row[idx].strip() else None
                except (IndexError, ValueError):
                    return None

            work = fnum(5)
            pe_nfac = fnum(6)
            pe_fac = fnum(8)
            mp = fnum(10)
            global_days = (row[14] if len(row) > 14 else "") or ""

            conn.execute(
                """
                INSERT OR REPLACE INTO rvu
                (hcpcs, mod, description, status, work_rvu, pe_nfac_rvu, pe_fac_rvu, mp_rvu, global_days, conv_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (hcpcs, mod, desc, status, work, pe_nfac, pe_fac, mp, global_days, cf),
            )
            count += 1

    conn.commit()
    return count


def load_gpci(conn: sqlite3.Connection, path: Path) -> int:
    """Load locality GPCIs. Header is on the third row of the published CSV."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpci (
            mac          TEXT,
            state        TEXT,
            locality     TEXT,
            locality_name TEXT,
            work_gpci    REAL,
            pe_gpci      REAL,
            mp_gpci      REAL,
            PRIMARY KEY (state, locality)
        )
        """
    )
    conn.execute("DELETE FROM gpci")

    count = 0
    with open(path, newline="", encoding="latin-1") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and "Locality Number" in "".join(row):
                break

        for row in reader:
            if len(row) < 7 or not row[2].strip():
                continue
            try:
                mac = row[0].strip()
                state = row[1].strip()
                locality = row[2].strip()
                name = row[3].strip()
                work = float(row[4])
                pe = float(row[5])
                mp = float(row[6])
            except (ValueError, IndexError):
                continue

            conn.execute(
                """
                INSERT OR REPLACE INTO gpci
                (mac, state, locality, locality_name, work_gpci, pe_gpci, mp_gpci)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mac, state, locality, name, work, pe, mp),
            )
            count += 1

    conn.commit()
    return count


def compute_payment(
    work_rvu: float,
    pe_rvu: float,
    mp_rvu: float,
    work_gpci: float,
    pe_gpci: float,
    mp_gpci: float,
    conv_factor: float,
) -> float:
    """Standard non-facility (or facility) payment formula."""
    return ((work_rvu * work_gpci) + (pe_rvu * pe_gpci) + (mp_rvu * mp_gpci)) * conv_factor


def main() -> None:
    if not PPRRVU_FILE.exists():
        print(f"ERROR: {PPRRVU_FILE} not found. Download RVU26C first.", file=sys.stderr)
        sys.exit(1)
    if not GPCI_FILE.exists():
        print(f"ERROR: {GPCI_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"[+] Source directory : {DATA_DIR}")
    print(f"[+] Output database  : {OUTPUT_DB}")

    conn = sqlite3.connect(OUTPUT_DB)

    n_rvu = load_pprrvu(conn, PPRRVU_FILE)
    print(f"[+] Loaded {n_rvu:,} HCPCS/modifier rows into rvu table")

    n_gpci = load_gpci(conn, GPCI_FILE)
    print(f"[+] Loaded {n_gpci:,} locality rows into gpci table")

    row = conn.execute(
        """
        SELECT work_rvu, pe_nfac_rvu, mp_rvu, conv_factor
        FROM rvu WHERE hcpcs = '99214' AND mod = ''
        """
    ).fetchone()
    if row:
        work, pe, mp, cf = row
        payment = compute_payment(work or 0, pe or 0, mp or 0, 1.0, 1.0, 1.0, cf)
        print(f"[+] Sanity: 99214 national non-facility ≈ ${payment:.2f}")

    conn.close()
    print("[+] Done. Database ready for rate lookups.")


if __name__ == "__main__":
    main()
