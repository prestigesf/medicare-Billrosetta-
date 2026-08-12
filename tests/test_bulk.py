"""Pricing a whole bill: parsing, totals, and how bad lines are handled."""
from datetime import date
from pathlib import Path

import pytest

from pfs import FeeSchedulePeriod, RateEngine, Setting
from pfs.bulk import (
    MATERIALITY_MULTIPLE,
    BilledLine,
    BillFormatError,
    parse_date,
    parse_money,
    parse_setting,
    price_bill,
    read_bill,
    write_priced_csv,
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


@pytest.fixture(scope="module")
def engine_and_directory():
    layout = ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
    rvus = load_rvus(RVU_FILE, layout)
    gpcis = load_gpcis(GPCI_FILE, ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))
    period = FeeSchedulePeriod(
        period_id="2026-RVU26C",
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        conversion_factor=load_conversion_factor(RVU_FILE, layout),
        rvus=rvus,
        gpcis=gpcis,
    )
    return RateEngine([period], {}), LocalityDirectory(gpcis)


def line(code, charged, *, modifier="", state="AL", locality=None,
         setting=Setting.NON_FACILITY, number=1):
    return BilledLine(
        line_number=number,
        cpt_code=code,
        charged_amount=charged,
        service_date=DOS,
        setting=setting,
        modifier=modifier,
        state=state,
        locality_id=locality,
    )


# --- parsing -----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("facility", Setting.FACILITY),
    ("Non-Facility", Setting.NON_FACILITY),
    ("office", Setting.NON_FACILITY),
    ("HOSPITAL", Setting.FACILITY),
])
def test_setting_aliases(text, expected):
    assert parse_setting(text) is expected


def test_unrecognised_setting_is_refused():
    with pytest.raises(ValueError, match="not recognised"):
        parse_setting("somewhere")


@pytest.mark.parametrize("text", ["2026-03-14", "03/14/2026"])
def test_date_formats(text):
    assert parse_date(text) == DOS


def test_unrecognised_date_is_refused():
    with pytest.raises(ValueError, match="not recognised"):
        parse_date("March 14th")


@pytest.mark.parametrize("text,expected", [
    ("340.00", 340.0), ("$1,450.00", 1450.0), (" 95 ", 95.0),
])
def test_money_parsing(text, expected):
    assert parse_money(text) == expected


def test_blank_charge_is_refused():
    with pytest.raises(ValueError, match="blank"):
        parse_money("")


# --- reading a bill file -----------------------------------------------------

BILL = """cpt_code,modifier,description,charged_amount,date_of_service,setting,state
99214,,Office visit,340.00,2026-03-14,non-facility,AL
71046,26,Chest x-ray read,185.00,2026-03-14,non-facility,AL
"""


def test_reads_a_bill(tmp_path):
    path = tmp_path / "bill.csv"
    path.write_text(BILL)
    lines = read_bill(path)

    assert len(lines) == 2
    assert lines[0].cpt_code == "99214"
    assert lines[1].modifier == "26"
    assert lines[0].service_date == DOS
    assert lines[0].setting is Setting.NON_FACILITY


def test_missing_required_column_is_named(tmp_path):
    path = tmp_path / "bill.csv"
    path.write_text("cpt_code,charged_amount,state\n99214,340,AL\n")
    with pytest.raises(BillFormatError, match="missing required column"):
        read_bill(path)


def test_bill_without_any_location_column_is_refused(tmp_path):
    path = tmp_path / "bill.csv"
    path.write_text(
        "cpt_code,charged_amount,date_of_service,setting\n"
        "99214,340,2026-03-14,non-facility\n"
    )
    with pytest.raises(BillFormatError, match="locality_id or a state"):
        read_bill(path)


def test_a_bad_row_names_its_line_number(tmp_path):
    path = tmp_path / "bill.csv"
    path.write_text(BILL + "99213,,Visit,not-a-number,2026-03-14,non-facility,AL\n")
    with pytest.raises(BillFormatError, match="line 4"):
        read_bill(path)


# --- pricing -----------------------------------------------------------------

