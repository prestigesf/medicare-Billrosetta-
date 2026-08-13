"""A tamper-evident record of an audit run.

A benefits director does not need a report. They need to be able to answer, a
year later and possibly to a regulator, three questions: what data was this
computed from, what rules were in force at the time, and has any of it changed
since. A PDF answers none of them.

Every run records its inputs by hash, its rate sources by version, and every
line's outcome, chained so that altering any earlier entry invalidates every
hash after it. The manifest hashes itself, and reading it back recomputes that
hash — the same discipline the evidence artifacts in this repo already follow,
applied to the thing a customer receives.

**No protected health information enters the ledger.** Claim and member
identifiers are stored as salted digests, never in the clear. The ledger is
meant to be handed to a broker, an auditor or opposing counsel; anything in it
should be safe in all three hands. The salt lives with the run, so a holder of
the ledger can verify a claim id they already possess, and cannot enumerate
ids they do not.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

# The chain starts somewhere. This is the anchor for entry zero.
GENESIS = "0" * 64

# Bytes of salt used to blind claim identifiers.
SALT_BYTES = 16

# Read files a megabyte at a time when hashing them.
HASH_BLOCK_BYTES = 1 << 20

# Hex characters of a digest shown in a human-facing message. Enough to
# identify which hash is meant, short enough to read.
HASH_PREVIEW = 12

LEDGER_VERSION = "1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(HASH_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(payload: dict) -> str:
    """One byte-for-byte representation, so a hash is reproducible.

    Keys sorted, no incidental whitespace. Every key is a string — JSON coerces
    integer keys on write, and a payload that hashes differently after a
    round-trip makes the read-back check fail for reasons unrelated to
    tampering.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def blind(identifier: str, salt: str) -> str:
    """A salted digest of an identifier. Never reversible, still checkable."""
    return sha256_text(f"{salt}:{identifier}") if identifier else ""


@dataclass(frozen=True)
class SourceRecord:
    """One data source the run depended on, pinned by content."""

    name: str
    kind: str
    identifier: str
    sha256: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "identifier": self.identifier,
            "sha256": self.sha256 or "",
        }


@dataclass
class LedgerEntry:
    """One audited line, chained to the entry before it."""

    index: int
    claim_ref: str
    cpt_code: str
    modifier: str
    service_date: str
    units: int
    paid_amount: float
    benchmark: Optional[float]
    variance: Optional[float]
    rate_source: Optional[str]
    derivation: Optional[str]
    unavailable_reason: Optional[str]
    previous_hash: str
    entry_hash: str = ""

    def payload(self) -> dict:
        return {
            "index": str(self.index),
            "claim_ref": self.claim_ref,
            "cpt_code": self.cpt_code,
            "modifier": self.modifier,
            "service_date": self.service_date,
            "units": str(self.units),
            "paid_amount": f"{self.paid_amount:.2f}",
            "benchmark": "" if self.benchmark is None else f"{self.benchmark:.2f}",
            "variance": "" if self.variance is None else f"{self.variance:.2f}",
            "rate_source": self.rate_source or "",
            "derivation": self.derivation or "",
            "unavailable_reason": self.unavailable_reason or "",
            "previous_hash": self.previous_hash,
        }

    def compute_hash(self) -> str:
        return sha256_text(canonical(self.payload()))

    def as_dict(self) -> dict:
        return {**self.payload(), "entry_hash": self.entry_hash}


