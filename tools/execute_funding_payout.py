#!/usr/bin/env python3
"""Authorize and (sandbox) execute an ACH CCD payout from a borrowing-base packet.

Does not price claims. Amount comes only from authorize_funding().
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pfs.funding_authorization import AuthorizationError, authorize_funding
from pfs.payout_adapter import PayoutAdapter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packet", required=True)
    ap.add_argument("--mode", default="sandbox", choices=["sandbox", "live"])
    ap.add_argument("--provider-npi", required=True)
    ap.add_argument("--receiving-account-id", required=True)
    ap.add_argument("--originating-account-id", required=True)
    ap.add_argument("--capital-approval-id", required=True)
    ap.add_argument("--claim-schedule-hash", default="")
    ap.add_argument("--disclosure-receipt-hash", default="")
    ap.add_argument("--verifier-passed", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    packet = json.loads(Path(args.packet).read_text())
    live_creds = bool(os.environ.get("MODERN_TREASURY_API_KEY"))
    try:
        auth = authorize_funding(
            packet,
            mode=args.mode,
            provider_npi=args.provider_npi,
            receiving_account_id=args.receiving_account_id,
            originating_account_id=args.originating_account_id,
            capital_approval_id=args.capital_approval_id,
            claim_schedule_hash=args.claim_schedule_hash or None,
            disclosure_receipt_hash=args.disclosure_receipt_hash or None,
            live_credentials_present=live_creds,
            verifier_passed=args.verifier_passed,
        )
    except AuthorizationError as exc:
        print(f"AUTHORIZATION BLOCKED: {exc}")
        sys.exit(2)

    print("FUND BUTTON AMOUNT (from authorization, not UI copy):")
    print(f"  Verified receivables: ${auth.eligible_ar:,.2f}")
    print(f"  Available advance:    ${auth.advance_amount:,.2f} ({auth.advance_cents} cents)")
    print(f"  Reserve:              ${auth.reserve_amount:,.2f}")
    print(f"  Mode:                 {auth.mode}")
    print(f"  Idempotency:          {auth.idempotency_key}")

    adapter = PayoutAdapter(live_credentials={"api_key": os.environ.get("MODERN_TREASURY_API_KEY")} if live_creds else {})
    try:
        receipt = adapter.execute(auth, originating_account_id=args.originating_account_id)
    except AuthorizationError as exc:
        print(f"PAYOUT BLOCKED: {exc}")
        sys.exit(3)

    payload = {"authorization": auth.to_dict(), "settlement": receipt.to_dict()}
    print(json.dumps(payload, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
