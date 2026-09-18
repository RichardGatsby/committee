"""Fetching the data a player report needs. Thin: no scoring, no formatting."""

import re
from typing import Any, Dict, List, Optional, Tuple

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
SIZE_3V3 = "3v3"
PAGE_SIZE = 50


class PlayerNotFound(Exception):
    pass


class AmbiguousPlayer(Exception):
    pass


def resolve_player(client, term: str, exact: bool = False) -> str:
    """A UUID passes through; a name goes through fuzzy search.

    Several hits raise rather than guess, unless one is an exact nick match and
    `exact` allows it.
    """
    if UUID.match(term):
        return term

    results = (client.get("/players/search", {"q": term, "limit": 10}) or {}).get("data") or []
    if not results:
        raise PlayerNotFound("no player matches %r" % term)
    if len(results) == 1:
        return results[0]["player_id"]

    if exact:
        lowered = term.lower()
        for result in results:
            if (result.get("discord_nick") or "").lower() == lowered:
                return result["player_id"]

    listing = "\n".join(
        "  %s  %s (%s)" % (r["player_id"], r.get("discord_nick") or "?", r.get("nick") or "?")
        for r in results
    )
    raise AmbiguousPlayer("%r matches several players:\n%s" % (term, listing))


def fetch_player_data(
    client,
    player_id: str,
    matches: Optional[int] = None,
    range_: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    channel: Optional[str] = None,
    cache=None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], int]:
    scope = {"size": SIZE_3V3, "range": range_, "from": from_, "to": to,
             "channel": channel}
    profile = client.get("/players/" + player_id, scope)
    spider = client.get("/players/" + player_id + "/spider", scope)

    # How many matches the window holds, so a truncated report can say so:
    # silently taking the most recent N can flip a verdict.
    head = client.get("/players/" + player_id + "/matches",
                      dict(scope, page=1, pageSize=1))
    available = head.get("total") or 0

    listing = client.paginate(
        "/players/" + player_id + "/matches", scope, page_size=PAGE_SIZE, limit=matches
    )

    def load(match_id):
        return client.get("/matches/" + match_id)

    details = []
    for item in listing:
        match_id = item["match_id"]
        details.append(cache.fetch(match_id, load) if cache else load(match_id))

    return profile, spider, details, available
