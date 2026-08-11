"""Load CMS data files into the engine's types.

CMS publishes the RVU, GPCI, and ZIP-locality files in layouts that vary by
year and by release format (CSV, fixed-width text, spreadsheet export). Rather
than hardcode one guessed layout, the mapping from file columns to fields is
*configuration*: a ColumnMap. Adopting a new file, or a new year's format, is a
ColumnMap change, not a code change.

That keeps invariant 2 intact — no CMS-specific layout knowledge lives in
executable engine code — and it means the first real file costs a config, not
a rewrite.

Every loader validates as it reads. A row that cannot be parsed is reported
with its line number and rejected. Nothing is silently coerced or defaulted,
because a bad rate that loads quietly is worse than a file that refuses.
"""
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

from .models import GPCI, RVUs

# A CSV field is addressed by header name; a fixed-width field by [start, end).
FieldSpec = Union[str, Tuple[int, int]]

# How many bad rows to list before truncating. A malformed file can produce
# thousands; the first handful is what tells you what went wrong.
MAX_PROBLEMS_SHOWN = 20


class FileFormatError(Exception):
    """The file could not be read under the supplied ColumnMap."""

    def __init__(self, path: Path, problems: Sequence[str]):
        self.path = path
        self.problems = list(problems)
        shown = "\n  ".join(self.problems[:MAX_PROBLEMS_SHOWN])
        hidden = len(self.problems) - MAX_PROBLEMS_SHOWN
        more = f"\n  ... and {hidden} more" if hidden > 0 else ""
        super().__init__(f"{path.name}: {len(self.problems)} problem(s)\n  {shown}{more}")


@dataclass(frozen=True)
class ColumnMap:
    """Where each field lives in a particular file.

    fields: field name -> header name (CSV) or (start, end) slice (fixed width)
    fixed_width: read by character offsets rather than delimiter
    skip_rows: leading rows to discard (banners, notes, blank lines)
    """

    fields: Dict[str, FieldSpec]
    fixed_width: bool = False
    skip_rows: int = 0
    encoding: str = "utf-8-sig"

    def require(self, *names: str) -> None:
        missing = [n for n in names if n not in self.fields]
        if missing:
            raise ValueError(f"ColumnMap is missing required field(s): {missing}")


def _rows(path: Path, colmap: ColumnMap) -> Iterator[Tuple[int, Dict[str, str]]]:
    """Yield (line number, {field: raw text}) for each data row."""
    text = path.read_text(encoding=colmap.encoding)
    lines = text.splitlines()[colmap.skip_rows:]

    if colmap.fixed_width:
        for offset, line in enumerate(lines, start=colmap.skip_rows + 1):
            if not line.strip():
                continue
            yield offset, {
                name: line[spec[0]:spec[1]].strip()
                for name, spec in colmap.fields.items()
            }
        return

    reader = csv.DictReader(lines)
    if reader.fieldnames is None:
        raise FileFormatError(path, ["file has no header row"])

    headers = {h.strip(): h for h in reader.fieldnames if h is not None}
    unknown = [spec for spec in colmap.fields.values() if spec not in headers]
    if unknown:
        raise FileFormatError(
            path,
            [f"column {c!r} not in file; available: {sorted(headers)}" for c in unknown],
        )

    for offset, row in enumerate(reader, start=colmap.skip_rows + 2):
        yield offset, {
            name: (row.get(headers[spec]) or "").strip()
            for name, spec in colmap.fields.items()
        }


def _number(raw: str, *, allow_blank: bool = False) -> Optional[float]:
    """Parse a numeric cell. Blank means absent, not zero — when permitted."""
    cleaned = raw.replace(",", "").replace("$", "").strip()
    if not cleaned:
        if allow_blank:
            return None
        raise ValueError("blank")
    return float(cleaned)


