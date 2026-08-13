"""Auditing a claims portfolio.

The properties that make this evidence rather than an opinion: unmeasured
dollars never become a finding, coverage is reported honestly, and units scale
the benchmark.
"""
from datetime import date
from pathlib import Path

import pytest

from pfs import FeeSchedulePeriod, RateEngine, Setting
from pfs.audit import (
    ClaimLine,
    ClaimsFormatError,
    audit_claims,
    categorise,
    read_claims,
)
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus
from pfs.locality import LocalityDirectory

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"
RVU_FILE = DATA / "PPRRVU2026_Jul_nonQPP.csv"
GPCI_FILE = DATA / "GPCI2026.csv"

pytestmark = pytest.mark.skipif(
    not (RVU_FILE.exists() and GPCI_FILE.exists()),
    reason="full CMS release not present",
)

DOS = date(2026, 3, 14)
ALABAMA = "10112-AL-00"


@pytest.fixture(scope="module")
def engine_and_directory():
    layout = ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
    rvus = load_rvus(RVU_FILE, layout)
    gpcis = load_gpcis(GPCI_FILE, ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))
    period = FeeSchedulePeriod(
        "2026-RVU26C", date(2026, 1, 1), date(2026, 12, 31),
        load_conversion_factor(RVU_FILE, layout), rvus, gpcis,
    )
    return RateEngine([period], {}), LocalityDirectory(gpcis)


def claim(code="99214", paid=340.0, *, units=1, modifier="", provider="Clinic",
          revenue_code="", locality=ALABAMA, when=DOS, number=1,
          setting=Setting.NON_FACILITY):
    return ClaimLine(
        line_number=number, cpt_code=code, service_date=when, paid_amount=paid,
        setting=setting, modifier=modifier, units=units, provider=provider,
        locality_id=locality, revenue_code=revenue_code,
    )


# --- the benchmark -----------------------------------------------------------

def test_variance_is_paid_minus_benchmark(engine_and_directory):
    """A plan's exposure is what it paid, not what was billed."""
    engine, directory = engine_and_directory
    audit = audit_claims([claim(paid=340.0)], engine, directory)
    line = audit.lines[0]

    assert line.benchmarked
    assert line.benchmark == 125.23
    assert line.variance == 214.77
    assert line.multiple_of_medicare == 2.72


def test_units_scale_the_benchmark(engine_and_directory):
    """Four units of therapy are measured against four units of Medicare."""
    engine, directory = engine_and_directory
    one = audit_claims([claim("97110", paid=180.0, units=1)], engine, directory).lines[0]
    four = audit_claims([claim("97110", paid=720.0, units=4)], engine, directory).lines[0]

    assert four.benchmark == pytest.approx(one.benchmark * 4, abs=0.02)
    assert four.multiple_of_medicare == pytest.approx(one.multiple_of_medicare, abs=0.02)


def test_paying_under_medicare_reports_a_negative_variance(engine_and_directory):
    engine, directory = engine_and_directory
    line = audit_claims([claim(paid=100.0)], engine, directory).lines[0]
    assert line.variance == -25.23


# --- unmeasured dollars stay unmeasured --------------------------------------

def test_facility_lines_are_named_not_benchmarked(engine_and_directory):
    engine, directory = engine_and_directory
    line = audit_claims([claim(revenue_code="0450", paid=890.0)], engine, directory).lines[0]

    assert not line.benchmarked
    assert "OPPS" in line.unavailable_reason
    assert line.variance is None


def test_unbenchmarked_dollars_never_enter_the_variance(engine_and_directory):
    """The property that makes this defensible: no silent projection."""
    engine, directory = engine_and_directory
    audit = audit_claims([
        claim(paid=340.0, number=1),
        claim(revenue_code="0450", paid=5000.0, number=2),
    ], engine, directory)

    assert audit.total_paid == 5340.00
    assert audit.benchmarked_paid == 340.00
    assert audit.total_variance == 214.77
    assert audit.coverage == pytest.approx(340.0 / 5340.0, abs=0.0001)


def test_coverage_is_reported_in_dollars_not_lines(engine_and_directory):
    """One huge unmeasured line matters more than many small measured ones."""
    engine, directory = engine_and_directory
    audit = audit_claims(
        [claim(paid=100.0, number=i) for i in range(9)]
        + [claim(revenue_code="0450", paid=9000.0, number=10)],
        engine, directory,
    )
    assert len(audit.benchmarked_lines) == 9
    assert audit.coverage < 0.10


def test_a_non_priceable_code_is_reported_with_its_reason(engine_and_directory):
    engine, directory = engine_and_directory
    line = audit_claims([claim("36415", paid=25.0)], engine, directory).lines[0]
    assert not line.benchmarked
    assert "status" in line.unavailable_reason


# --- rollups -----------------------------------------------------------------

def test_provider_rollup_orders_by_variance(engine_and_directory):
    engine, directory = engine_and_directory
    audit = audit_claims([
        claim(paid=340.0, provider="Small Clinic", number=1),
        claim(paid=900.0, provider="Big Imaging", number=2),
    ], engine, directory)

    rows = audit.by_provider()
    assert rows[0].key == "Big Imaging"
    assert rows[0].variance > rows[1].variance


