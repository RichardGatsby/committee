"""Pure assembly of a player's evidence report. No I/O."""

import dataclasses
from typing import Any, Dict, List, Optional, Sequence

from .dataset import TEAM_SIZE, roster_ids, winner_of
from .model import feature_vector, points_delta, predict
from .tiers import CROSS_CHANNEL, EXACT, IMPUTED, TierIndex

OVER_UNDER_THRESHOLD = 1.5


def side_of(match: Dict[str, Any], player_id: str) -> Optional[str]:
    alpha, beta = roster_ids(match)
    if player_id in alpha:
        return "alpha"
    if player_id in beta:
        return "beta"
    return None


def weighted_utro(match: Dict[str, Any], player_id: str) -> Optional[float]:
    """The player's UTRO across the match, weighted by time on the server.

    None when the player appears in no round with both a UTRO and playtime — a
    substitute, or a match predating the stats version that reports UTRO.
    """
    total_weight = 0.0
    total = 0.0

    for round_ in match.get("rounds") or []:
        for side in ("alpha", "beta"):
            for entry in round_.get(side) or []:
                if entry.get("player_id") != player_id:
                    continue
                utro = entry.get("utro")
                weight = entry.get("playtime_percent") or 0
                if utro is None or weight <= 0:
                    continue
                total += utro * weight
                total_weight += weight

    if total_weight == 0.0:
        return None
    return total / total_weight


@dataclasses.dataclass(frozen=True)
class MatchRow:
    match_id: str
    date: str
    maps: List[str]
    side: str
    expected: float
    result: str  # "W", "L" or "D"
    utro: Optional[float]
    utro_delta: Optional[float]
    sources: List[str]
    upset: bool
    # Team points minus opponent points, from the committee's tier scale.
    # None when the model was fitted without a fixed points scale.
    points: Optional[float] = None


@dataclasses.dataclass(frozen=True)
class PlayerReport:
    player_id: str
    nick: str
    discord_nick: str
    tiers: List[Dict[str, Any]]
    lifetime: Dict[str, Any]
    percentiles: List[Any]
    rows: List[MatchRow]
    expected_wins: float
    actual_wins: int
    delta: float
    label: str
    upset_wins: int
    upset_losses: int
    # The other half of the 2x2: results that went the way the tiers predicted.
    stack_wins: int        # favoured (expected > 50%) and won
    underdog_losses: int   # underdog (expected < 50%) and lost
    even_matches: int      # expected exactly 50%, neither favoured nor underdog
    draws: int
    skipped: int
    source_counts: Dict[str, int]
    provenance: Dict[str, Any]


def classify(delta: float) -> str:
    """OVER / UNDER / ON TIER, at the +-1.5 win threshold from the spec."""
    if delta >= OVER_UNDER_THRESHOLD:
        return "OVER"
    if delta <= -OVER_UNDER_THRESHOLD:
        return "UNDER"
    return "ON TIER"


def _lifetime_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
    lifetime = profile.get("lifetime") or {}
    wins = lifetime.get("match_wins") or 0
    losses = lifetime.get("match_losses") or 0
    draws = lifetime.get("match_draws") or 0
    decided = wins + losses
    return {
        "matches": lifetime.get("matches") or 0,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": (wins / decided) if decided else 0.0,
        "utro": lifetime.get("utro"),
        "kdr": lifetime.get("kdr"),
    }


def build_report(
    profile: Dict[str, Any],
    spider: Dict[str, Any],
    details: Sequence[Dict[str, Any]],
    index: TierIndex,
    coefficients: Sequence[float],
    provenance: Dict[str, Any],
    tier_points: Optional[Dict[str, float]] = None,
) -> PlayerReport:
    player_id = profile["player_id"]
    baseline = (profile.get("lifetime") or {}).get("utro")

    rows: List[MatchRow] = []
    counts = {EXACT: 0, CROSS_CHANNEL: 0, IMPUTED: 0}
    expected_wins = 0.0
    actual_wins = 0
    upset_wins = 0
    upset_losses = 0
    stack_wins = 0
    underdog_losses = 0
    even_matches = 0
    draws = 0
    skipped = 0

    for match in details:
        side = side_of(match, player_id)
        alpha, beta = roster_ids(match)
        if side is None or len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
            skipped += 1
            continue

        channel_id = match.get("channel_id")
        alpha_resolved = index.resolve_all(alpha, channel_id)
        beta_resolved = index.resolve_all(beta, channel_id)
        for resolved in alpha_resolved + beta_resolved:
            counts[resolved.source] += 1

        features = feature_vector(
            [r.tier for r in alpha_resolved], [r.tier for r in beta_resolved]
        )
        p_alpha = predict(coefficients, features)
        expected = p_alpha if side == "alpha" else 1.0 - p_alpha

        delta_points = None
        if tier_points:
            delta_points = points_delta(features, tier_points)
            if side == "beta":
                delta_points = -delta_points
            delta_points = delta_points or 0.0  # normalise -0.0

        winner = winner_of(match)
        if winner is None:
            result = "D"
            draws += 1
        elif winner == side:
            result = "W"
        else:
            result = "L"

        upset = False
        if result in ("W", "L"):
            expected_wins += expected
            if expected == 0.5:
                even_matches += 1
            if result == "W":
                actual_wins += 1
                upset = expected < 0.5
                if upset:
                    upset_wins += 1
                elif expected > 0.5:
                    stack_wins += 1
            else:
                upset = expected > 0.5
                if upset:
                    upset_losses += 1
                elif expected < 0.5:
                    underdog_losses += 1

        utro = weighted_utro(match, player_id)
        rows.append(
            MatchRow(
                match_id=match.get("match_id", ""),
                date=(match.get("start_time") or "")[:10],
                maps=[entry.get("map", "") for entry in (match.get("maps") or [])],
                side=side,
                expected=expected,
                result=result,
                utro=utro,
                utro_delta=(utro - baseline) if (utro is not None and baseline) else None,
                sources=[r.source for r in alpha_resolved + beta_resolved],
                upset=upset,
                points=delta_points,
            )
        )

    delta = actual_wins - expected_wins
    spider_metrics = spider.get("metrics") or []

    return PlayerReport(
        player_id=player_id,
        nick=profile.get("nick") or "",
        discord_nick=profile.get("discord_nick") or "",
        tiers=[t for t in (profile.get("tiers") or []) if t.get("size") == 6],
        lifetime=_lifetime_summary(profile),
        percentiles=[(m["key"], m["percentile"]) for m in spider_metrics],
        rows=rows,
        expected_wins=expected_wins,
        actual_wins=actual_wins,
        delta=delta,
        label=classify(delta),
        upset_wins=upset_wins,
        upset_losses=upset_losses,
        stack_wins=stack_wins,
        underdog_losses=underdog_losses,
        even_matches=even_matches,
        draws=draws,
        skipped=skipped,
        source_counts=counts,
        provenance=provenance,
    )
