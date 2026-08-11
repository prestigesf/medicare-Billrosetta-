"""Loading CMS files: both layouts, and every way a file is refused.

Fixtures are synthetic. What's verified is that a declared ColumnMap reads a
file correctly, and that anything ambiguous is rejected loudly rather than
loaded quietly.
"""
import pytest

from pfs import Setting
from pfs.loaders import ColumnMap, FileFormatError, load_gpcis, load_rvus, load_zip_crosswalk

RVU_CSV = """HCPCS,DESC,WORK RVU,PE FAC,PE NONFAC,MP RVU,STATUS
99213,Office visit low,0.97,0.53,1.11,0.07,A
99214,Office visit moderate,1.92,0.80,1.73,0.14,A
99211,Bundled thing,0.00,0.00,0.00,0.00,B
0001T,Facility only,2.50,1.10,,0.20,A
"""

RVU_MAP = ColumnMap(
    fields={
        "cpt_code": "HCPCS",
        "work": "WORK RVU",
        "practice_expense_facility": "PE FAC",
        "practice_expense_non_facility": "PE NONFAC",
        "malpractice": "MP RVU",
        "status_code": "STATUS",
    }
)

GPCI_CSV = """MAC,LOCALITY,NAME,PW GPCI,PE GPCI,MP GPCI
01112,01-05,San Francisco,1.070,1.380,0.480
01112,01-99,Rest of California,1.005,1.050,0.600
"""

GPCI_MAP = ColumnMap(
    fields={
        "locality_id": "LOCALITY",
        "locality_name": "NAME",
        "work": "PW GPCI",
        "practice_expense": "PE GPCI",
        "malpractice": "MP GPCI",
    }
)

ZIP_CSV = """ZIP,LOCALITY
94110,01-05
95814,01-99
"""

ZIP_MAP = ColumnMap(fields={"zip_code": "ZIP", "locality_id": "LOCALITY"})


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return path


def test_loads_rvus_from_csv(tmp_path):
    table = load_rvus(write(tmp_path, "rvu.csv", RVU_CSV), RVU_MAP)

    assert set(table) == {"99213", "99214", "99211", "0001T"}
    assert table["99214"].work == 1.92
    assert table["99214"].practice_expense_non_facility == 1.73
    assert table["99214"].status_code == "A"
    assert table["99214"].is_priceable


def test_blank_pe_stays_none_and_is_not_zero(tmp_path):
    """0.00 and blank mean different things — priced at zero vs not priced."""
    table = load_rvus(write(tmp_path, "rvu.csv", RVU_CSV), RVU_MAP)

    assert table["0001T"].practice_expense_non_facility is None
    assert table["0001T"].practice_expense_for(Setting.NON_FACILITY) is None
    assert table["99211"].practice_expense_facility == 0.0


def test_status_code_survives_loading(tmp_path):
    table = load_rvus(write(tmp_path, "rvu.csv", RVU_CSV), RVU_MAP)
    assert not table["99211"].is_priceable
    assert "bundled" in table["99211"].status_meaning


def test_loads_fixed_width(tmp_path):
    fixed = (
        "HEADER LINE TO SKIP\n"
        "99214  1.92  0.80  1.73  0.14 A\n"
        "99213  0.97  0.53  1.11  0.07 A\n"
    )
    colmap = ColumnMap(
        fields={
            "cpt_code": (0, 5),
            "work": (7, 11),
            "practice_expense_facility": (13, 17),
            "practice_expense_non_facility": (19, 23),
            "malpractice": (25, 29),
            "status_code": (30, 31),
        },
        fixed_width=True,
        skip_rows=1,
    )
    table = load_rvus(write(tmp_path, "rvu.txt", fixed), colmap)

    assert table["99214"].work == 1.92
    assert table["99214"].malpractice == 0.14
    assert table["99214"].status_code == "A"


def test_wrong_column_name_names_the_available_columns(tmp_path):
    bad = ColumnMap(fields={**RVU_MAP.fields, "work": "WRK"})
    with pytest.raises(FileFormatError) as exc:
        load_rvus(write(tmp_path, "rvu.csv", RVU_CSV), bad)
    assert "WRK" in str(exc.value)
    assert "WORK RVU" in str(exc.value)


