"""The tier change log. Pure: parsing and lookup, no I/O.

Tiers have no history in the API, so a tier change would otherwise rewrite every
past match a player appears in. This module records what was decided
and when, so a match can be scored against the tiers in force on its own day.
"""

import bisect
import dataclasses
import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import TIER_POINTS

# Written in the `from` column when a player held no assigned tier before.
UNTIERED = "-"


@dataclasses.dataclass(frozen=True)
class TierChange:
    """One tier decision, on one date, about one player."""

    date: str
    player: str
    previous: Optional[str]  # None when the player held no assigned tier
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


# (start, end, tier). `end` is exclusive; None at either side means open-ended.
Era = Tuple[Optional[str], Optional[str], Optional[str]]


@dataclasses.dataclass(frozen=True)
class TierHistory:
    """Per-player change lists, sorted by date, ready for bisect.

    Empty by construction until something is logged, and an empty
    history answers every question with the current tier, so the whole feature
    is inert until the first decision is recorded.
    """

    dates: Mapping[str, Sequence[str]]
    previous: Mapping[str, Sequence[Optional[str]]]

    @classmethod
    def build(cls, changes: Sequence[TierChange]) -> "TierHistory":
        dates: Dict[str, List[str]] = {}
        previous: Dict[str, List[Optional[str]]] = {}
        for change in sorted(changes, key=lambda c: c.date):
            dates.setdefault(change.player, []).append(change.date)
            previous.setdefault(change.player, []).append(change.previous)
        return cls(dates=dates, previous=previous)

    def players(self) -> List[str]:
        """Everyone with at least one recorded decision."""
        return list(self.dates)

    def tier_at(
        self, player: str, on_date: Optional[str], *, current: Optional[str]
    ) -> Optional[str]:
        """The assigned tier in force for `player` on `on_date`.

        The tier that day is the `from` of the earliest change dated after it;
        with no later change, the current tier stands. A change dated exactly
        on_date has already taken effect.
        """
        if on_date is None:
            return current
        dates = self.dates.get(player)
        if not dates:
            return current
        position = bisect.bisect_right(dates, on_date)
        if position >= len(dates):
            return current
        return self.previous[player][position]

    def eras(self, player: str, *, current: Optional[str]) -> List[Era]:
        """Every span the player held one tier, oldest first."""
        dates = self.dates.get(player)
        if not dates:
            return [(None, None, current)]
        spans: List[Era] = []
        start: Optional[str] = None
        for index, date in enumerate(dates):
            spans.append((start, date, self.previous[player][index]))
            start = date
        spans.append((start, None, current))
        return spans

    def changes_in(
        self, player: str, start: Optional[str], end: Optional[str]
    ) -> List[str]:
        """Dates this player's tier changed within [start, end)."""
        return [
            date
            for date in self.dates.get(player, ())
            if (start is None or date >= start) and (end is None or date < end)
        ]
