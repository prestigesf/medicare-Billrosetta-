"""Spreadsheet loading, header matching, and layouts declared as JSON."""
import json

import pytest

from pfs.loaders import ColumnMap, FileFormatError, load_gpcis, load_rvus, load_zip_crosswalk

openpyxl = pytest.importorskip("openpyxl")

RVU_FIELDS = {
    "cpt_code": "HCPCS",
    "work": "WORK RVU",
    "practice_expense_facility": "FACILITY PE RVU",
    "practice_expense_non_facility": "NON-FAC PE RVU",
    "malpractice": "MP RVU",
    "status_code": "STATUS CODE",
}


def write_xlsx(tmp_path, name, rows, banner_rows=0, sheet_title="Sheet1"):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = sheet_title
    for _ in range(banner_rows):
        sheet.append(["CMS copyright banner"])
    for row in rows:
        sheet.append(row)
    path = tmp_path / name
    book.save(path)
    return path


def test_loads_rvus_from_xlsx(tmp_path):
    path = write_xlsx(
        tmp_path, "rvu.xlsx",
        [
            ["HCPCS", "DESCRIPTION", "STATUS CODE", "WORK RVU", "NON-FAC PE RVU", "FACILITY PE RVU", "MP RVU"],
            ["99214", "Office visit", "A", 1.92, 1.73, 0.80, 0.14],
            ["99213", "Office visit", "A", 0.97, 1.11, 0.53, 0.07],
        ],
    )
    table = load_rvus(path, ColumnMap(fields=RVU_FIELDS))

    assert table["99214"].work == 1.92
    assert table["99214"].practice_expense_non_facility == 1.73
    assert table["99214"].status_code == "A"


def test_skip_rows_clears_cms_banner_rows(tmp_path):
    """CMS files carry copyright and title rows before the real header."""
    path = write_xlsx(
        tmp_path, "rvu.xlsx",
        [
            ["HCPCS", "STATUS CODE", "WORK RVU", "NON-FAC PE RVU", "FACILITY PE RVU", "MP RVU"],
            ["99214", "A", 1.92, 1.73, 0.80, 0.14],
        ],
        banner_rows=9,
    )
    table = load_rvus(path, ColumnMap(fields=RVU_FIELDS, skip_rows=9))
    assert table["99214"].work == 1.92


def test_wrong_skip_rows_fails_loudly_with_actual_headers(tmp_path):
    """Getting the offset wrong must name what it found, not load garbage."""
    path = write_xlsx(
        tmp_path, "rvu.xlsx",
        [["HCPCS", "STATUS CODE", "WORK RVU", "NON-FAC PE RVU", "FACILITY PE RVU", "MP RVU"],
         ["99214", "A", 1.92, 1.73, 0.80, 0.14]],
        banner_rows=9,
    )
    with pytest.raises(FileFormatError) as exc:
        load_rvus(path, ColumnMap(fields=RVU_FIELDS, skip_rows=0))
    assert "not in file" in str(exc.value)


def open_descriptors():
    """Currently open file descriptors, as {fd: target path}."""
    import os

    fds = {}
    for entry in os.listdir("/proc/self/fd"):
        try:
            fds[entry] = os.readlink(f"/proc/self/fd/{entry}")
        except OSError:
            continue
    return fds


@pytest.mark.skipif(
    not __import__("pathlib").Path("/proc/self/fd").exists(),
    reason="requires /proc",
)
def test_failed_load_does_not_leak_the_file_handle(tmp_path):
    """A load that raises must still close the workbook.

    read_only mode holds an open handle, and the row generator can be
    abandoned mid-iteration by an exception on a bad column. Descriptors are
    counted directly rather than waiting for a ResourceWarning, because that
    warning surfaces at garbage-collection time and lands on whichever
    unrelated test happens to be running.
    """
    path = write_xlsx(tmp_path, "rvu.xlsx", [["WRONG HEADER"], ["99214"]])

    before = open_descriptors()
    with pytest.raises(FileFormatError):
        load_rvus(path, ColumnMap(fields=RVU_FIELDS))
    after = open_descriptors()

    leaked = [
        target for fd, target in after.items()
        if fd not in before and path.name in target
    ]
    assert not leaked, f"failed load left {path.name} open: {leaked}"


