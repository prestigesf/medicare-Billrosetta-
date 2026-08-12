"""Rate lookup across published fee-schedule periods.

The engine resolves a query — CPT code, ZIP, setting, date of service — down
to one allowed amount plus the arithmetic behind it. It holds no CMS data of
its own; periods are loaded and handed in, so the data can be versioned,
swapped, and audited independently of this code.
"""
from datetime import date
from typing import Dict, Iterable, List, Mapping

from .errors import (
    NoFeeScheduleForDate,
    UnknownCPTCode,
    UnknownLocality,
    UnmappedZipCode,
)
from .formula import geographic_components, round_money
from .models import FeeSchedulePeriod, RateResult, Setting


class RateEngine:
    """Answers: what did Medicare allow for this code, here, on this date?

    Args:
        periods: published fee-schedule editions. Overlapping periods are
            rejected — an ambiguous date of service must not silently resolve
            to whichever edition happened to be first in the list.
        zip_to_locality: ZIP code -> locality id, from CMS's crosswalk.
    """

    def __init__(
        self,
        periods: Iterable[FeeSchedulePeriod],
        zip_to_locality: Mapping[str, str],
    ):
        self._periods: List[FeeSchedulePeriod] = sorted(
            periods, key=lambda p: p.effective_start
        )
        self._reject_overlaps(self._periods)
        self._zip_to_locality: Dict[str, str] = dict(zip_to_locality)

    @staticmethod
    def _reject_overlaps(periods: List[FeeSchedulePeriod]) -> None:
        for earlier, later in zip(periods, periods[1:]):
            if later.effective_start <= earlier.effective_end:
                raise ValueError(
                    f"Fee schedule periods overlap: {earlier.period_id} ends "
                    f"{earlier.effective_end} but {later.period_id} starts "
                    f"{later.effective_start}. A date of service must resolve "
                    "to exactly one edition."
                )

    def period_for(self, service_date: date) -> FeeSchedulePeriod:
        for period in self._periods:
            if period.covers(service_date):
                return period
        raise NoFeeScheduleForDate(
            f"No loaded fee schedule covers {service_date.isoformat()}. "
            f"Loaded periods: {[p.period_id for p in self._periods] or 'none'}."
        )

    def locality_for_zip(self, zip_code: str) -> str:
        normalised = zip_code.strip()[:5]
        try:
            return self._zip_to_locality[normalised]
        except KeyError:
            raise UnmappedZipCode(
                f"ZIP {normalised} is not in the loaded ZIP-to-locality crosswalk."
            ) from None

    def rate(
        self,
        cpt_code: str,
        zip_code: str,
        setting: Setting,
        service_date: date,
    ) -> RateResult:
        """The allowed amount for a ZIP, or a specific reason there isn't one.

        Raises a RateUnavailable subclass rather than returning a fallback.
        Requires a loaded ZIP-to-locality crosswalk; when one is unavailable,
        use rate_for_locality with a locality id taken from the GPCI file.
        """
        return self.rate_for_locality(
            cpt_code, self.locality_for_zip(zip_code), setting, service_date
        )

    def rate_for_locality(
        self,
        cpt_code: str,
        locality_id: str,
        setting: Setting,
        service_date: date,
    ) -> RateResult:
        """The allowed amount for an explicit MAC locality.

        CMS distributes the ZIP-to-locality crosswalk through channels that are
        not reliably public, so callers who already know the locality — or who
        resolve it by other means — can price without one.
        """
        period = self.period_for(service_date)
        code = cpt_code.upper().strip()

        try:
            rvus = period.rvus[code]
        except KeyError:
            raise UnknownCPTCode(
                f"CPT {code} is not in the {period.period_id} RVU file."
            ) from None

        try:
            gpci = period.gpcis[locality_id]
        except KeyError:
            raise UnknownLocality(
                f"Locality {locality_id} has no GPCI entry in {period.period_id}."
            ) from None

        work, practice_expense, malpractice = geographic_components(rvus, gpci, setting)
        total_rvu = work + practice_expense + malpractice

        return RateResult(
            cpt_code=code,
            locality_id=locality_id,
            locality_name=gpci.locality_name,
            setting=setting,
            service_date=service_date,
            period_id=period.period_id,
            conversion_factor=period.conversion_factor,
            work_component=work,
            practice_expense_component=practice_expense,
            malpractice_component=malpractice,
            allowed_amount=round_money(total_rvu * period.conversion_factor),
        )