def test_unparseable_number_is_rejected_with_its_line(tmp_path):
    broken = RVU_CSV.replace("1.92", "N/A")
    with pytest.raises(FileFormatError) as exc:
        load_rvus(write(tmp_path, "rvu.csv", broken), RVU_MAP)
    assert "99214" in str(exc.value)


def test_blank_status_code_is_rejected(tmp_path):
    broken = RVU_CSV.replace("1.73,0.14,A", "1.73,0.14,")
    with pytest.raises(FileFormatError, match="blank status code"):
        load_rvus(write(tmp_path, "rvu.csv", broken), RVU_MAP)


def test_conflicting_duplicate_row_is_rejected(tmp_path):
    doubled = RVU_CSV + "99214,Office visit moderate,9.99,0.80,1.73,0.14,A\n"
    with pytest.raises(FileFormatError, match="conflicting duplicate"):
        load_rvus(write(tmp_path, "rvu.csv", doubled), RVU_MAP)


def test_identical_duplicate_row_is_tolerated(tmp_path):
    doubled = RVU_CSV + "99214,Office visit moderate,1.92,0.80,1.73,0.14,A\n"
    table = load_rvus(write(tmp_path, "rvu.csv", doubled), RVU_MAP)
    assert table["99214"].work == 1.92


def test_empty_file_is_rejected(tmp_path):
    with pytest.raises(FileFormatError):
        load_rvus(write(tmp_path, "rvu.csv", "HCPCS,WORK RVU\n"), RVU_MAP)


def test_missing_field_in_colmap_is_caught_before_reading(tmp_path):
    incomplete = ColumnMap(fields={"cpt_code": "HCPCS"})
    with pytest.raises(ValueError, match="missing required field"):
        load_rvus(write(tmp_path, "rvu.csv", RVU_CSV), incomplete)


def test_loads_gpcis(tmp_path):
    table = load_gpcis(write(tmp_path, "gpci.csv", GPCI_CSV), GPCI_MAP)

    assert table["01-05"].locality_name == "San Francisco"
    assert table["01-05"].work == 1.070
    assert table["01-05"].practice_expense == 1.380
    assert table["01-05"].malpractice == 0.480


def test_loads_zip_crosswalk(tmp_path):
    table = load_zip_crosswalk(write(tmp_path, "zip.csv", ZIP_CSV), ZIP_MAP)
    assert table == {"94110": "01-05", "95814": "01-99"}


def test_zip_mapped_to_two_localities_is_rejected(tmp_path):
    """Silently keeping one would price a whole region wrong."""
    conflicting = ZIP_CSV + "94110,01-99\n"
    with pytest.raises(FileFormatError, match="maps to both"):
        load_zip_crosswalk(write(tmp_path, "zip.csv", conflicting), ZIP_MAP)


def test_malformed_zip_is_rejected(tmp_path):
    broken = ZIP_CSV + "ABCDE,01-05\n"
    with pytest.raises(FileFormatError, match="not a 5-digit ZIP"):
        load_zip_crosswalk(write(tmp_path, "zip.csv", broken), ZIP_MAP)


def test_loaded_data_prices_end_to_end(tmp_path):
    """The point of the loaders: real files in, a real rate out."""
    from datetime import date

    from pfs import FeeSchedulePeriod, RateEngine

    rvus = load_rvus(write(tmp_path, "rvu.csv", RVU_CSV), RVU_MAP)
    gpcis = load_gpcis(write(tmp_path, "gpci.csv", GPCI_CSV), GPCI_MAP)
    zips = load_zip_crosswalk(write(tmp_path, "zip.csv", ZIP_CSV), ZIP_MAP)

    period = FeeSchedulePeriod(
        period_id="test",
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        conversion_factor=33.0,
        rvus=rvus,
        gpcis=gpcis,
    )
    result = RateEngine([period], zips).rate(
        "99214", "94110", Setting.NON_FACILITY, date(2026, 3, 14)
    )

    # (1.92*1.070 + 1.73*1.380 + 0.14*0.480) * 33.00
    # = (2.05440 + 2.38740 + 0.06720) * 33.00 = 4.50900 * 33.00 = 148.797 -> 148.80
    assert result.allowed_amount == 148.80
    assert result.source == "cms-pfs:test:01-05"
