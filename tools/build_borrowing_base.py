#!/usr/bin/env python3
"""Stream a claims extract into a borrowing-base packet.

Without an assignment file, title is unbound and eligible AR is $0.
Priced allowed is still reported so the engine can be audited at book scale.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pfs.documents import bind_file, sha256_bytes
from pfs.formula import compute_allowed_amount
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus
from pfs.models import PRICEABLE_STATUS_CODES, rvu_key
from pfs.pos import infer_pos_from_rev_code, setting_for_pos


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def canonical_leaf_payload(line: dict, pfs_release: str, rvu_data_hash: str) -> str:
    mods = ",".join(sorted(line.get("modifiers") or []))
    allowed = line["engine_pricing"]["allowed_amount"] if line.get("engine_pricing") else 0.0
    return (
        f"{line['line_id']}|"
        f"{line['source_doc_hash']}|"
        f"{line['dos']}|"
        f"{line['cpt_hcpcs']}|"
        f"{mods}|"
        f"{line['pos']}|"
        f"{line['billed_amount']:.2f}|"
        f"{allowed:.2f}|"
        f"{line['bucket']}|"
        f"{line['inclusion_verdict']}|"
        f"{pfs_release}|"
        f"{rvu_data_hash}"
    )


def compute_leaf_hash(line, pfs_release, rvu_data_hash):
    return hashlib.sha256(canonical_leaf_payload(line, pfs_release, rvu_data_hash).encode()).hexdigest()


def compute_packet_digest(leaf_hashes, engine_binding, rollup):
    sorted_leaves = "".join(sorted(leaf_hashes))
    engine_part = (
        f"{engine_binding['pfs_release']}|"
        f"{engine_binding['conversion_factor']:.4f}|"
        f"{engine_binding['rvu_data_hash']}"
    )
    rollup_part = (
        f"{rollup['total_face_billed']:.2f}|"
        f"{rollup['eligible_ar_allowed']:.2f}|"
        f"{rollup['haircuts_total']:.2f}|"
        f"{rollup['net_borrowing_base']:.2f}|"
        f"{rollup['advance_rate_pct']:.2f}|"
        f"{rollup['advance_amount_t0']:.2f}|"
        f"{rollup['reserve_amount']:.2f}"
    )
    return "0x" + hashlib.sha256(f"{sorted_leaves}|{engine_part}|{rollup_part}".encode()).hexdigest()


def normalize_locality(raw: str) -> str:
    return raw.strip()


def modifier_list(mod: str) -> list:
    m = (mod or "").strip().upper()
    return [m] if m else []


def price_line(row, rvus, gpcis, cf):
    cpt = row["cpt"].strip().upper()
    mods = modifier_list(row.get("mod", ""))
    key = rvu_key(cpt, mods[0] if mods else "")
    loc = normalize_locality(row["locality"])
    units = float(row.get("units") or 1)
    billed = float(row["billed"])
    pos = (row.get("pos") or "").strip() or infer_pos_from_rev_code(row.get("rev_code", ""))
    setting = setting_for_pos(pos)

    flags = []
    engine = None
    allowed = 0.0
    status = None

    if key not in rvus:
        flags.append("CPT_NOT_IN_PFS")
        bucket = "BUCKET_E_UNPRICEABLE_EXCLUDED"
        verdict = "REJECTED_EXCLUDED"
    elif loc not in gpcis:
        flags.append("INVALID_LOCALITY")
        bucket = "BUCKET_E_UNPRICEABLE_EXCLUDED"
        verdict = "REJECTED_EXCLUDED"
    else:
        rec = rvus[key]
        status = rec.status_code
        gpci = gpcis[loc]
        if rec.status_code not in PRICEABLE_STATUS_CODES:
            flags.append(f"STATUS_{rec.status_code}")
            bucket = "BUCKET_E_UNPRICEABLE_EXCLUDED"
            verdict = "REJECTED_EXCLUDED"
            engine = {
                "work_rvu": rec.work,
                "pe_rvu": rec.practice_expense_for(setting) or 0.0,
                "mp_rvu": rec.malpractice,
                "gpci_work": gpci.work,
                "gpci_pe": gpci.practice_expense,
                "gpci_mp": gpci.malpractice,
                "allowed_amount": 0.0,
                "derivation": f"status {rec.status_code} not priceable under PFS",
            }
        else:
            try:
                unit_allowed = compute_allowed_amount(rec, gpci, cf, setting)
            except Exception as exc:
                flags.append("PE_OR_SETTING_UNAVAILABLE")
                bucket = "BUCKET_E_UNPRICEABLE_EXCLUDED"
                verdict = "REJECTED_EXCLUDED"
                engine = {
                    "work_rvu": rec.work,
                    "pe_rvu": rec.practice_expense_for(setting),
                    "mp_rvu": rec.malpractice,
                    "gpci_work": gpci.work,
                    "gpci_pe": gpci.practice_expense,
                    "gpci_mp": gpci.malpractice,
                    "allowed_amount": 0.0,
                    "derivation": str(exc),
                }
            else:
                allowed = round(unit_allowed * units, 2)
                pe = rec.practice_expense_for(setting)
                engine = {
                    "work_rvu": rec.work,
                    "pe_rvu": pe,
                    "mp_rvu": rec.malpractice,
                    "gpci_work": gpci.work,
                    "gpci_pe": gpci.practice_expense,
                    "gpci_mp": gpci.malpractice,
                    "units": units,
                    "unit_allowed": unit_allowed,
                    "allowed_amount": allowed,
                    "derivation": (
                        f"({rec.work}*{gpci.work} + {pe}*{gpci.practice_expense} + "
                        f"{rec.malpractice}*{gpci.malpractice}) * {cf} = {unit_allowed} "
                        f"x {units} units = {allowed}"
                    ),
                }
                bucket = "BUCKET_A_CANDIDATE"
                verdict = "PENDING_TITLE"

    source = sha256_bytes(
        f"{row['claim_id']}|{cpt}|{','.join(mods)}|{row['dos']}|{billed:.2f}|{loc}".encode()
    )
    return {
        "line_id": row["claim_id"],
        "claim_control_number": row["claim_id"],
        "source_doc_hash": source,
        "dos": row["dos"],
        "cpt_hcpcs": cpt,
        "modifiers": mods,
        "pos": pos,
        "locality_id": loc,
        "billed_amount": billed,
        "provider": row.get("provider"),
        "status_code": status,
        "bucket": bucket,
        "exclusion_flags": flags,
        "inclusion_verdict": verdict,
        "engine_pricing": engine,
        "priced_allowed": allowed,
    }


def apply_title(lines, title_bound: bool):
    priced = 0.0
    eligible = 0.0
    for line in lines:
        priced += line["priced_allowed"]
        if not title_bound:
            if line["bucket"] == "BUCKET_A_CANDIDATE":
                line["bucket"] = "BUCKET_C_APPEAL_UPSIDE"
                line["inclusion_verdict"] = "REJECTED_EXCLUDED"
                line["exclusion_flags"] = list(line["exclusion_flags"]) + ["TITLE_UNBOUND"]
        else:
            if line["bucket"] == "BUCKET_A_CANDIDATE":
                line["bucket"] = "BUCKET_A_FILED_MEDICARE_AR"
                line["inclusion_verdict"] = "ELIGIBLE_AR"
                eligible += line["priced_allowed"]
        line.pop("priced_allowed", None)
    return priced, eligible


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", default=str(ROOT / "examples/claims_q1_2026.csv"))
    ap.add_argument("--pprrvu", default=str(ROOT / "data/cms/rvu26c/PPRRVU2026_Jul_nonQPP.csv"))
    ap.add_argument("--gpci", default=str(ROOT / "data/cms/rvu26c/GPCI2026.csv"))
    ap.add_argument("--pprrvu-layout", default=str(ROOT / "layouts/pprrvu_2026.json"))
    ap.add_argument("--gpci-layout", default=str(ROOT / "layouts/gpci_2026.json"))
    ap.add_argument("--assignment-file", default="")
    ap.add_argument("--advance-rate", type=float, default=76.6)
    ap.add_argument("--out", default=str(ROOT / "evidence/claims_q1_2026_book.json"))
    args = ap.parse_args()

    pprrvu = Path(args.pprrvu)
    gpci = Path(args.gpci)
    pprrvu_sha = hash_file(pprrvu)
    gpci_sha = hash_file(gpci)
    combined = hashlib.sha256(f"{pprrvu_sha}|{gpci_sha}".encode()).hexdigest()

    rvus = load_rvus(pprrvu, ColumnMap.from_json(args.pprrvu_layout))
    gpcis = load_gpcis(gpci, ColumnMap.from_json(args.gpci_layout))
    cf = load_conversion_factor(pprrvu, ColumnMap.from_json(args.pprrvu_layout))

    assignment = bind_file(args.assignment_file or None)

    lines = []
    with open(args.claims, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lines.append(price_line(row, rvus, gpcis, cf))

    priced_total, eligible = apply_title(lines, assignment.bound)
    face = round(sum(l["billed_amount"] for l in lines), 2)
    eligible = round(eligible, 2)
    haircuts = round(face - eligible, 2)
    advance = round(eligible * (args.advance_rate / 100.0), 2)
    reserve = round(eligible - advance, 2)

    pfs_release = "RVU26C"
    leaf_hashes = []
    for line in lines:
        if line["engine_pricing"] is None:
            line["engine_pricing"] = {
                "work_rvu": 0.0, "pe_rvu": 0.0, "mp_rvu": 0.0,
                "gpci_work": 0.0, "gpci_pe": 0.0, "gpci_mp": 0.0,
                "allowed_amount": 0.0, "derivation": "unpriced",
            }
        lh = compute_leaf_hash(line, pfs_release, combined)
        line["line_receipt_hash"] = lh
        leaf_hashes.append(lh)

    engine_binding = {
        "pfs_release": pfs_release,
        "conversion_factor": cf,
        "rvu_data_hash": combined,
        "pprrvu_sha256": pprrvu_sha,
        "gpci_sha256": gpci_sha,
    }
    rollup = {
        "total_face_billed": face,
        "priced_medicare_allowed": round(priced_total, 2),
        "eligible_ar_allowed": eligible,
        "haircuts_total": haircuts,
        "net_borrowing_base": eligible,
        "advance_rate_pct": args.advance_rate,
        "advance_amount_t0": advance,
        "reserve_amount": reserve,
        "line_count": len(lines),
    }
    packet = {
        "packet_id": "BB-2026-Q1-BOOK",
        "fixture_mode": "PRODUCTION_BOOK",
        "engine_binding": engine_binding,
        "eligibility_attestation": {
            "title_assigned": assignment.bound,
            "assignment_doc_hash": assignment.sha256,
            "assignment_path": assignment.path,
            "timely_filing_verified": False,
            "no_recoupment_block": False,
        },
        "claim_lines": lines,
        "rollup": rollup,
    }
    packet["packet_digest"] = compute_packet_digest(leaf_hashes, engine_binding, rollup)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, indent=2) + "\n")

    print("=== BOOK BUILD ===")
    print(f"wrote {out}")
    print(f"lines {len(lines)}")
    print(f"face billed ${face:,.2f}")
    print(f"priced allowed (if titled) ${priced_total:,.2f}")
    print(f"eligible AR ${eligible:,.2f}  title_bound={assignment.bound}")
    print(f"advance {args.advance_rate}% ${advance:,.2f}")
    print(f"reserve ${reserve:,.2f}")
    print(f"rvu_data_hash {combined}")
    print(f"digest {packet['packet_digest']}")


if __name__ == "__main__":
    main()
