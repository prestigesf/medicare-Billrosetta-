"""Lookup behaviour: date resolution, locality resolution, and refusals."""
from datetime import date

import pytest

from pfs import (
    GPCI,
    FeeSchedulePeriod,
    NoFeeScheduleForDate,
    NotPriceableUnderPFS,
    RateEngine,
    RVUs,
    Setting,
    UnknownCPTCode,
    UnknownLocality,
    UnmappedZipCode,
)

# Illustrative fixtures — structure real, numbers not CMS's.
GPCI_SF = GPCI("01-05", "San Francisco", 1.070, 1.380, 0.480)
GPCI_REST = GPCI("01-99", "Rest of California", 1.005, 1.050, 0.600)


def rvus(code="99214", status="A", work=1.92, pe_nf=1.73, pe_f=0.80, mp=0.14):
    return RVUs(code, work, pe_f, pe_nf, mp, status)


def period(period_id, start, end, cf, codes=None, gpcis=None):
    return FeeSchedulePeriod(
        period_id=period_id,
        effective_start=start,
        effective_end=end,
        conversion_factor=cf,
        rvus=codes if codes is not None else {"99214": rvus()},
        gpcis=gpcis if gpcis is not None else {"01-05": GPCI_SF, "01-99": GPCI_REST},
    )


P2025 = period("2025", date(2025, 1, 1), date(2025, 12, 31), 32.0000)
P2026 = period("2026", date(2026, 1, 1), date(2026, 12, 31), 33.0000)

ZIPS = {"94110": "01-05", "95814": "01-99"}


def engine(periods=(P2025, P2026), zips=None):
    return RateEngine(periods, zips if zips is not None else ZIPS)


def test_date_of_service_selects_the_schedule_in_effect_then():
    """The whole point: a 2025 bill is priced with 2025's conversion factor."""
    e = engine()
    older = e.rate("99214", "94110", Setting.NON_FACILITY, date(2025, 6, 1))
    newer = e.rate("99214", "94110", Setting.NON_FACILITY, date(2026, 6, 1))

    assert older.period_id == "2025"
    assert older.conversion_factor == 32.0000
    assert newer.period_id == "2026"
    assert newer.conversion_factor == 33.0000
    assert older.allowed_amount != newer.allowed_amount


def test_period_boundaries_are_inclusive():
    e = engine()
    assert e.rate("99214", "94110", Setting.FACILITY, date(2026, 1, 1)).period_id == "2026"
    assert e.rate("99214", "94110", Setting.FACILITY, date(2026, 12, 31)).period_id == "2026"


def test_date_outside_every_loaded_period_raises():
    with pytest.raises(NoFeeScheduleForDate):
        engine().rate("99214", "94110", Setting.FACILITY, date(2019, 3, 1))


def test_overlapping_periods_are_rejected_at_construction():
    """An ambiguous date must not silently resolve to whichever came first."""
    overlapping = period("2026-dup", date(2026, 6, 1), date(2027, 1, 1), 34.0)
    with pytest.raises(ValueError, match="overlap"):
        RateEngine([P2026, overlapping], ZIPS)


def test_locality_changes_the_amount():
    """Geography is the point — same code, same day, two localities."""
    e = engine()
    sf = e.rate("99214", "94110", Setting.NON_FACILITY, date(2026, 6, 1))
    rest = e.rate("99214", "95814", Setting.NON_FACILITY, date(2026, 6, 1))

    assert sf.locality_id == "01-05"
    assert rest.locality_id == "01-99"
    assert sf.allowed_amount > rest.allowed_amount


def test_zip_plus_four_is_normalised():
    result = engine().rate("99214", "94110-1234", Setting.FACILITY, date(2026, 6, 1))
    assert result.locality_id == "01-05"


def test_unmapped_zip_raises_rather_than_defaulting():
    with pytest.raises(UnmappedZipCode):
        engine().rate("99214", "00000", Setting.FACILITY, date(2026, 6, 1))


def test_unknown_cpt_raises_rather_than_defaulting():
    with pytest.raises(UnknownCPTCode):
        engine().rate("00000", "94110", Setting.FACILITY, date(2026, 6, 1))


def test_locality_without_gpci_data_raises():
    sparse = period("2026", date(2026, 1, 1), date(2026, 12, 31), 33.0, gpcis={"01-99": GPCI_REST})
    with pytest.raises(UnknownLocality):
        RateEngine([sparse], ZIPS).rate("99214", "94110", Setting.FACILITY, date(2026, 6, 1))


def test_bundled_code_raises_with_its_status_explained():
    bundled = period(
        "2026", date(2026, 1, 1), date(2026, 12, 31), 33.0,
        codes={"99211": rvus("99211", status="B", work=0, pe_nf=0, pe_f=0, mp=0)},
    )
    with pytest.raises(NotPriceableUnderPFS) as exc:
        RateEngine([bundled], ZIPS).rate("99211", "94110", Setting.FACILITY, date(2026, 6, 1))
    assert exc.value.status_code == "B"


def test_result_carries_its_own_derivation():
    result = engine().rate("99214", "94110", Setting.NON_FACILITY, date(2026, 6, 1))

    recomputed = (
        result.work_component
        + result.practice_expense_component
        + result.malpractice_component
    ) * result.conversion_factor

    assert round(recomputed, 2) == pytest.approx(result.allowed_amount, abs=0.01)
    assert result.source == "cms-pfs:2026:01-05"
    assert "99214" in result.explain()
    assert "2026-06-01" in result.explain()


def test_setting_is_recorded_on_the_result():
    result = engine().rate("99214", "94110", Setting.FACILITY, date(2026, 6, 1))
    assert result.setting is Setting.FACILITY