@dataclass
class AuditLedger:
    """The chained record of one audit run."""

    run_id: str
    created_utc: str
    salt: str
    sources: List[SourceRecord] = field(default_factory=list)
    parameters: Dict[str, str] = field(default_factory=dict)
    entries: List[LedgerEntry] = field(default_factory=list)

    @property
    def head(self) -> str:
        return self.entries[-1].entry_hash if self.entries else GENESIS

    def append(
        self,
        *,
        claim_id: str,
        cpt_code: str,
        modifier: str,
        service_date: str,
        units: int,
        paid_amount: float,
        benchmark: Optional[float],
        variance: Optional[float],
        rate_source: Optional[str],
        derivation: Optional[str],
        unavailable_reason: Optional[str],
    ) -> LedgerEntry:
        entry = LedgerEntry(
            index=len(self.entries),
            claim_ref=blind(claim_id, self.salt),
            cpt_code=cpt_code,
            modifier=modifier,
            service_date=service_date,
            units=units,
            paid_amount=paid_amount,
            benchmark=benchmark,
            variance=variance,
            rate_source=rate_source,
            derivation=derivation,
            unavailable_reason=unavailable_reason,
            previous_hash=self.head,
        )
        entry.entry_hash = entry.compute_hash()
        self.entries.append(entry)
        return entry

    # -- verification ---------------------------------------------------------

    def verify(self) -> dict:
        """Recompute the whole chain. Reports the first break, if any."""
        expected_previous = GENESIS
        for position, entry in enumerate(self.entries):
            if entry.index != position:
                return {
                    "intact": False,
                    "entries": len(self.entries),
                    "broken_at": position,
                    "detail": (
                        f"entry numbered {entry.index} sits at position "
                        f"{position}; an entry has been removed or reordered"
                    ),
                }
            if entry.previous_hash != expected_previous:
                return {
                    "intact": False,
                    "entries": len(self.entries),
                    "broken_at": entry.index,
                    "detail": (
                        f"entry {entry.index} follows {entry.previous_hash[:HASH_PREVIEW]}… "
                        f"but the chain is at {expected_previous[:HASH_PREVIEW]}…"
                    ),
                }
            recomputed = entry.compute_hash()
            if recomputed != entry.entry_hash:
                return {
                    "intact": False,
                    "entries": len(self.entries),
                    "broken_at": entry.index,
                    "detail": (
                        f"entry {entry.index} has been altered: stored hash "
                        f"{entry.entry_hash[:HASH_PREVIEW]}…, recomputed {recomputed[:HASH_PREVIEW]}…"
                    ),
                }
            expected_previous = entry.entry_hash

        return {
            "intact": True,
            "entries": len(self.entries),
            "broken_at": None,
            "head": self.head,
        }

    def contains(self, claim_id: str) -> bool:
        """Whether an identifier you already hold is in this ledger.

        Checkable without the ledger ever revealing which identifiers it
        covers — the point of blinding rather than omitting them.
        """
        reference = blind(claim_id, self.salt)
        return any(entry.claim_ref == reference for entry in self.entries)

    # -- serialisation --------------------------------------------------------

    def manifest(self) -> dict:
        body = {
            "ledger_version": LEDGER_VERSION,
            "run_id": self.run_id,
            "created_utc": self.created_utc,
            "salt": self.salt,
            "parameters": dict(self.parameters),
            "sources": [source.as_dict() for source in self.sources],
            "entry_count": str(len(self.entries)),
            "head": self.head,
            "entries": [entry.as_dict() for entry in self.entries],
        }
        return {"payload": body, "payload_sha256": sha256_text(canonical(body))}

    def write(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.manifest(), indent=2, sort_keys=True) + "\n")
        return path


def new_ledger(
    run_id: Optional[str] = None,
    sources: Sequence[SourceRecord] = (),
    parameters: Optional[Dict[str, str]] = None,
) -> AuditLedger:
    created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return AuditLedger(
        run_id=run_id or f"audit-{created}-{secrets.token_hex(4)}",
        created_utc=created,
        salt=secrets.token_hex(SALT_BYTES),
        sources=list(sources),
        parameters=dict(parameters or {}),
    )


def read_ledger(path: Union[str, Path]) -> AuditLedger:
    """Load a ledger and confirm the manifest hash still matches its payload."""
    raw = json.loads(Path(path).read_text())
    payload = raw["payload"]

    recomputed = sha256_text(canonical(payload))
    if recomputed != raw["payload_sha256"]:
        raise ValueError(
            f"Manifest hash does not match its contents: stored "
            f"{raw['payload_sha256'][:HASH_PREVIEW]}…, recomputed {recomputed[:HASH_PREVIEW]}…"
        )

    ledger = AuditLedger(
        run_id=payload["run_id"],
        created_utc=payload["created_utc"],
        salt=payload["salt"],
        sources=[
            SourceRecord(s["name"], s["kind"], s["identifier"], s["sha256"] or None)
            for s in payload["sources"]
        ],
        parameters=dict(payload["parameters"]),
    )
    for row in payload["entries"]:
        ledger.entries.append(LedgerEntry(
            index=int(row["index"]),
            claim_ref=row["claim_ref"],
            cpt_code=row["cpt_code"],
            modifier=row["modifier"],
            service_date=row["service_date"],
            units=int(row["units"]),
            paid_amount=float(row["paid_amount"]),
            benchmark=float(row["benchmark"]) if row["benchmark"] else None,
            variance=float(row["variance"]) if row["variance"] else None,
            rate_source=row["rate_source"] or None,
            derivation=row["derivation"] or None,
            unavailable_reason=row["unavailable_reason"] or None,
            previous_hash=row["previous_hash"],
            entry_hash=row["entry_hash"],
        ))
    return ledger


def record_audit(audit, sources: Sequence[SourceRecord] = (), parameters=None) -> AuditLedger:
    """Chain a completed PortfolioAudit into a ledger."""
    ledger = new_ledger(sources=sources, parameters=parameters)
    for line in audit.lines:
        ledger.append(
            claim_id=line.claim.claim_id,
            cpt_code=line.claim.cpt_code,
            modifier=line.claim.modifier,
            service_date=line.claim.service_date.isoformat(),
            units=line.claim.units,
            paid_amount=line.claim.paid_amount,
            benchmark=line.benchmark,
            variance=line.variance,
            rate_source=line.rate_source,
            derivation=line.derivation,
            unavailable_reason=line.unavailable_reason,
        )
    return ledger
