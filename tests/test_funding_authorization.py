"""Funding authorization gates. Amounts are derived, never hard-coded."""
from __future__ import annotations

import pytest

from pfs.funding_authorization import (
    AuthorizationError,
    authorize_funding,
    derive_advance_cents,
    idempotency_key,
)
from pfs.payout_adapter import PayoutAdapter


def _packet(**overrides):
    base = {
        "packet_id": "BB-TEST",
        "fixture_mode": "PRODUCTION_BOOK",
        "packet_digest": "0xabc123",
        "mac_jurisdiction": "10112-AL-00",
        "eligibility_attestation": {
            "title_assigned": True,
            "assignment_doc_hash": "0" * 64,
            "assignment_path": "evidence/docs/provider_assignment_specimen_sanitized.txt",
            "timely_filing_verified": False,
            "no_recoupment_block": False,
        },
        "rollup": {
            "total_face_billed": 467518.99,
            "eligible_ar_allowed": 35601.32,
            "haircuts_total": 431917.67,
            "net_borrowing_base": 35601.32,
            "advance_rate_pct": 76.6,
            "advance_amount_t0": 27270.61,
            "reserve_amount": 8330.71,
        },
    }
    base.update(overrides)
    if "eligibility_attestation" in overrides:
        att = dict(base["eligibility_attestation"])
        att.update(overrides["eligibility_attestation"])
        base["eligibility_attestation"] = att
    if "rollup" in overrides:
        roll = dict(
            {
                "total_face_billed": 467518.99,
                "eligible_ar_allowed": 35601.32,
                "haircuts_total": 431917.67,
                "net_borrowing_base": 35601.32,
                "advance_rate_pct": 76.6,
                "advance_amount_t0": 27270.61,
                "reserve_amount": 8330.71,
            }
        )
        roll.update(overrides["rollup"])
        base["rollup"] = roll
    return base


AUTH_KW = dict(
    provider_npi="1999999992",
    receiving_account_id="acct_recv_sandbox",
    originating_account_id="acct_orig_sandbox",
    capital_approval_id="DEMO-CAP-001",
)


def test_zero_eligible_ar_blocks():
    packet = _packet(rollup={"eligible_ar_allowed": 0.0, "net_borrowing_base": 0.0, "advance_amount_t0": 0.0, "reserve_amount": 0.0, "advance_rate_pct": 76.6})
    with pytest.raises(AuthorizationError, match="zero eligible AR"):
        authorize_funding(packet, mode="sandbox", **AUTH_KW)


def test_unassigned_title_blocks():
    packet = _packet(eligibility_attestation={"title_assigned": False, "assignment_doc_hash": None})
    with pytest.raises(AuthorizationError, match="unassigned title"):
        authorize_funding(packet, mode="sandbox", **AUTH_KW)


def test_specimen_allowed_only_in_sandbox():
    packet = _packet()
    auth = authorize_funding(packet, mode="sandbox", **AUTH_KW)
    assert auth.advance_cents == derive_advance_cents(packet["rollup"])
    assert auth.advance_cents == 2727061
    with pytest.raises(AuthorizationError, match="specimen|LIVE_PRODUCTION|demo"):
        authorize_funding(
            packet,
            mode="live",
            verifier_passed=True,
            live_credentials_present=True,
            claim_schedule_hash="ab",
            disclosure_receipt_hash="cd",
            **{**AUTH_KW, "receiving_account_id": "acct_live_1", "originating_account_id": "acct_live_2", "capital_approval_id": "CAP-REAL-1"},
        )


def test_demo_fixture_blocked_from_live():
    packet = _packet(fixture_mode="PRODUCTION_BOOK")
    with pytest.raises(AuthorizationError):
        authorize_funding(
            packet,
            mode="live",
            verifier_passed=True,
            live_credentials_present=True,
            claim_schedule_hash="ab",
            disclosure_receipt_hash="cd",
            **AUTH_KW,
        )


def test_live_requires_timely_filing():
    packet = _packet(
        fixture_mode="LIVE_PRODUCTION",
        eligibility_attestation={
            "title_assigned": True,
            "assignment_doc_hash": "a" * 64,
            "assignment_path": "evidence/docs/real_assignment.pdf",
            "timely_filing_verified": False,
            "no_recoupment_block": True,
        },
    )
    with pytest.raises(AuthorizationError, match="timely-filing"):
        authorize_funding(
            packet,
            mode="live",
            verifier_passed=True,
            live_credentials_present=True,
            claim_schedule_hash="ab",
            disclosure_receipt_hash="cd",
            assignment_path="evidence/docs/real_assignment.pdf",
            provider_npi="1999999992",
            receiving_account_id="acct_live_recv",
            originating_account_id="acct_live_orig",
            capital_approval_id="CAP-REAL-1",
        )


def test_live_requires_recoupment_clearance():
    packet = _packet(
        fixture_mode="LIVE_PRODUCTION",
        eligibility_attestation={
            "title_assigned": True,
            "assignment_doc_hash": "a" * 64,
            "assignment_path": "evidence/docs/real_assignment.pdf",
            "timely_filing_verified": True,
            "no_recoupment_block": False,
        },
    )
    with pytest.raises(AuthorizationError, match="recoupment"):
        authorize_funding(
            packet,
            mode="live",
            verifier_passed=True,
            live_credentials_present=True,
            claim_schedule_hash="ab",
            disclosure_receipt_hash="cd",
            assignment_path="evidence/docs/real_assignment.pdf",
            provider_npi="1999999992",
            receiving_account_id="acct_live_recv",
            originating_account_id="acct_live_orig",
            capital_approval_id="CAP-REAL-1",
        )


def test_payout_amount_is_derived_not_hardcoded():
    packet = _packet()
    derived = derive_advance_cents(packet["rollup"])
    assert derived == int(round(27270.61 * 100))
    packet_bad = _packet(rollup={"advance_amount_t0": 99999.00})
    with pytest.raises(AuthorizationError, match="advance mismatch"):
        derive_advance_cents(packet_bad["rollup"])


def test_same_authorization_same_idempotency_key():
    packet = _packet()
    a = authorize_funding(packet, mode="sandbox", **AUTH_KW)
    b = authorize_funding(packet, mode="sandbox", **AUTH_KW)
    assert a.idempotency_key == b.idempotency_key
    assert a.idempotency_key == idempotency_key(
        packet["packet_digest"],
        AUTH_KW["receiving_account_id"],
        a.advance_cents,
        AUTH_KW["capital_approval_id"],
    )
    adapter = PayoutAdapter()
    r1 = adapter.execute(a, originating_account_id=AUTH_KW["originating_account_id"])
    r2 = adapter.execute(b, originating_account_id=AUTH_KW["originating_account_id"])
    assert r1.payment_order_id == r2.payment_order_id
    assert r1.amount_cents == a.advance_cents
