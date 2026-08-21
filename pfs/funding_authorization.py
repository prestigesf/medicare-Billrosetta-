"""Deterministic funding authorization from a verified borrowing-base packet.

The payment rail must never price, rate, or invent an amount. It consumes
this object only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


SPECIMEN_MARKERS = (
    "specimen",
    "sanitized",
    "not_a_real",
    "not-a-real",
    "demo",
    "fixture",
)


class AuthorizationError(Exception):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_specimen_path(path: Optional[str]) -> bool:
    if not path:
        return False
    lowered = path.lower()
    return any(marker in lowered for marker in SPECIMEN_MARKERS)


CENTS_PER_DOLLAR = 100


def _cents(amount: float) -> int:
    return int(round(float(amount) * CENTS_PER_DOLLAR))


def derive_advance_cents(rollup: Mapping[str, Any]) -> int:
    """Re-derive advance from the packet. Never accept a caller-chosen amount."""
    from decimal import Decimal, ROUND_HALF_UP

    base = Decimal(str(rollup["net_borrowing_base"]))
    rate_pct = Decimal(str(rollup["advance_rate_pct"]))
    stated_advance = Decimal(str(rollup["advance_amount_t0"]))
    stated_reserve = Decimal(str(rollup["reserve_amount"]))
    expected_advance = (base * rate_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if stated_advance != expected_advance:
        raise AuthorizationError(
            f"advance mismatch: packet {stated_advance} vs derived {expected_advance}"
        )
    if (stated_advance + stated_reserve) != base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        raise AuthorizationError("advance + reserve != net_borrowing_base")
    return _cents(float(stated_advance))


def idempotency_key(
    packet_digest: str,
    recipient_account_id: str,
    advance_cents: int,
    capital_approval_id: str,
) -> str:
    payload = (
        f"{packet_digest}|{recipient_account_id}|{advance_cents}|"
        f"{capital_approval_id}|ACH|CCD"
    )
    return _sha256_text(payload)


@dataclass(frozen=True)
class FundingAuthorization:
    packet_id: str
    packet_digest: str
    assignment_doc_hash: Optional[str]
    claim_schedule_hash: Optional[str]
    provider_npi: str
    receiving_account_id: str
    masked_destination: str
    jurisdiction: str
    disclosure_receipt_hash: Optional[str]
    capital_approval_id: str
    gross_face: float
    eligible_ar: float
    advance_rate_pct: float
    advance_amount: float
    advance_cents: int
    reserve_amount: float
    rail: str
    sec_code: str
    mode: str
    fixture_mode: str
    idempotency_key: str
    authorization_digest: str

    def to_dict(self) -> dict:
        return asdict(self)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorizationError(message)


def authorize_funding(
    packet: Mapping[str, Any],
    *,
    mode: str,
    provider_npi: str,
    receiving_account_id: str,
    originating_account_id: str,
    capital_approval_id: str,
    claim_schedule_hash: Optional[str] = None,
    disclosure_receipt_hash: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    assignment_path: Optional[str] = None,
    live_credentials_present: bool = False,
    verifier_passed: bool = False,
) -> FundingAuthorization:
    """Build an authorization or raise. Live mode is a hard-block set."""
    mode = mode.lower().strip()
    _require(mode in {"sandbox", "live"}, "mode must be sandbox or live")

    att = packet.get("eligibility_attestation") or {}
    rollup = packet.get("rollup") or {}
    fixture_mode = packet.get("fixture_mode") or ""
    title_assigned = bool(att.get("title_assigned"))
    assignment_hash = att.get("assignment_doc_hash")
    eligible = float(rollup.get("eligible_ar_allowed") or 0)
    advance_cents = derive_advance_cents(rollup)
    packet_digest = packet.get("packet_digest") or ""
    assignment_path = assignment_path or att.get("assignment_path")
    specimen = _is_specimen_path(assignment_path)

    _require(bool(packet_digest), "packet_digest required")
    _require(advance_cents >= 0, "advance cents cannot be negative")

    if eligible <= 0 or advance_cents == 0:
        raise AuthorizationError("zero eligible AR blocks authorization")
    if not title_assigned or not assignment_hash:
        raise AuthorizationError("unassigned title blocks authorization")

    if mode == "sandbox":
        _require(not live_credentials_present or specimen, "sandbox must not use live rail credentials against a live book")
    else:
        _require(verifier_passed, "live mode requires disk-backed verifier pass")
        _require(fixture_mode == "LIVE_PRODUCTION", "live mode requires fixture_mode=LIVE_PRODUCTION")
        _require(not specimen, "demo/specimen title is blocked from live payout")
        _require(bool(att.get("timely_filing_verified")), "live mode requires timely-filing verification")
        _require(bool(att.get("no_recoupment_block")), "live mode requires recoupment clearance")
        _require(bool(disclosure_receipt_hash), "live mode requires commercial-financing disclosure hash")
        _require(bool(capital_approval_id) and not str(capital_approval_id).upper().startswith("DEMO"), "live mode requires a real capital approval ID")
        _require(bool(claim_schedule_hash), "live mode requires hashed source claims/837")
        _require(bool(receiving_account_id) and not receiving_account_id.upper().startswith("DEMO"), "live mode requires a verified receiving account")
        _require(bool(originating_account_id) and not originating_account_id.upper().startswith("DEMO"), "live mode requires funded originating account")
        _require(live_credentials_present, "live mode requires live ACH credentials")
        if assignment_path:
            _require(Path(assignment_path).is_file(), "live assignment file missing on disk")

    _require(bool(provider_npi), "provider NPI required")
    _require(bool(receiving_account_id), "receiving account required")
    _require(bool(capital_approval_id), "capital approval ID required")

    masked = f"****{receiving_account_id[-4:]}" if len(receiving_account_id) >= 4 else "****"
    key = idempotency_key(packet_digest, receiving_account_id, advance_cents, capital_approval_id)
    auth_payload = {
        "packet_id": packet.get("packet_id"),
        "packet_digest": packet_digest,
        "assignment_doc_hash": assignment_hash,
        "claim_schedule_hash": claim_schedule_hash,
        "provider_npi": provider_npi,
        "receiving_account_id": receiving_account_id,
        "advance_cents": advance_cents,
        "capital_approval_id": capital_approval_id,
        "mode": mode,
        "idempotency_key": key,
        "rail": "ACH",
        "sec_code": "CCD",
    }
    digest = _sha256_text(json.dumps(auth_payload, sort_keys=True, separators=(",", ":")))

    return FundingAuthorization(
        packet_id=str(packet.get("packet_id")),
        packet_digest=packet_digest,
        assignment_doc_hash=assignment_hash,
        claim_schedule_hash=claim_schedule_hash,
        provider_npi=provider_npi,
        receiving_account_id=receiving_account_id,
        masked_destination=masked,
        jurisdiction=jurisdiction or str(packet.get("mac_jurisdiction") or ""),
        disclosure_receipt_hash=disclosure_receipt_hash,
        capital_approval_id=capital_approval_id,
        gross_face=float(rollup.get("total_face_billed") or 0),
        eligible_ar=eligible,
        advance_rate_pct=float(rollup["advance_rate_pct"]),
        advance_amount=float(rollup["advance_amount_t0"]),
        advance_cents=advance_cents,
        reserve_amount=float(rollup["reserve_amount"]),
        rail="ACH",
        sec_code="CCD",
        mode=mode,
        fixture_mode=fixture_mode,
        idempotency_key=key,
        authorization_digest=digest,
    )