def test_prices_a_line_against_real_data(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill([line("99214", 340.00)], engine, directory)
    priced = pricing.lines[0]

    assert priced.priced
    assert priced.allowed_amount == 125.23
    assert priced.variance == 214.77
    assert priced.multiple_of_medicare == 2.72
    assert priced.flagged
    assert "99214" in priced.derivation


def test_a_charge_at_the_benchmark_is_not_flagged(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill([line("99214", 125.23)], engine, directory)

    assert pricing.lines[0].multiple_of_medicare == 1.0
    assert not pricing.lines[0].flagged
    assert pricing.lines[0].variance == 0.0


def test_a_charge_below_the_benchmark_reports_a_negative_variance(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill([line("99214", 100.00)], engine, directory)

    assert pricing.lines[0].variance == -25.23
    assert not pricing.lines[0].flagged


def test_flagging_respects_the_materiality_multiple(engine_and_directory):
    """Just under the multiple is reported but not called out."""
    engine, directory = engine_and_directory
    just_under = 125.23 * MATERIALITY_MULTIPLE - 0.50
    just_over = 125.23 * MATERIALITY_MULTIPLE + 0.50

    assert not price_bill([line("99214", just_under)], engine, directory).lines[0].flagged
    assert price_bill([line("99214", just_over)], engine, directory).lines[0].flagged


def test_modifier_line_prices_the_component(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill([line("71046", 185.00, modifier="26")], engine, directory)

    assert pricing.lines[0].allowed_amount == 9.54


# --- one bad line never fails the batch --------------------------------------

def test_unknown_code_is_reported_and_the_rest_still_price(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill(
        [line("99999", 300.00, number=1), line("99214", 340.00, number=2)],
        engine, directory,
    )

    assert len(pricing.priced_lines) == 1
    assert len(pricing.unpriced_lines) == 1
    assert "not in" in pricing.unpriced_lines[0].unavailable_reason


def test_non_priceable_status_is_reported_with_its_reason(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill([line("27215", 1450.00)], engine, directory)
    unpriced = pricing.lines[0]

    assert not unpriced.priced
    assert "not valid for Medicare purposes" in unpriced.unavailable_reason


def test_ambiguous_state_is_reported_with_its_candidates(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill([line("99214", 340.00, state="CA")], engine, directory)

    assert not pricing.lines[0].priced
    assert "20 localities" in pricing.lines[0].unavailable_reason


def test_an_explicit_locality_bypasses_state_ambiguity(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill(
        [line("99214", 340.00, state="CA", locality="01112-CA-05")], engine, directory
    )

    assert pricing.lines[0].priced
    assert pricing.lines[0].locality_id == "01112-CA-05"


def test_without_a_directory_a_state_only_line_is_reported_not_guessed(engine_and_directory):
    engine, _ = engine_and_directory
    pricing = price_bill([line("99214", 340.00)], engine, directory=None)

    assert not pricing.lines[0].priced
    assert "no locality directory" in pricing.lines[0].unavailable_reason


# --- totals ------------------------------------------------------------------

def test_unpriced_lines_do_not_pollute_the_totals(engine_and_directory):
    """The charge on a line with no benchmark cannot become a finding."""
    engine, directory = engine_and_directory
    pricing = price_bill(
        [line("99214", 340.00, number=1), line("27215", 1450.00, number=2)],
        engine, directory,
    )

    assert pricing.total_charged == 1790.00
    assert pricing.total_charged_on_priced_lines == 340.00
    assert pricing.total_allowed == 125.23
    assert pricing.total_variance == 214.77


def test_summary_reports_both_charge_figures(engine_and_directory):
    engine, directory = engine_and_directory
    pricing = price_bill(
        [line("99214", 340.00, number=1), line("99999", 300.00, number=2)],
        engine, directory,
    )
    summary = pricing.summary()

    assert summary["lines"] == 2
    assert summary["priced"] == 1
    assert summary["unpriced"] == 1
    assert summary["total_charged"] == 640.00
    assert summary["total_charged_on_priced_lines"] == 340.00


# --- output ------------------------------------------------------------------

def test_priced_csv_carries_every_line_and_its_derivation(engine_and_directory, tmp_path):
    engine, directory = engine_and_directory
    pricing = price_bill(
        [line("99214", 340.00, number=1), line("99999", 300.00, number=2)],
        engine, directory,
    )
    out = write_priced_csv(pricing, tmp_path / "priced.csv")
    text = out.read_text()

    assert "99214" in text and "99999" in text
    assert "125.23" in text
    assert "no benchmark" in text
    assert "cms-pfs:2026-RVU26C" in text


def test_the_shipped_example_bill_prices(engine_and_directory):
    """The example in the repo must actually run."""
    example = ROOT / "examples" / "sample_bill.csv"
    if not example.exists():
        pytest.skip("example bill not present")

    engine, directory = engine_and_directory
    pricing = price_bill(read_bill(example), engine, directory)

    assert len(pricing.priced_lines) == 4
    assert len(pricing.unpriced_lines) == 4
    assert pricing.total_allowed == 457.46
    assert pricing.total_variance == 797.54
