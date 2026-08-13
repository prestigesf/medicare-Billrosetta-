"""The audit ledger: tamper evidence, PHI handling, and round-tripping.

The properties that make a ledger worth having: altering a past entry is
detectable, the file proves its own integrity when re-read, and no identifier
is stored in the clear.
"""
import json
from datetime import date

import pytest

from pfs.ledger import (
    GENESIS,
    SourceRecord,
    blind,
    canonical,
    new_ledger,
    read_ledger,
    record_audit,
    sha256_text,
)


def ledger_with(count=3):
    ledger = new_ledger(
        sources=[SourceRecord("PPRRVU", "cms-file", "PPRRVU2026_Jul", "a" * 64)],
        parameters={"materiality_multiple": "1.5"},
    )
    for i in range(count):
        ledger.append(
            claim_id=f"CLM{i:04d}",
            cpt_code="99214",
            modifier="",
            service_date="2026-03-14",
            units=1,
            paid_amount=340.00 + i,
            benchmark=125.23,
            variance=214.77 + i,
            rate_source="cms-pfs:2026-RVU26C:10112-AL-00",
            derivation="worked arithmetic here",
            unavailable_reason=None,
        )
    return ledger


# --- the chain ---------------------------------------------------------------

def test_first_entry_anchors_to_genesis():
    ledger = ledger_with(1)
    assert ledger.entries[0].previous_hash == GENESIS


def test_each_entry_chains_to_the_one_before():
    ledger = ledger_with(3)
    for earlier, later in zip(ledger.entries, ledger.entries[1:]):
        assert later.previous_hash == earlier.entry_hash


def test_an_intact_chain_verifies():
    result = ledger_with(5).verify()
    assert result["intact"]
    assert result["entries"] == 5
    assert result["broken_at"] is None


def test_altering_a_past_entry_is_detected():
    """The whole point: a changed figure cannot pass silently."""
    ledger = ledger_with(5)
    ledger.entries[2].paid_amount = 1.00

    result = ledger.verify()
    assert not result["intact"]
    assert result["broken_at"] == 2
    assert "altered" in result["detail"]


def test_rehashing_the_altered_entry_still_breaks_the_chain():
    """Recomputing one entry's own hash does not repair what follows it."""
    ledger = ledger_with(5)
    ledger.entries[2].paid_amount = 1.00
    ledger.entries[2].entry_hash = ledger.entries[2].compute_hash()

    result = ledger.verify()
    assert not result["intact"]
    assert result["broken_at"] == 3


def test_removing_an_entry_is_detected():
    """A deletion is caught as a numbering gap, before the chain even fails."""
    ledger = ledger_with(5)
    del ledger.entries[2]

    result = ledger.verify()
    assert not result["intact"]
    assert result["broken_at"] == 2
    assert "removed or reordered" in result["detail"]


def test_reordering_entries_is_detected():
    ledger = ledger_with(5)
    ledger.entries[1], ledger.entries[3] = ledger.entries[3], ledger.entries[1]

    result = ledger.verify()
    assert not result["intact"]
    assert "removed or reordered" in result["detail"]


def test_appending_after_the_fact_extends_the_same_chain():
    ledger = ledger_with(2)
    head_before = ledger.head
    entry = ledger.append(
        claim_id="CLM9999", cpt_code="71046", modifier="26",
        service_date="2026-03-14", units=1, paid_amount=185.00,
        benchmark=9.54, variance=175.46, rate_source="cms-pfs:x",
        derivation="d", unavailable_reason=None,
    )
    assert entry.previous_hash == head_before
    assert ledger.verify()["intact"]


# --- protected health information --------------------------------------------

def test_claim_identifiers_are_never_stored_in_the_clear():
    ledger = ledger_with(3)
    serialised = json.dumps(ledger.manifest())

    assert "CLM0000" not in serialised
    assert "CLM0001" not in serialised
    assert all(len(entry.claim_ref) == 64 for entry in ledger.entries)


