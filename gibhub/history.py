"""The committee's tier change log. Pure: parsing and lookup, no I/O.

Tiers have no history in the API, so a tier change would otherwise rewrite every
past match a player appears in. This module records what the committee decided
and when, so a match can be scored against the tiers in force on its own day.
"""

import bisect
import dataclasses
import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import TIER_POINTS

# Written in the `from` column when a player held no committee tier before.
UNTIERED = "-"


@dataclasses.dataclass(frozen=True)
class TierChange:
    """One committee decision, on one date, about one player."""

    date: str
    player: str
    previous: Optional[str]  # None when the player held no committee tier
    tier: Optional[str]
    note: str = ""


def _tier(raw: str, line_number: int) -> Optional[str]:
    if raw == UNTIERED:
        return None
    if raw not in TIER_POINTS:
        raise ValueError("line %d: unknown tier %r" % (line_number, raw))
    return raw


def parse_changes(text: str) -> List[TierChange]:
    """Read the log. Blank lines and `#` comments are ignored."""
    changes = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) < 4:
            raise ValueError(
                "line %d: expected date, player, from, to, note; got %r"
                % (number, raw)
            )
        date, player, previous, tier = (field.strip() for field in fields[:4])
        # A note may itself contain tabs; everything past the fourth column is it.
        note = "\t".join(fields[4:]).strip()
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ValueError("line %d: bad date %r, want YYYY-MM-DD" % (number, date))
        changes.append(
            TierChange(date, player, _tier(previous, number), _tier(tier, number), note)
        )
    # Stable sort: two decisions on one date keep the order they were written.
    return sorted(changes, key=lambda change: change.date)
