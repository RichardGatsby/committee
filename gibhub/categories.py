"""Classifying a 3v3 match by what kind of game it was.

The API does not carry a single field for this, so it is read off three signals:
the `gather` tag, the channel the match was reported in, and whether the channel
is a real Discord channel or a synthetic tournament one.
"""

from typing import Any, Dict, List, Tuple

LEGACY = "legacy"
POLAND = "poland"
OTHER_GATHER = "other-gather"
CUP = "cup"
TEAM = "team"

LABELS = {
    LEGACY: "ET:Legacy gathers",
    POLAND: "Poland gathers",
    OTHER_GATHER: "other gathers",
    CUP: "cups and tournaments",
    TEAM: "team games and scrims",
}
ORDER = (LEGACY, POLAND, OTHER_GATHER, CUP, TEAM)

# Tournament channels carry a synthetic zero-padded id rather than a Discord
# snowflake, which is the only reliable marker for cups that carry no `cup` tag
# (Nations Cup and subak's cups among them).
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

    if (channel_id.startswith(TOURNAMENT_ID_PREFIX)
            or "cup" in tags
            or any(t.startswith("et:l season") for t in tags)):
        return CUP

    return TEAM


def parse_selection(values) -> List[str]:
    """Turn --only values into category keys, accepting a few friendly spellings."""
    if not values:
        return []
    aliases = {
        "legacy": LEGACY, "events": LEGACY, "etl": LEGACY,
        "poland": POLAND, "pl": POLAND,
        "other": OTHER_GATHER, "other-gather": OTHER_GATHER,
        "gather": "ALL_GATHERS", "gathers": "ALL_GATHERS",
        "cup": CUP, "cups": CUP, "tournament": CUP,
        "team": TEAM, "teams": TEAM, "scrim": TEAM, "internal": TEAM,
    }
    chosen: List[str] = []
    for value in values:
        key = aliases.get(str(value).strip().lower())
        if key is None:
            raise ValueError(
                "unknown category %r; expected one of: %s"
                % (value, ", ".join(sorted(set(aliases)))))
        for resolved in ([LEGACY, POLAND, OTHER_GATHER] if key == "ALL_GATHERS" else [key]):
            if resolved not in chosen:
                chosen.append(resolved)
    return chosen


def split(rows) -> List[Tuple[str, List[Any]]]:
    """Group rows by category, in a stable order, skipping empty categories."""
    buckets: Dict[str, List[Any]] = {key: [] for key in ORDER}
    for row in rows:
        buckets.setdefault(row.category or TEAM, []).append(row)
    return [(key, buckets[key]) for key in ORDER if buckets.get(key)]
