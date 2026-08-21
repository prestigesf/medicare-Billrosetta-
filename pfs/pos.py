"""Place-of-service -> PFS setting.

POS 11 is not the only non-facility code. Guessing facility vs non-facility
from a single equality is a silent misprice.
"""
from .models import Setting

# CMS POS codes that take facility PE RVUs under the physician fee schedule.
FACILITY_POS = frozenset({
    "19",  # off-campus outpatient hospital
    "21",  # inpatient hospital
    "22",  # on-campus outpatient hospital
    "23",  # emergency room
    "24",  # ASC
    "26",  # military treatment facility
    "31",  # SNF
    "34",  # hospice
    "41",  # ambulance land
    "42",  # ambulance air/water
    "51",  # inpatient psych
    "52",  # psych facility partial
    "53",  # community mental health
    "56",  # psych residential
    "61",  # comprehensive inpatient rehab
})

# Explicit non-facility set. Anything else is refused, not guessed.
NON_FACILITY_POS = frozenset({
    "11", "12", "13", "14", "15", "16", "17",
    "20", "32", "33", "49", "50", "54", "55",
    "57", "60", "62", "65", "71", "72", "81", "99",
})


class UnknownPlaceOfService(ValueError):
    pass


def setting_for_pos(pos: str) -> Setting:
    code = (pos or "").strip()
    if len(code) == 1:
        code = code.zfill(2)
    if code in FACILITY_POS:
        return Setting.FACILITY
    if code in NON_FACILITY_POS:
        return Setting.NON_FACILITY
    raise UnknownPlaceOfService(
        f"POS {pos!r} is not in the facility/non-facility map; "
        "refuse rather than guess a PE RVU."
    )


def infer_pos_from_rev_code(rev_code: str) -> str:
    """Best-effort POS when the extract has a UB revenue code and no POS.

    Used only for the demo claims extract. Production books must carry POS.
    """
    rc = (rev_code or "").strip()
    if rc == "0450":
        return "23"
    if rc in {"0320", "0350", "0400"}:
        return "22"
    if rc in {"0250", "0636"}:
        return "22"
    return "11"
