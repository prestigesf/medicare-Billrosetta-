#!/usr/bin/env python3
"""837P -> borrowing-base packet using existing PFS loaders and title gate.

Does not modify tools/build_borrowing_base.py. Reuses its hash/title helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pfs.documents import bind_file
from pfs.edi_parser import EDI837Parser
from pfs.formula import compute_allowed_amount
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus
from pfs.models import PRICEABLE_STATUS_CODES, rvu_key
from pfs.pos import setting_for_pos


def _load_builder():
    path = ROOT / "tools" / "build_borrowing_base.py"
    spec = importlib.util.spec_from_file_location("build_borrowing_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BB = _load_builder()


class LocalityError(ValueError):
    pass


def resolve_locality(gpcis, *, locality: str, state: str, npi_map: dict) -> str:
    if locality:
        if locality not in gpcis:
            raise LocalityError(f"locality {locality} not in GPCI file")
        return locality
    if npi_map:
        values = sorted(set(npi_map.values()))
        if len(values) != 1:
            raise LocalityError("NPI/locality map is ambiguous; pass a single locality")
        loc = values[0]
        if loc not in gpcis:
            raise LocalityError(f"mapped locality {loc} not in GPCI file")
        return loc
    if not state:
        raise LocalityError("pass --locality, --state (single-locality states only), or --npi-locality-map")
    matches = sorted(k for k in gpcis if f"-{state.upper()}-" in k)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LocalityError(f"no GPCI locality for state {state}")
    raise LocalityError(
        f"state {state} has multiple localities {matches}; require --locality or --npi-locality-map"
    )


def price_parsed_line(line, rvus, gpci, cf, locality_id):
    mods = list(line.modifiers or [])
    key = rvu_key(line.cpt_hcpcs, mods[0] if mods else "")
    flags = []
    engine = None
    allowed = 0.0
    status = None
    if key not in rvus:
        flags.append("CPT_NOT_IN_PFS")
        bucket = "BUCKET_E_UNPRICEABLE_EXCLUDED"
        verdict = "REJECTED_EXCLUDED"
    else:
        rec = rvus[key]
        status = rec.status_code
        if rec.status_code not in PRICEABLE_STATUS_CODES:
            flags.append(f"STATUS_{rec.status_code}")
            bucket = "BUCKET_E_UNPRICEABLE_EXCLUDED"
            verdict = "REJECTED_EXCLUDED"
            engine = {
                "work_rvu": rec.work,
                "pe_rvu": 0.0,
                "mp_rvu": rec.malpractice,
                "gpci_work": gpci.work,
                "gpci_pe": gpci.practice_expense,
                "gpci_mp": gpci.malpractice,
                "allowed_amount": 0.0,
                "derivation": f"status {rec.status_code} not priceable under PFS",
            }
        else:
            setting = setting_for_pos(line.pos)
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
                allowed = round(unit_allowed * float(line.units), 2)
                pe = rec.practice_expense_for(setting)
                engine = {
                    "work_rvu": rec.work,
                    "pe_rvu": pe,
                    "mp_rvu": rec.malpractice,
                    "gpci_work": gpci.work,
                    "gpci_pe": gpci.practice_expense,
                    "gpci_mp": gpci.malpractice,
                    "units": float(line.units),
                    "unit_allowed": unit_allowed,
                    "allowed_amount": allowed,
                    "derivation": f"unit {unit_allowed} x {line.units} = {allowed}",
                }
                bucket = "BUCKET_A_CANDIDATE"
                verdict = "PENDING_TITLE"

    return {
        "line_id": line.line_id,
        "claim_control_number": line.claim_control_number,
        "source_doc_hash": line.raw_segment_hash,
        "billing_npi": line.billing_npi,
        "dos": line.dos,
        "cpt_hcpcs": line.cpt_hcpcs,
        "modifiers": mods,
        "pos": line.pos,
        "locality_id": locality_id,
        "billed_amount": line.billed_amount,
        "status_code": status,
        "bucket": bucket,
        "exclusion_flags": flags,
        "inclusion_verdict": verdict,
        "engine_pricing": engine,
        "priced_allowed": allowed,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edi", default=str(ROOT / "examples/claims_q1_2026.837"))
    ap.add_argument("--pprrvu", default=str(ROOT / "data/cms/rvu26c/PPRRVU2026_Jul_nonQPP.csv"))
    ap.add_argument("--gpci", default=str(ROOT / "data/cms/rvu26c/GPCI2026.csv"))
    ap.add_argument("--pprrvu-layout", default=str(ROOT / "layouts/pprrvu_2026.json"))
    ap.add_argument("--gpci-layout", default=str(ROOT / "layouts/gpci_2026.json"))
    ap.add_argument("--assignment-file", default="")
    ap.add_argument("--locality", default="")
    ap.add_argument("--state", default="AL")
    ap.add_argument("--npi-locality-map", default="")
    ap.add_argument("--advance-rate", type=float, default=76.6)
    ap.add_argument("--out", default=str(ROOT / "evidence/claims_q1_2026_837_packet.json"))
    args = ap.parse_args()

    edi_path = Path(args.edi)
    if not edi_path.is_file():
        raise SystemExit(f"missing 837: {edi_path} (run python tools/csv_to_837.py first)")

    npi_map = json.loads(Path(args.npi_locality_map).read_text()) if args.npi_locality_map else {}

    pprrvu = Path(args.pprrvu)
    gpci_path = Path(args.gpci)
    pprrvu_sha = BB.hash_file(pprrvu)
    gpci_sha = BB.hash_file(gpci_path)
    combined = hashlib.sha256(f"{pprrvu_sha}|{gpci_sha}".encode()).hexdigest()
    edi_sha = hashlib.sha256(edi_path.read_bytes()).hexdigest()

    rvus = load_rvus(pprrvu, ColumnMap.from_json(args.pprrvu_layout))
    gpcis = load_gpcis(gpci_path, ColumnMap.from_json(args.gpci_layout))
    cf = load_conversion_factor(pprrvu, ColumnMap.from_json(args.pprrvu_layout))
    locality = resolve_locality(gpcis, locality=args.locality, state=args.state, npi_map=npi_map)
    gpci = gpcis[locality]

    parsed = EDI837Parser(edi_path.read_text()).parse()
    lines = [price_parsed_line(line, rvus, gpci, cf, locality) for line in parsed]
    assignment = bind_file(args.assignment_file or None)
    priced_total, eligible = BB.apply_title(lines, assignment.bound)

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
        lh = BB.compute_leaf_hash(line, pfs_release, combined)
        line["line_receipt_hash"] = lh
        leaf_hashes.append(lh)

    npis = sorted({l.get("billing_npi") or "" for l in lines if l.get("billing_npi")})
    engine_binding = {
        "pfs_release": pfs_release,
        "conversion_factor": cf,
        "rvu_data_hash": combined,
        "pprrvu_sha256": pprrvu_sha,
        "gpci_sha256": gpci_sha,
        "edi_sha256": edi_sha,
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
        "packet_id": "BB-2026-Q1-837",
        "fixture_mode": "PRODUCTION_BOOK",
        "provider_npi": npis[0] if len(npis) == 1 else "MULTI",
        "mac_jurisdiction": locality,
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
    packet["packet_digest"] = BB.compute_packet_digest(leaf_hashes, engine_binding, rollup)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, indent=2) + "\n")
    print("=== 837 BOOK BUILD ===")
    print(f"wrote {out}")
    print(f"edi sha256 {edi_sha}")
    print(f"locality {locality}")
    print(f"lines {len(lines)}")
    print(f"face billed ${face:,.2f}")
    print(f"priced allowed (if titled) ${priced_total:,.2f}")
    print(f"eligible AR ${eligible:,.2f}  title_bound={assignment.bound}")
    print(f"advance {args.advance_rate}% ${advance:,.2f}")
    print(f"digest {packet['packet_digest']}")


if __name__ == "__main__":
    main()
