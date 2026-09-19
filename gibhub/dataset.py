"""Turning API match payloads into model samples."""

import dataclasses
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .categories import TRAINING_DEFAULT, allowed, categorise
from .model import feature_vector
from .tiers import TierIndex

TEAM_SIZE = 3
PAGE_SIZE = 100


@dataclasses.dataclass(frozen=True)
class Sample:
    match_id: str
    features: List[float]
    outcome: int  # 1 when alpha won, 0 when beta won
    sources: List[str]


def _roster_from_rounds(match: Dict[str, Any], side: str) -> List[str]:
    """Reconstruct a side from its round entries, ranked by time on the server.

    GET /api/matches/{id} carries no `teams` block — only the match *list* does —
    so a detail payload's roster has to come from the rounds. Where a substitute
    pushes a side past three players, the three who actually played the match are
    the three with the most playtime.
    """
    playtime: Dict[str, float] = {}
    order: List[str] = []
    for round_ in match.get("rounds") or []:
        for entry in round_.get(side) or []:
            player_id = entry["player_id"]
            if player_id not in playtime:
                playtime[player_id] = 0.0
                order.append(player_id)
            playtime[player_id] += entry.get("playtime_percent") or 0

    if len(order) <= TEAM_SIZE:
        return order
    ranked = sorted(order, key=lambda pid: (-playtime[pid], order.index(pid)))
    return ranked[:TEAM_SIZE]


def roster_ids(match: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Both sides' player ids, from `teams` when present, else from the rounds."""
    teams = match.get("teams")
    if teams:
        alpha = [player["player_id"] for player in (teams.get("alpha") or [])]
        beta = [player["player_id"] for player in (teams.get("beta") or [])]
        if alpha or beta:
            return alpha, beta
    return _roster_from_rounds(match, "alpha"), _roster_from_rounds(match, "beta")


def winner_of(match: Dict[str, Any]) -> Optional[str]:
    """"alpha", "beta", or None for a draw or an undecided match.

    `winner` is left empty on matches the API has not settled (state "unknown
    match" and friends), even where the scoreline is decisive — one such match
    reads 0-10 with an empty winner. Falling back to the scores keeps those
    results instead of silently recording them as draws.
    """
    winner = match.get("winner")
    if winner in ("alpha", "beta"):
        return winner
    if winner == "draw":
        return None

    alpha, beta = match.get("alpha_score"), match.get("beta_score")
    if alpha is None or beta is None or alpha == beta:
        return None
    return "alpha" if alpha > beta else "beta"


def match_to_sample(
    match: Dict[str, Any], index: TierIndex, categories=None
) -> Optional[Sample]:
    """None when the match cannot train the model: a draw, an odd roster, or a
    channel the committee does not tier for."""
    if categorise(match) not in allowed(categories, TRAINING_DEFAULT):
        return None

    winner = winner_of(match)
    if winner is None:
        return None

    alpha, beta = roster_ids(match)
    if len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
        return None

    channel_id = match.get("channel_id")
    # Score against the tiers in force on the day, not today's.
    on_date = (match.get("start_time") or "")[:10] or None
    alpha_resolved = index.resolve_all(alpha, channel_id, on_date)
    beta_resolved = index.resolve_all(beta, channel_id, on_date)

    return Sample(
        match_id=match.get("match_id", ""),
        features=feature_vector(
            [r.tier for r in alpha_resolved], [r.tier for r in beta_resolved]
        ),
        outcome=1 if winner == "alpha" else 0,
        sources=[r.source for r in alpha_resolved + beta_resolved],
    )


def iter_samples(
    client, index: TierIndex, to: Optional[str] = None, limit: Optional[int] = None,
    categories=None,
) -> Iterator[Sample]:
    """Walk every finished 3v3 match and yield the usable ones as samples."""
    params = {"size": "3v3", "state": "finished", "to": to}
    for match in client.paginate("/matches", params, page_size=PAGE_SIZE, limit=limit):
        sample = match_to_sample(match, index, categories)
        if sample is not None:
            yield sample
