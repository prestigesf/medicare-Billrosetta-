"""ACH CCD adapter. Executes an already-authorized amount. Does not price."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from pfs.funding_authorization import AuthorizationError, FundingAuthorization

ID_PREFIX_LEN = 16


@dataclass(frozen=True)
class SettlementReceipt:
    settlement_id: str
    authorization_id: str
    authorization_digest: str
    packet_digest: str
    payment_order_id: str
    external_id: str
    idempotency_key: str
    amount_cents: int
    rail: str
    sec_code: str
    status: str
    timestamp: str
    settlement_receipt_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


class PayoutAdapter:
    def __init__(self, *, live_credentials: Optional[dict] = None):
        self.live_credentials = live_credentials or {}
        self._issued = {}

    def execute(self, auth: FundingAuthorization, *, originating_account_id: str) -> SettlementReceipt:
        if auth.rail != "ACH" or auth.sec_code != "CCD":
            raise AuthorizationError("adapter only executes ACH CCD")
        if auth.advance_cents <= 0:
            raise AuthorizationError("zero amount cannot be paid")

        if auth.idempotency_key in self._issued:
            return self._issued[auth.idempotency_key]

        if auth.mode == "live":
            if not self.live_credentials:
                raise AuthorizationError("live ACH credentials missing")
            raise AuthorizationError(
                "live Modern Treasury rail is not configured in this environment; "
                "refusing to invent a live payment order"
            )

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payment_order_id = "po_sandbox_" + auth.idempotency_key[:ID_PREFIX_LEN]
        external_id = "ext_" + auth.authorization_digest[:ID_PREFIX_LEN]
        settlement_id = "stl_" + auth.authorization_digest[:ID_PREFIX_LEN]
        body = {
            "settlement_id": settlement_id,
            "authorization_id": auth.authorization_digest,
            "authorization_digest": auth.authorization_digest,
            "packet_digest": auth.packet_digest,
            "payment_order_id": payment_order_id,
            "external_id": external_id,
            "idempotency_key": auth.idempotency_key,
            "amount_cents": auth.advance_cents,
            "rail": auth.rail,
            "sec_code": auth.sec_code,
            "status": "sandbox_accepted",
            "originating_account_id": originating_account_id,
        }
        receipt_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        receipt = SettlementReceipt(
            settlement_id=settlement_id,
            authorization_id=auth.authorization_digest,
            authorization_digest=auth.authorization_digest,
            packet_digest=auth.packet_digest,
            payment_order_id=payment_order_id,
            external_id=external_id,
            idempotency_key=auth.idempotency_key,
            amount_cents=auth.advance_cents,
            rail=auth.rail,
            sec_code=auth.sec_code,
            status="sandbox_accepted",
            timestamp=ts,
            settlement_receipt_hash=receipt_hash,
        )
        self._issued[auth.idempotency_key] = receipt
        return receipt