def load_rvus(path: Union[str, Path], colmap: ColumnMap) -> Dict[str, RVUs]:
    """Read the RVU file (PPRRVU) into {cpt_code: RVUs}."""
    path = Path(path)
    colmap.require(
        "cpt_code", "work", "practice_expense_facility",
        "practice_expense_non_facility", "malpractice", "status_code",
    )

    table: Dict[str, RVUs] = {}
    problems: List[str] = []

    for line_no, raw in _rows(path, colmap):
        code = raw["cpt_code"].upper()
        if not code:
            continue
        try:
            entry = RVUs(
                cpt_code=code,
                work=_number(raw["work"]),
                # A code priced in only one setting leaves the other blank.
                # That must stay None, never 0.0 — see MissingPracticeExpenseRVU.
                practice_expense_facility=_number(
                    raw["practice_expense_facility"], allow_blank=True
                ),
                practice_expense_non_facility=_number(
                    raw["practice_expense_non_facility"], allow_blank=True
                ),
                malpractice=_number(raw["malpractice"]),
                status_code=raw["status_code"].upper(),
            )
        except ValueError as exc:
            problems.append(f"line {line_no}, CPT {code}: {exc}")
            continue

        if not entry.status_code:
            problems.append(f"line {line_no}, CPT {code}: blank status code")
            continue
        if code in table and table[code] != entry:
            problems.append(f"line {line_no}, CPT {code}: conflicting duplicate row")
            continue

        table[code] = entry

    if problems:
        raise FileFormatError(path, problems)
    if not table:
        raise FileFormatError(path, ["no RVU rows parsed"])
    return table


def load_gpcis(path: Union[str, Path], colmap: ColumnMap) -> Dict[str, GPCI]:
    """Read the GPCI file into {locality_id: GPCI}."""
    path = Path(path)
    colmap.require(
        "locality_id", "locality_name", "work", "practice_expense", "malpractice"
    )

    table: Dict[str, GPCI] = {}
    problems: List[str] = []

    for line_no, raw in _rows(path, colmap):
        locality = raw["locality_id"].strip()
        if not locality:
            continue
        try:
            entry = GPCI(
                locality_id=locality,
                locality_name=raw["locality_name"] or locality,
                work=_number(raw["work"]),
                practice_expense=_number(raw["practice_expense"]),
                malpractice=_number(raw["malpractice"]),
            )
        except ValueError as exc:
            problems.append(f"line {line_no}, locality {locality}: {exc}")
            continue

        if locality in table and table[locality] != entry:
            problems.append(f"line {line_no}, locality {locality}: conflicting duplicate row")
            continue

        table[locality] = entry

    if problems:
        raise FileFormatError(path, problems)
    if not table:
        raise FileFormatError(path, ["no GPCI rows parsed"])
    return table


def load_zip_crosswalk(path: Union[str, Path], colmap: ColumnMap) -> Dict[str, str]:
    """Read the ZIP-to-locality crosswalk into {zip: locality_id}."""
    path = Path(path)
    colmap.require("zip_code", "locality_id")

    table: Dict[str, str] = {}
    problems: List[str] = []

    for line_no, raw in _rows(path, colmap):
        zip_code = raw["zip_code"].strip()[:5]
        locality = raw["locality_id"].strip()
        if not zip_code:
            continue
        if not locality:
            problems.append(f"line {line_no}, ZIP {zip_code}: blank locality")
            continue
        if not zip_code.isdigit() or len(zip_code) != 5:
            problems.append(f"line {line_no}: {zip_code!r} is not a 5-digit ZIP")
            continue
        if zip_code in table and table[zip_code] != locality:
            problems.append(
                f"line {line_no}, ZIP {zip_code}: maps to both "
                f"{table[zip_code]} and {locality}"
            )
            continue
        table[zip_code] = locality

    if problems:
        raise FileFormatError(path, problems)
    if not table:
        raise FileFormatError(path, ["no crosswalk rows parsed"])
    return table
