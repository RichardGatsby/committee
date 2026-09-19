"""Classifying a 3v3 match by what kind of game it was.

The API carries no single field for this, so it is read off three signals: the
`gather` tag, the channel the match was reported in, and whether that channel is
a real Discord one or a synthetic tournament one.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

LEGACY = "legacy"
POLAND = "poland"
OTHER_GATHER = "other-gather"
CUP = "cup"

LABELS = {
    LEGACY: "ET:Legacy gathers",
    POLAND: "Poland gathers",
    OTHER_GATHER: "other gathers",
    CUP: "cups and team games",
}
ORDER = (LEGACY, POLAND, CUP, OTHER_GATHER)

# The gather channels the committee tiers for. The small one-off channels
# (subAk, eV!L, Frag Center, PRAWDZIWY) are not part of that and are dropped
# everywhere unless asked for by name.
GATHERS = (LEGACY, POLAND)

# What a report counts unless told otherwise. Poland is left out: the committee
# reads ET:Legacy gathers and team play, and Poland is over half the match volume,
# so including it quietly dominates every verdict.
REPORT_DEFAULT = (LEGACY, CUP)

# What the model trains on. Broader than a report on purpose — Poland is two
# thirds of the sample and dropping it would weaken the fit for no gain, since
# the tiers being fitted are the same ones either way.
TRAINING_DEFAULT = (LEGACY, POLAND, CUP)

# Tournament channels carry a synthetic zero-padded id rather than a Discord
# snowflake. It is the only reliable marker for cups that carry no `cup` tag,
# Nations Cup and subak's cups among them.
TOURNAMENT_ID_PREFIX = "0000"


def categorise(match: Dict[str, Any]) -> str:
    tags = {str(t).lower() for t in (match.get("tags") or [])}
    name = match.get("channel_name") or ""
    channel_id = str(match.get("channel_id") or "")

    if "gather" in tags:
        if "ET:Legacy Events" in name or "ET:Legacy Gathers" in name:
            return LEGACY
        if "Poland" in name:
            return POLAND
        return OTHER_GATHER

    # Everything else is played by named teams rather than picked sides: cups,
    # league seasons, and the untagged scrims between real teams.
    return CUP


def parse_selection(values: Optional[Iterable[str]]) -> List[str]:
    """Turn --only values into category keys, accepting friendly spellings."""
    if not values:
        return []
    aliases = {
        "legacy": LEGACY, "events": LEGACY, "etl": LEGACY,
        "poland": POLAND, "pl": POLAND,
        "other": OTHER_GATHER, "other-gather": OTHER_GATHER,
        "gather": "ALL_GATHERS", "gathers": "ALL_GATHERS",
        "cup": CUP, "cups": CUP, "tournament": CUP,
        "team": CUP, "teams": CUP, "scrim": CUP, "internal": CUP,
        "all": "EVERYTHING",
    }
    chosen: List[str] = []
    for value in values:
        key = aliases.get(str(value).strip().lower())
        if key is None:
            raise ValueError(
                "unknown category %r; expected one of: %s"
                % (value, ", ".join(sorted(set(aliases)))))
        if key == "ALL_GATHERS":
            expanded = list(GATHERS)
        elif key == "EVERYTHING":
            expanded = list(ORDER)
        else:
            expanded = [key]
        for resolved in expanded:
            if resolved not in chosen:
                chosen.append(resolved)
    return chosen


def allowed(
    selection: Optional[Iterable[str]], default: Tuple[str, ...] = REPORT_DEFAULT
) -> Tuple[str, ...]:
    """Which categories to count: an explicit selection, else `default`."""
    if selection:
        return tuple(selection)
    return default


def split(rows: Iterable[Any]) -> List[Tuple[str, List[Any]]]:
    """Group rows by category, in a stable order, skipping empty categories."""
    buckets: Dict[str, List[Any]] = {key: [] for key in ORDER}
    for row in rows:
        buckets.setdefault(row.category or CUP, []).append(row)
    return [(key, buckets[key]) for key in ORDER if buckets.get(key)]
