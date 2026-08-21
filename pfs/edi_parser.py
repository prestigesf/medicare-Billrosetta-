"""Parse a sanitized X12 837P into priceable service lines."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Parsed837Line:
    line_id: str
    claim_control_number: str
    billing_npi: str
    dos: str
    cpt_hcpcs: str
    modifiers: List[str]
    pos: str
    billed_amount: float
    units: float
    raw_segment: str
    raw_segment_hash: str


class EDI837Parser:
    def __init__(self, raw_content: str):
        if len(raw_content) < 106 or not raw_content.startswith("ISA"):
            raise ValueError("Invalid X12 payload: missing or malformed ISA envelope.")
        self.element_sep = raw_content[3]
        self.component_sep = raw_content[104]
        self.segment_term = raw_content[105]
        self.raw_content = raw_content

    def parse(self) -> List[Parsed837Line]:
        lines: List[Parsed837Line] = []
        segments = [s.strip() for s in self.raw_content.split(self.segment_term) if s.strip()]

        current_npi = ""
        current_ccn = ""
        current_pos = "11"
        current_dos = "2026-01-01"
        line_counter = 1

        for seg in segments:
            parts = seg.split(self.element_sep)
            tag = parts[0].strip()

            if tag == "NM1" and len(parts) > 9:
                if parts[1].strip() == "85" and parts[8].strip() == "XX":
                    current_npi = parts[9].strip()

            elif tag == "CLM" and len(parts) > 1:
                current_ccn = parts[1].strip()
                if len(parts) > 5 and parts[5]:
                    sub = parts[5].split(self.component_sep)
                    if sub and sub[0].strip():
                        current_pos = sub[0].strip()

            elif tag == "DTP" and len(parts) > 3:
                if parts[1].strip() in ("472", "150", "431"):
                    raw_date = parts[3].strip()
                    if len(raw_date) == 8:
                        current_dos = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

            elif tag == "SV1" and len(parts) > 2:
                comp = parts[1].split(self.component_sep)
                cpt = comp[1].strip().upper() if len(comp) > 1 else comp[0].strip().upper()
                mods = [m.strip().upper() for m in comp[2:] if m.strip()]
                try:
                    billed = float(parts[2].strip() or "0.0")
                except ValueError:
                    billed = 0.0
                try:
                    units = float(parts[4].strip() or "1.0") if len(parts) > 4 and parts[4].strip() else 1.0
                except ValueError:
                    units = 1.0

                lines.append(
                    Parsed837Line(
                        line_id=f"EDI837-{line_counter:05d}",
                        claim_control_number=current_ccn,
                        billing_npi=current_npi,
                        dos=current_dos,
                        cpt_hcpcs=cpt,
                        modifiers=mods,
                        pos=current_pos,
                        billed_amount=billed,
                        units=units,
                        raw_segment=seg,
                        raw_segment_hash=hashlib.sha256(seg.encode("utf-8")).hexdigest(),
                    )
                )
                line_counter += 1

        return lines