def test_an_identifier_you_hold_can_still_be_checked():
    """Blinded, not omitted — a holder can confirm a claim they already know."""
    ledger = ledger_with(3)

    assert ledger.contains("CLM0001")
    assert not ledger.contains("CLM9999")


def test_two_runs_blind_the_same_identifier_differently():
    """Per-run salt, so ledgers cannot be cross-referenced by identifier."""
    a, b = ledger_with(1), ledger_with(1)
    assert a.salt != b.salt
    assert a.entries[0].claim_ref != b.entries[0].claim_ref


def test_blinding_is_stable_within_a_run():
    ledger = ledger_with(1)
    assert blind("CLM0000", ledger.salt) == ledger.entries[0].claim_ref


# --- the manifest ------------------------------------------------------------

def test_manifest_hashes_its_own_payload():
    manifest = ledger_with(3).manifest()
    assert manifest["payload_sha256"] == sha256_text(canonical(manifest["payload"]))


def test_manifest_pins_its_sources_and_parameters():
    manifest = ledger_with(1).manifest()
    payload = manifest["payload"]

    assert payload["sources"][0]["name"] == "PPRRVU"
    assert payload["sources"][0]["sha256"] == "a" * 64
    assert payload["parameters"]["materiality_multiple"] == "1.5"


def test_round_trip_preserves_the_chain(tmp_path):
    original = ledger_with(4)
    path = original.write(tmp_path / "ledger.json")
    reloaded = read_ledger(path)

    assert reloaded.head == original.head
    assert reloaded.verify()["intact"]
    assert reloaded.run_id == original.run_id
    assert len(reloaded.entries) == 4


def test_a_tampered_file_is_refused_on_read(tmp_path):
    """Editing the JSON directly must not load quietly."""
    path = ledger_with(3).write(tmp_path / "ledger.json")
    raw = json.loads(path.read_text())
    raw["payload"]["entries"][1]["paid_amount"] = "0.01"
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError, match="does not match"):
        read_ledger(path)


def test_a_tampered_file_that_also_repairs_the_manifest_still_fails_verify(tmp_path):
    """Fixing the outer hash does not fix the chain underneath it."""
    path = ledger_with(3).write(tmp_path / "ledger.json")
    raw = json.loads(path.read_text())
    raw["payload"]["entries"][1]["paid_amount"] = "0.01"
    raw["payload_sha256"] = sha256_text(canonical(raw["payload"]))
    path.write_text(json.dumps(raw))

    reloaded = read_ledger(path)          # manifest hash now agrees
    assert not reloaded.verify()["intact"]  # the chain does not
    assert reloaded.verify()["broken_at"] == 1


def test_canonical_form_is_stable_across_key_order():
    a = {"b": "2", "a": "1"}
    b = {"a": "1", "b": "2"}
    assert canonical(a) == canonical(b)


# --- recording a real audit ---------------------------------------------------

def test_records_a_portfolio_audit():
    from pfs.audit import ClaimLine, PortfolioAudit
    from pfs.audit import AuditedLine
    from pfs.models import Setting

    claim = ClaimLine(
        line_number=1, cpt_code="99214", service_date=date(2026, 3, 14),
        paid_amount=340.00, setting=Setting.NON_FACILITY, claim_id="CLM1",
        provider="Clinic",
    )
    audit = PortfolioAudit(lines=[
        AuditedLine(claim=claim, benchmark=125.23, rate_source="cms-pfs:x",
                    derivation="d"),
        AuditedLine(claim=claim, unavailable_reason="facility charge"),
    ])

    ledger = record_audit(audit, parameters={"period": "2026Q1"})

    assert len(ledger.entries) == 2
    assert ledger.verify()["intact"]
    assert ledger.entries[0].benchmark == 125.23
    assert ledger.entries[1].benchmark is None
    assert ledger.entries[1].unavailable_reason == "facility charge"
