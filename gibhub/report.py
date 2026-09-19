"""Pure assembly of a player's evidence report. No I/O."""

import dataclasses
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .categories import allowed, categorise, split
from .dataset import TEAM_SIZE, roster_ids, winner_of
from .model import feature_vector, points_delta, predict
from .model import TIER_POINTS
from .tiers import CROSS_CHANNEL, EXACT, IMPUTED, OVERRIDE, TierIndex

# Verdict thresholds on the probability that a gap this big is luck. Chosen so
# the wording means the same thing whether a window holds 20 matches or 400.
CLEAR_P = 0.01
LIKELY_P = 0.05


def nicks_of(match: Dict[str, Any]) -> Dict[str, str]:
    """player_id -> display nick, from the round entries.

    A detail payload has no `teams` block, so names come from the rounds.
    """
    names: Dict[str, str] = {}
    for round_ in match.get("rounds") or []:
        for side in ("alpha", "beta"):
            for entry in round_.get(side) or []:
                if entry["player_id"] not in names:
                    names[entry["player_id"]] = (
                        entry.get("discord_nick") or entry.get("nick") or "")
    for side in ("alpha", "beta"):
        for entry in (match.get("teams") or {}).get(side) or []:
            names.setdefault(
                entry["player_id"], entry.get("discord_nick") or entry.get("nick") or "")
    return names


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
    # (nick, tier, source) per player, his side first then the opposition.
    team: List[Any] = dataclasses.field(default_factory=list)
    opponents: List[Any] = dataclasses.field(default_factory=list)
    channel: str = ""
    score: str = ""
    category: str = ""


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
    # Chance a gap this big is luck, and the gap as wins per 100 games.
    luck: float
    per_100: float
    decided: int
    # The tier this verdict is about, and what to do with it.
    current_tier: Optional[str]
    recommendation: str
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
    # Per-category splits: (key, decided, expected, actual, luck, verdict).
    categories: List[Any] = dataclasses.field(default_factory=list)
    # Distinct people in the window, and how many had no committee tier.
    players_seen: int = 0
    players_guessed: int = 0


# Share of tier inputs that had to be guessed before the verdict stops being
# worth much. Imputation error, not luck, is the dominant source of false signal
# here: one player's apparent overperformance fell from +24.7 to +10.3 as the
# guessing was tightened.
CAUTION_GUESS_SHARE = 0.20
UNRELIABLE_GUESS_SHARE = 0.40


def guess_warning(
    source_counts: Mapping[str, int], *, subject: str = "this verdict"
) -> str:
    """How loudly to disclaim a verdict built on imputed tiers.

    Only IMPUTED counts as a guess. A cross-channel tier is a real committee
    decision made in another channel, not an invention.
    """
    total = sum(source_counts.values())
    if not total:
        return ""
    share = source_counts.get(IMPUTED, 0) / total
    if share >= UNRELIABLE_GUESS_SHARE:
        return ("UNRELIABLE: %.0f%% of the tiers behind %s were guessed rather "
                "than set by the committee. Tier those players before acting "
                "on it." % (100 * share, subject))
    if share >= CAUTION_GUESS_SHARE:
        return ("CAUTION: %.0f%% of the tiers behind %s were guessed rather "
                "than set by the committee." % (100 * share, subject))
    return ""


def luck_probability(probabilities: Sequence[float], actual: int) -> float:
    """Chance of a gap at least this large, in this direction, by luck alone.

    Exact Poisson-binomial tail: each match has its own win probability, so the
    usual binomial formula does not apply. Returns 1.0 with nothing to judge.
    """
    if not probabilities:
        return 1.0

    distribution = [1.0]
    for p in probabilities:
        nxt = [0.0] * (len(distribution) + 1)
        for wins, mass in enumerate(distribution):
            nxt[wins] += mass * (1.0 - p)
            nxt[wins + 1] += mass * p
        distribution = nxt

    expected = sum(probabilities)
    if actual >= expected:
        return sum(distribution[actual:])
    return sum(distribution[:actual + 1])


