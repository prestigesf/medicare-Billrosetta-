"""Reasons a rate cannot be produced.

Every one of these is a refusal to guess. The caller gets a specific reason
instead of a plausible number, because a wrong benchmark in an appeal letter
is worse than no benchmark at all.
"""


class RateUnavailable(Exception):
    """Base: no defensible rate exists for this query."""


class UnknownCPTCode(RateUnavailable):
    """The code is not in the loaded RVU file for this period."""


class NotPriceableUnderPFS(RateUnavailable):
    """The code exists but carries a status code with no national PFS rate.

    Bundled, non-covered, statutorily excluded, or carrier-priced services all
    land here. A carrier-priced code genuinely has no national number — the
    MAC sets it — so there is nothing to compute.
    """

    def __init__(self, cpt_code: str, status_code: str, meaning: str):
        self.cpt_code = cpt_code
        self.status_code = status_code
        self.meaning = meaning
        super().__init__(
            f"CPT {cpt_code} has PFS status '{status_code}' ({meaning}); "
            "no national fee-schedule amount exists for it."
        )


class UnknownLocality(RateUnavailable):
    """No GPCI entry for the requested locality."""


class UnmappedZipCode(RateUnavailable):
    """The ZIP is not in the loaded ZIP-to-locality crosswalk."""


class NoFeeScheduleForDate(RateUnavailable):
    """No published fee schedule covers this date of service.

    Rates change; an appeal must use the schedule in effect on the date the
    service was rendered, not today's.
    """


class MissingPracticeExpenseRVU(RateUnavailable):
    """The code has no PE RVU for the requested setting.

    Some codes are only priced in one setting. Substituting the other
    setting's PE RVU produces a real-looking number for a service that was
    never priced that way.
    """
