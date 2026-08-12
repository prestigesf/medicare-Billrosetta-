"""Resolving a locality without a ZIP crosswalk.

CMS distributes the ZIP-to-locality file through channels that are not
reliably public, which leaves a gap: bills carry a ZIP or an address, and
pricing needs a MAC locality.

Most of that gap closes without the crosswalk. In the CY2026 release, 36 of
53 states and territories contain exactly one locality, so the state alone
determines it. The remaining 17 are genuinely ambiguous and are reported as
such — with their candidates — rather than resolved by picking one.
"""
from typing import Dict, Iterable, List, Mapping

from .errors import RateUnavailable
from .models import GPCI


class AmbiguousLocality(RateUnavailable):
    """The state contains more than one locality; a ZIP is required."""

    def __init__(self, state: str, candidates: List[str]):
        self.state = state
        self.candidates = candidates
        super().__init__(
            f"{state} contains {len(candidates)} localities, so the state alone "
            f"does not determine one: {', '.join(candidates)}. "
            "A ZIP-to-locality crosswalk is needed for this state."
        )


class UnknownState(RateUnavailable):
    """No locality is loaded for that state."""


class LocalityDirectory:
    """Which localities exist in a state, and whether the state settles it.

    Built from the GPCI table, whose keys are MAC-State-Locality.
    """

    def __init__(self, gpcis: Mapping[str, GPCI]):
        self._by_state: Dict[str, List[str]] = {}
        for locality_id in gpcis:
            parts = locality_id.split("-")
            if len(parts) != 3:
                continue
            self._by_state.setdefault(parts[1].upper(), []).append(locality_id)
        for localities in self._by_state.values():
            localities.sort()

    @property
    def states(self) -> List[str]:
        return sorted(self._by_state)

    def localities_in(self, state: str) -> List[str]:
        try:
            return list(self._by_state[state.upper().strip()])
        except KeyError:
            raise UnknownState(
                f"No locality loaded for state {state!r}."
            ) from None

    def is_unambiguous(self, state: str) -> bool:
        return len(self.localities_in(state)) == 1

    def for_state(self, state: str) -> str:
        """The locality id for a state that contains exactly one.

        Raises AmbiguousLocality, listing the candidates, when it does not.
        Never picks one — that would price part of a state with another
        region's indices.
        """
        localities = self.localities_in(state)
        if len(localities) == 1:
            return localities[0]
        raise AmbiguousLocality(state.upper().strip(), localities)

    def unambiguous_states(self) -> List[str]:
        return [s for s, localities in sorted(self._by_state.items()) if len(localities) == 1]

    def ambiguous_states(self) -> List[str]:
        return [s for s, localities in sorted(self._by_state.items()) if len(localities) > 1]

    def coverage(self) -> Dict[str, int]:
        """How much of the country the state alone can price."""
        unambiguous = self.unambiguous_states()
        return {
            "states_total": len(self._by_state),
            "states_resolvable_by_state_alone": len(unambiguous),
            "states_requiring_a_zip": len(self._by_state) - len(unambiguous),
        }


def build_directory(gpcis: Iterable) -> LocalityDirectory:
    return LocalityDirectory(gpcis)