def stronger_and_weaker(tier: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """The tiers either side of `tier` by strength, not by letter.

    The letters are not an ordered ladder — E sits between S and A — so the
    neighbours come off the points scale.
    """
    if tier not in TIER_POINTS:
        return None, None
    ladder = sorted(TIER_POINTS, key=lambda t: -TIER_POINTS[t])
    index = ladder.index(tier)
    return (ladder[index - 1] if index > 0 else None,
            ladder[index + 1] if index < len(ladder) - 1 else None)


def recommend(label: str, tier: Optional[str]) -> str:
    """Say plainly what to do about the tier, not just how the results read."""
    if label == "ON TIER":
        return "KEEP at %s" % tier if tier else "KEEP current tier"

    up, down = stronger_and_weaker(tier)
    # OVER means they win more than the tier predicts, so the tier is too low.
    target = up if label.endswith("OVER") else down
    direction = "UP" if label.endswith("OVER") else "DOWN"
    strength = "MOVE" if label.startswith("CLEARLY") else "CONSIDER MOVING"

    if tier and target:
        return "%s %s: %s → %s" % (strength, direction, tier, target)
    if tier:
        # The ends of the ladder: S cannot go up, D cannot go down. Say that
        # outright rather than issuing a move with nowhere to move to.
        if direction == "UP":
            return "NO HIGHER TIER: already %s, and beating it" % tier
        return "NO LOWER TIER: already %s, and losing below it" % tier
    return "%s %s" % (strength, direction)


def classify(delta: float, probability: float) -> str:
    """The committee-facing verdict.

    Reads off how likely the gap is to be luck, not off a raw win count: a
    +4 win gap is decisive over 20 matches and meaningless over 400.
    """
    direction = "OVER" if delta > 0 else "UNDER"
    if probability < CLEAR_P:
        return "CLEARLY %s" % direction
    if probability < LIKELY_P:
        return direction
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
    only: Optional[Sequence[str]] = None,
    tier_channel_ids: Optional[Sequence[str]] = None,
) -> PlayerReport:
    player_id = profile["player_id"]
    baseline = (profile.get("lifetime") or {}).get("utro")

    rows: List[MatchRow] = []
    counts = {OVERRIDE: 0, EXACT: 0, CROSS_CHANNEL: 0, IMPUTED: 0}
    seen: set = set()
    guessed_players: set = set()
    expected_wins = 0.0
    actual_wins = 0
    upset_wins = 0
    upset_losses = 0
    stack_wins = 0
    underdog_losses = 0
    even_matches = 0
    draws = 0
    skipped = 0

    # The tier the verdict is about: a committee override first, since the API
    # does not carry those, then whatever the profile lists for the scored channel.
    profile_tiers = [
        t for t in (profile.get("tiers") or [])
        if t.get("size") == 6
        and (not tier_channel_ids or t.get("channel_id") in tier_channel_ids)
    ]
    current_tier = index.overrides.get(player_id) or (
        profile_tiers[0]["tier"] if profile_tiers else None)

    counted = allowed(only)
    for match in details:
        if categorise(match) not in counted:
            continue
        side = side_of(match, player_id)
        alpha, beta = roster_ids(match)
        if side is None or len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
            skipped += 1
            continue

        channel_id = match.get("channel_id")
        alpha_resolved = index.resolve_all(alpha, channel_id)
        beta_resolved = index.resolve_all(beta, channel_id)
        for player, resolved in zip(alpha + beta, alpha_resolved + beta_resolved):
            counts[resolved.source] += 1
            seen.add(player)
            if resolved.source == IMPUTED:
                guessed_players.add(player)

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

        names = nicks_of(match)
        lineup = [
            [(names.get(p, p[:8]), r.tier, r.source) for p, r in zip(ids, res)]
            for ids, res in ((alpha, alpha_resolved), (beta, beta_resolved))
        ]
        own, other = lineup if side == "alpha" else lineup[::-1]

        # match_score is alpha-beta; show it from his side.
        a_score, b_score = match.get("alpha_score"), match.get("beta_score")
        if a_score is None or b_score is None:
            score = match.get("match_score") or ""
        else:
            score = "%d-%d" % ((a_score, b_score) if side == "alpha" else (b_score, a_score))

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
                team=own,
                opponents=other,
                channel=match.get("channel_name") or "",
                score=score,
                category=categorise(match),
            )
        )

    delta = actual_wins - expected_wins
    decided = sum(1 for row in rows if row.result in ("W", "L"))
    luck = luck_probability([row.expected for row in rows if row.result in ("W", "L")],
                            actual_wins)
    categories = []
    for key, group in split(rows):
        decided_rows = [r for r in group if r.result in ("W", "L")]
        if not decided_rows:
            continue
        won = sum(1 for r in decided_rows if r.result == "W")
        exp = sum(r.expected for r in decided_rows)
        group_luck = luck_probability([r.expected for r in decided_rows], won)
        categories.append((key, len(decided_rows), exp, won, group_luck,
                           classify(won - exp, group_luck)))

    spider_metrics = spider.get("metrics") or []

    return PlayerReport(
        player_id=player_id,
        nick=profile.get("nick") or "",
        discord_nick=profile.get("discord_nick") or "",
        tiers=profile_tiers,
        lifetime=_lifetime_summary(profile),
        percentiles=[(m["key"], m["percentile"]) for m in spider_metrics],
        rows=rows,
        expected_wins=expected_wins,
        actual_wins=actual_wins,
        delta=delta,
        label=classify(delta, luck),
        luck=luck,
        current_tier=current_tier,
        recommendation=recommend(classify(delta, luck), current_tier),
        per_100=(100.0 * delta / decided) if decided else 0.0,
        decided=decided,
        upset_wins=upset_wins,
        upset_losses=upset_losses,
        stack_wins=stack_wins,
        underdog_losses=underdog_losses,
        even_matches=even_matches,
        draws=draws,
        skipped=skipped,
        source_counts=counts,
        players_seen=len(seen),
        players_guessed=len(guessed_players),
        provenance=provenance,
        categories=categories,
    )