def test_group_coverage_is_per_group(engine_and_directory):
    engine, directory = engine_and_directory
    audit = audit_claims([
        claim(paid=340.0, provider="Clean", number=1),
        claim(paid=500.0, provider="Facility Heavy", revenue_code="0450", number=2),
    ], engine, directory)

    by_provider = {row.key: row for row in audit.by_provider()}
    assert by_provider["Clean"].coverage == 1.0
    assert by_provider["Facility Heavy"].coverage == 0.0


def test_month_rollup_is_chronological(engine_and_directory):
    engine, directory = engine_and_directory
    audit = audit_claims([
        claim(paid=340.0, when=date(2026, 3, 2), number=1),
        claim(paid=340.0, when=date(2026, 1, 8), number=2),
        claim(paid=340.0, when=date(2026, 2, 9), number=3),
    ], engine, directory)

    assert [row.key for row in audit.by_month()] == ["2026-01", "2026-02", "2026-03"]


def test_concentration_reports_where_variance_sits(engine_and_directory):
    engine, directory = engine_and_directory
    audit = audit_claims(
        [claim(paid=2000.0, provider="Outlier", number=1)]
        + [claim(paid=200.0, provider=f"Clinic {i}", number=i + 2) for i in range(6)],
        engine, directory,
    )
    concentration = audit.concentration(top=1)
    assert concentration["top"][0][0] == "Outlier"
    assert concentration["share_in_top"] > 0.5


def test_reasons_are_ranked_by_dollars_not_line_count(engine_and_directory):
    engine, directory = engine_and_directory
    audit = audit_claims(
        [claim(revenue_code="0450", paid=9000.0, number=1)]
        + [claim("36415", paid=20.0, number=i + 2) for i in range(8)],
        engine, directory,
    )
    reasons = audit.reasons()
    assert "Facility" in reasons[0][0]
    assert reasons[0][2] > reasons[1][2]


@pytest.mark.parametrize("code,expected", [
    ("99214", "Evaluation & management"),
    ("71046", "Radiology"),
    ("80053", "Pathology & laboratory"),
    ("20610", "Surgery"),
    ("97110", "Medicine & therapy"),
    ("J1885", "Other / HCPCS level II"),
])
def test_service_categories(code, expected):
    assert categorise(code) == expected


# --- reading an extract ------------------------------------------------------

EXTRACT = """claim_id,provider,cpt,mod,units,dos,billed,paid,rev_code,locality
CLM1,Clinic A,99214,,1,2026-03-14,900.00,340.00,,10112-AL-00
CLM2,Hospital B,99284,,1,2026-03-14,2400.00,890.00,0450,10112-AL-00
CLM3,Clinic A,71046,26,1,2026-03-14,300.00,120.00,,10112-AL-00
"""

LAYOUT = ColumnMap(fields={
    "claim_id": "claim_id", "provider": "provider", "cpt_code": "cpt",
    "modifier": "mod", "units": "units", "service_date": "dos",
    "billed_amount": "billed", "paid_amount": "paid",
    "revenue_code": "rev_code", "locality_id": "locality",
})


def test_reads_a_claims_extract(tmp_path):
    path = tmp_path / "claims.csv"
    path.write_text(EXTRACT)
    claims = read_claims(path, LAYOUT)

    assert len(claims) == 3
    assert claims[0].paid_amount == 340.00
    assert claims[0].billed_amount == 900.00
    assert claims[2].modifier == "26"


def test_setting_defaults_from_the_revenue_code(tmp_path):
    """A revenue code and a facility setting are the same fact, seen twice."""
    path = tmp_path / "claims.csv"
    path.write_text(EXTRACT)
    claims = read_claims(path, LAYOUT)

    assert claims[0].setting is Setting.NON_FACILITY
    assert claims[1].setting is Setting.FACILITY


def test_missing_required_column_is_refused(tmp_path):
    path = tmp_path / "claims.csv"
    path.write_text(EXTRACT)
    incomplete = ColumnMap(fields={"cpt_code": "cpt"})
    with pytest.raises(ValueError, match="missing required field"):
        read_claims(path, incomplete)


def test_a_bad_row_names_its_line(tmp_path):
    path = tmp_path / "claims.csv"
    path.write_text(EXTRACT + "CLM4,Clinic A,99213,,1,2026-03-14,100,not-a-number,,10112-AL-00\n")
    with pytest.raises(ClaimsFormatError, match="line 5"):
        read_claims(path, LAYOUT)


def test_the_shipped_quarter_audits(engine_and_directory):
    """The example portfolio must actually run end to end."""
    example = ROOT / "examples" / "claims_q1_2026.csv"
    if not example.exists():
        pytest.skip("example claims file not present")

    engine, directory = engine_and_directory
    claims = read_claims(example, ColumnMap.from_json(LAYOUTS / "claims_extract.json"))
    audit = audit_claims(claims, engine, directory)

    assert len(claims) == 260
    assert 0.5 < audit.coverage < 1.0
    assert audit.total_variance > 0
    assert audit.by_provider()[0].variance > 0
    assert audit.reasons()
