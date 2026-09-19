#!/usr/bin/env python3
"""Check the tier change log against the current tier list.

Two files can drift: somebody edits data/tierlist-events-3v3.txt and forgets
data/tier-changes.tsv, and the history silently grows a hole. This catches that.

    python3 tools/check_tier_history.py [overrides.txt] [tier-history.txt]

Exits 1 with one line per problem, 0 when clean.
"""

import dataclasses
import os
import sys
from typing import Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gibhub.history import TierChange, parse_changes  # noqa: E402
from gibhub.model import TIERS  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Problem:
    player: str
    detail: str


def _name(tier: Optional[str]) -> str:
    return tier if tier else "untiered"


def check(
    current: Mapping[str, str], changes: Sequence[TierChange]
) -> List[Problem]:
    """Every way the log and the tier list can disagree.

    Deliberately does not require a log entry per listed player: the log starts
    empty and most players will never appear in it. Only players the log
    mentions are checked.
    """
    by_player: Dict[str, List[TierChange]] = {}
    for change in changes:
        by_player.setdefault(change.player, []).append(change)

    problems: List[Problem] = []
    for player in sorted(by_player):
        entries = by_player[player]
        dates = [entry.date for entry in entries]

        if len(set(dates)) != len(dates):
            problems.append(Problem(
                player, "two entries on the same date; the order they take effect "
                        "in is undefined"))
        elif dates != sorted(dates):
            problems.append(Problem(player, "entries are out of order by date"))

        for earlier, later in zip(entries, entries[1:]):
            if earlier.tier != later.previous:
                problems.append(Problem(
                    player,
                    "%s leaves %s but the next starts from %s"
                    % (earlier.date, _name(earlier.tier), _name(later.previous))))

        ends_at = entries[-1].tier
        listed = current.get(player)
        if listed is None and ends_at is not None:
            problems.append(Problem(
                player, "not on the tier list, but the log ends at %s"
                        % _name(ends_at)))
        elif listed is not None and listed != ends_at:
            problems.append(Problem(
                player, "list says %s, log ends at %s"
                        % (_name(listed), _name(ends_at))))

    return problems


def load_overrides(path: str) -> Dict[str, str]:
    """Read the resolved 'uuid = TIER' file the tier list produces."""
    current = {}
    if not os.path.exists(path):
        return current
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            player, _, tier = line.partition("=")
            tier = tier.strip().upper()
            if tier in TIERS:
                current[player.strip()] = tier
    return current


def main(overrides_path: str, history_path: str) -> int:
    if not os.path.exists(history_path):
        print("no %s; nothing to check" % history_path)
        return 0

    with open(history_path, "r", encoding="utf-8") as handle:
        changes = parse_changes(handle.read())

    problems = check(load_overrides(overrides_path), changes)
    if not problems:
        print("%d change(s) checked against %s: OK"
              % (len(changes), overrides_path))
        return 0

    print("%d problem(s) between %s and %s:" % (
        len(problems), history_path, overrides_path))
    for problem in problems:
        print("  %-40s %s" % (problem.player, problem.detail))
    return 1


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "overrides.txt",
        sys.argv[2] if len(sys.argv) > 2 else "tier-history.txt",
    ))
