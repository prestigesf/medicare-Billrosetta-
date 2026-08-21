#!/usr/bin/env python3
"""Verify a borrowing-base packet against on-disk CMS files."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus
from pfs.models import rvu_key
from pfs.pos import setting_for_pos


class VerifyError(Exception):
    pass


def hash_file_bytes(filepath: str) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical_leaf_payload(line, pfs_release, rvu_data_hash):
    mods_str = ",".join(sorted(line.get("modifiers") or []))
    allowed = line["engine_pricing"]["allowed_amount"] if line.get("engine_pricing") else 0.0
    return (
        f"{line['line_id']}|"
        f"{line['source_doc_hash']}|"
        f"{line['dos']}|"
        f"{line['cpt_hcpcs']}|"
        f"{mods_str}|"
        f"{line['pos']}|"
        f"{line['billed_amount']:.2f}|"
        f"{allowed:.2f}|"
        f"{line['bucket']}|"
        f"{line['inclusion_verdict']}|"
        f"{pfs_release}|"
        f"{rvu_data_hash}"
    )


def compute_leaf_hash(line, pfs_release, rvu_data_hash):
    return hashlib.sha256(
        canonical_leaf_payload(line, pfs_release, rvu_data_hash).encode()
    ).hexdigest()


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
    return "0x" + hashlib.sha256(
        f"{sorted_leaves}|{engine_part}|{rollup_part}".encode()
    ).hexdigest()


def verify_packet(packet_path, pprrvu_csv, gpci_csv, pprrvu_layout, gpci_layout):
    with open(packet_path, "r", encoding="utf-8") as f:
        packet = json.load(f)

    pprrvu_sha = hash_file_bytes(pprrvu_csv)
    gpci_sha = hash_file_bytes(gpci_csv)
    combined_hash = hashlib.sha256(f"{pprrvu_sha}|{gpci_sha}".encode()).hexdigest()

    eb = packet["engine_binding"]
    if eb["rvu_data_hash"] != combined_hash:
        raise VerifyError(
            f"CMS Data Hash mismatch: disk {combined_hash} packet {eb['rvu_data_hash']}"
        )

    rvus = load_rvus(pprrvu_csv, ColumnMap.from_json(pprrvu_layout))
    gpcis = load_gpcis(gpci_csv, ColumnMap.from_json(gpci_layout))
    disk_cf = load_conversion_factor(pprrvu_csv, ColumnMap.from_json(pprrvu_layout))

    if abs(eb["conversion_factor"] - disk_cf) > 0.0001:
        raise VerifyError(f"CF mismatch disk {disk_cf} packet {eb['conversion_factor']}")

    att = packet["eligibility_attestation"]
    if att.get("title_assigned"):
        doc_hash = att.get("assignment_doc_hash") or ""
        if len(doc_hash) != 64 or doc_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855":
            raise VerifyError("title assigned but assignment_doc_hash is invalid")

    face_accum = 0.0
    eligible_allowed_accum = 0.0
    leaf_hashes = []

    for line in packet["claim_lines"]:
        computed_lh = compute_leaf_hash(line, eb["pfs_release"], eb["rvu_data_hash"])
        if line["line_receipt_hash"] != computed_lh:
            raise VerifyError(f"leaf mismatch {line['line_id']}")
        leaf_hashes.append(computed_lh)
        face_accum += line["billed_amount"]

        mods = line.get("modifiers") or []
        first_mod = mods[0] if mods else ""
        key = rvu_key(line["cpt_hcpcs"].strip(), first_mod)
        loc_id = line["locality_id"].strip()
        if key not in rvus:
            raise VerifyError(f"missing rvu {key}")
        if loc_id not in gpcis:
            raise VerifyError(f"missing gpci {loc_id}")

        r_entry = rvus[key]
        g_entry = gpcis[loc_id]
        p = line["engine_pricing"]
        setting = setting_for_pos(line["pos"])

        if r_entry.status_code not in ("B", "X"):
            if abs(p["work_rvu"] - r_entry.work) > 0.0001:
                raise VerifyError(f"work tamper {line['line_id']}")
            expected_pe = r_entry.practice_expense_for(setting)
            if expected_pe is None:
                raise VerifyError(f"missing PE {line['line_id']}")
            if abs(p["pe_rvu"] - expected_pe) > 0.0001:
                raise VerifyError(f"pe tamper {line['line_id']}")
            if abs(p["mp_rvu"] - r_entry.malpractice) > 0.0001:
                raise VerifyError(f"mp tamper {line['line_id']}")
            if (
                abs(p["gpci_work"] - g_entry.work) > 0.0001
                or abs(p["gpci_pe"] - g_entry.practice_expense) > 0.0001
                or abs(p["gpci_mp"] - g_entry.malpractice) > 0.0001
            ):
                raise VerifyError(f"gpci tamper {line['line_id']}")
            tot = (
                r_entry.work * g_entry.work
                + expected_pe * g_entry.practice_expense
                + r_entry.malpractice * g_entry.malpractice
            )
            disk_allowed = round(tot * disk_cf, 2)
        else:
            disk_allowed = 0.0

        if abs(disk_allowed - p["allowed_amount"]) > 0.001:
            raise VerifyError(
                f"allowed mismatch {line['line_id']}: disk {disk_allowed} json {p['allowed_amount']}"
            )

        if (
            line["bucket"] == "BUCKET_A_FILED_MEDICARE_AR"
            and line["inclusion_verdict"] == "ELIGIBLE_AR"
            and not line.get("exclusion_flags")
        ):
            if not att.get("title_assigned"):
                raise VerifyError("Bucket A line present but title is unbound")
            if not line.get("claim_control_number"):
                raise VerifyError("missing CCN")
            eligible_allowed_accum += disk_allowed

    r = packet["rollup"]
    if round(face_accum, 2) != round(r["total_face_billed"], 2):
        raise VerifyError("face mismatch")
    if round(eligible_allowed_accum, 2) != round(r["eligible_ar_allowed"], 2):
        raise VerifyError(
            f"eligible mismatch {eligible_allowed_accum} vs {r['eligible_ar_allowed']}"
        )
    if round(r["total_face_billed"] - r["eligible_ar_allowed"], 2) != round(r["haircuts_total"], 2):
        raise VerifyError("haircut mismatch")
    if round(r["net_borrowing_base"] * (r["advance_rate_pct"] / 100.0), 2) != round(
        r["advance_amount_t0"], 2
    ):
        raise VerifyError("advance mismatch")
    if round(r["advance_amount_t0"] + r["reserve_amount"], 2) != round(r["net_borrowing_base"], 2):
        raise VerifyError("reserve mismatch")
    computed = compute_packet_digest(leaf_hashes, eb, r)
    if packet["packet_digest"] != computed:
        raise VerifyError(f"digest mismatch computed {computed}")

    print(f"[OK] DISK-BOUND VERIFICATION PASSED: {packet['packet_id']}")
    print(f"    - Combined: {combined_hash}")
    print(f"    - Face: ${r['total_face_billed']:,.2f}")
    print(f"    - Eligible: ${r['eligible_ar_allowed']:,.2f}")
    print(f"    - Advance: ${r['advance_amount_t0']:,.2f}")
    print(f"    - Digest: {packet['packet_digest']}")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(
            "Usage: python tools/verify_borrowing_base.py "
            "<packet.json> <pprrvu.csv> <gpci.csv> <pprrvu_layout.json> <gpci_layout.json>"
        )
        sys.exit(1)
    verify_packet(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