def test_header_matching_tolerates_case_and_spacing(tmp_path):
    """CMS varies capitalisation and internal spacing between releases."""
    path = write_xlsx(
        tmp_path, "rvu.xlsx",
        [["hcpcs", "Status  Code", "Work RVU", "Non-Fac PE RVU", "Facility PE RVU", "MP  RVU"],
         ["99214", "A", 1.92, 1.73, 0.80, 0.14]],
    )
    table = load_rvus(path, ColumnMap(fields=RVU_FIELDS))
    assert table["99214"].malpractice == 0.14


def test_numeric_cells_survive_spreadsheet_typing(tmp_path):
    """A code stored as a number must not arrive as '99214.0'."""
    path = write_xlsx(
        tmp_path, "gpci.xlsx",
        [["LOCALITY", "LOCALITY NAME", "PW GPCI", "PE GPCI", "MP GPCI"],
         ["01-05", "San Francisco", 1.07, 1.38, 0.48]],
    )
    table = load_gpcis(
        path,
        ColumnMap(fields={
            "locality_id": "LOCALITY", "locality_name": "LOCALITY NAME",
            "work": "PW GPCI", "practice_expense": "PE GPCI", "malpractice": "MP GPCI",
        }),
    )
    assert table["01-05"].work == 1.07


def test_zip_crosswalk_from_xlsx(tmp_path):
    path = write_xlsx(
        tmp_path, "zips.xlsx",
        [["ZIP CODE", "LOCALITY"], ["94110", "01-05"], ["95814", "01-99"]],
    )
    table = load_zip_crosswalk(
        path, ColumnMap(fields={"zip_code": "ZIP CODE", "locality_id": "LOCALITY"})
    )
    assert table == {"94110": "01-05", "95814": "01-99"}


def test_blank_rows_in_spreadsheet_are_skipped(tmp_path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["LOCALITY", "LOCALITY NAME", "PW GPCI", "PE GPCI", "MP GPCI"])
    sheet.append(["01-05", "San Francisco", 1.07, 1.38, 0.48])
    sheet.append([None, None, None, None, None])
    sheet.append(["01-99", "Rest of California", 1.005, 1.05, 0.60])
    path = tmp_path / "gpci.xlsx"
    book.save(path)

    table = load_gpcis(
        path,
        ColumnMap(fields={
            "locality_id": "LOCALITY", "locality_name": "LOCALITY NAME",
            "work": "PW GPCI", "practice_expense": "PE GPCI", "malpractice": "MP GPCI",
        }),
    )
    assert set(table) == {"01-05", "01-99"}


def test_column_map_round_trips_through_json(tmp_path):
    spec = {
        "skip_rows": 9,
        "sheet": "RVU",
        "fields": {**RVU_FIELDS},
    }
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(spec))

    colmap = ColumnMap.from_json(path)
    assert colmap.skip_rows == 9
    assert colmap.sheet == "RVU"
    assert colmap.fields["work"] == "WORK RVU"


def test_json_layout_supports_fixed_width_offsets(tmp_path):
    """Offsets are written as two-element lists and must become tuples."""
    path = tmp_path / "layout.json"
    path.write_text(json.dumps({
        "fixed_width": True,
        "fields": {"cpt_code": [0, 5], "work": [7, 11]},
    }))

    colmap = ColumnMap.from_json(path)
    assert colmap.fixed_width is True
    assert colmap.fields["cpt_code"] == (0, 5)


def test_shipped_candidate_layouts_are_wellformed():
    """The candidate layouts must at least parse and cover required fields."""
    from pathlib import Path

    layouts = Path(__file__).resolve().parent.parent / "layouts"

    rvu = ColumnMap.from_json(layouts / "candidate_pprrvu_2026.json")
    rvu.require(
        "cpt_code", "work", "practice_expense_facility",
        "practice_expense_non_facility", "malpractice", "status_code",
    )

    gpci = ColumnMap.from_json(layouts / "candidate_gpci_2026.json")
    gpci.require("locality_id", "locality_name", "work", "practice_expense", "malpractice")
