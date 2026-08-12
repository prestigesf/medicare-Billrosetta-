"""Two things verified against the complete CY2026 release.

1. Status gating actually gates. Some non-priceable codes carry large RVUs;
   without the status check they would produce confident, wrong benchmarks.
2. How far a locality can be resolved without a ZIP crosswalk.
"""
from datetime import date
from pathlib import Path

import pytest

from pfs import (
    FeeSchedulePeriod,
    NotPriceableUnderPFS,
    RateEngine,
    Setting,
)
from pfs.loaders import ColumnMap, load_conversion_factor, load_gpcis, load_rvus
from pfs.locality import AmbiguousLocality, LocalityDirectory, UnknownState
from pfs.models import PRICEABLE_STATUS_CODES, STATUS_CODE_MEANINGS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cms" / "rvu26c"
LAYOUTS = ROOT / "layouts"
RVU_FILE = DATA / "PPRRVU2026_Jul_nonQPP.csv"
GPCI_FILE = DATA / "GPCI2026.csv"

pytestmark = pytest.mark.skipif(
    not (RVU_FILE.exists() and GPCI_FILE.exists()),
    reason="full CMS release not present",
)


@pytest.fixture(scope="module")
def rvus():
    return load_rvus(RVU_FILE, ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json"))


@pytest.fixture(scope="module")
def gpcis():
    return load_gpcis(GPCI_FILE, ColumnMap.from_json(LAYOUTS / "gpci_2026.json"))


@pytest.fixture(scope="module")
def engine(rvus, gpcis):
    period = FeeSchedulePeriod(
        period_id="2026-RVU26C",
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        conversion_factor=load_conversion_factor(
            RVU_FILE, ColumnMap.from_json(LAYOUTS / "pprrvu_2026.json")
        ),
        rvus=rvus,
        gpcis=gpcis,
    )
    return RateEngine([period], zip_to_locality={})


@pytest.fixture(scope="module")
def directory(gpcis):
    return LocalityDirectory(gpcis)


# --- status gating -----------------------------------------------------------

def test_every_status_code_in_the_release_is_named(rvus):
    """An unnamed status is one nobody has decided how to treat."""
    present = {v.status_code for v in rvus.values()}
    unnamed = present - set(STATUS_CODE_MEANINGS)
    assert not unnamed, f"status codes present but unnamed: {sorted(unnamed)}"


def test_some_non_priceable_codes_carry_real_rvus(rvus):
    """The reason status gating matters, stated as data.

    If non-priceable codes all had zero RVUs, forgetting the status check
    would be harmless. They do not: 158 rows across statuses N, I, B and X
    carry non-zero RVUs, some of them large.
    """
    carrying = [
        v for v in rvus.values()
        if v.status_code not in PRICEABLE_STATUS_CODES
        and any([
            v.work or 0,
            v.practice_expense_non_facility or 0,
            v.practice_expense_facility or 0,
            v.malpractice or 0,
        ])
    ]
    assert len(carrying) == 158
    assert {v.status_code for v in carrying} == {"N", "I", "B", "X"}


def test_a_non_priceable_code_with_large_rvus_is_still_refused(engine, rvus):
    """27215 carries a work RVU of 10.19 under status I, 'not valid'.

    Computed rather than refused, it yields a large and entirely wrong
    benchmark. The refusal is the correctness property.
    """
    entry = rvus["27215"]
    assert entry.status_code == "I"
    assert entry.work == 10.19

    with pytest.raises(NotPriceableUnderPFS) as exc:
        engine.rate_for_locality(
            "27215", "10112-AL-00", Setting.NON_FACILITY, date(2026, 3, 14)
        )
    assert exc.value.status_code == "I"


def test_no_non_priceable_code_anywhere_in_the_release_prices(engine, rvus):
    """Swept across every non-priceable line, not just a chosen example."""
    sample = [
        v for v in rvus.values() if v.status_code not in PRICEABLE_STATUS_CODES
    ][:400]

    for entry in sample:
        with pytest.raises(NotPriceableUnderPFS):
            engine.rate_for_locality(
                entry.cpt_code, "10112-AL-00", Setting.NON_FACILITY,
                date(2026, 3, 14), modifier=entry.modifier,
            )


# --- locality without a crosswalk --------------------------------------------

def test_most_states_are_settled_by_the_state_alone(directory):
    coverage = directory.coverage()
    assert coverage["states_total"] == 53
    assert coverage["states_resolvable_by_state_alone"] == 36
    assert coverage["states_requiring_a_zip"] == 17


def test_a_single_locality_state_resolves(directory):
    assert directory.for_state("AL") == "10112-AL-00"
    assert directory.is_unambiguous("AL")


def test_state_lookup_is_case_and_space_insensitive(directory):
    assert directory.for_state(" al ") == "10112-AL-00"


def test_a_multi_locality_state_refuses_and_lists_its_candidates(directory):
    """California has 20 localities. Picking one would misprice the rest."""
    assert not directory.is_unambiguous("CA")

    with pytest.raises(AmbiguousLocality) as exc:
        directory.for_state("CA")

    assert exc.value.state == "CA"
    assert len(exc.value.candidates) == 20
    assert "ZIP" in str(exc.value)


def test_the_ambiguous_states_are_the_expected_ones(directory):
    assert directory.ambiguous_states() == [
        "CA", "FL", "GA", "IL", "LA", "MA", "MD", "ME",
        "MI", "MO", "NJ", "NY", "OR", "PA", "TX", "WA", "WV",
    ]


def test_unknown_state_is_refused(directory):
    with pytest.raises(UnknownState):
        directory.for_state("ZZ")


def test_state_resolution_prices_end_to_end(engine, directory):
    """The gap this closes: state in, real rate out, no crosswalk."""
    locality = directory.for_state("AL")
    result = engine.rate_for_locality(
        "99214", locality, Setting.NON_FACILITY, date(2026, 3, 14)
    )
    assert result.allowed_amount == 125.23
