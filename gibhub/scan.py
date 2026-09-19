"""Population-wide mis-tiering scan.

One sweep of matches scores every tiered player at once, rather than fetching a
report per player. Pure: takes already-fetched matches and returns rows.
"""

import collections
import dataclasses
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .categories import allowed, categorise
from .dataset import TEAM_SIZE, roster_ids, winner_of
from .model import feature_vector, predict
from .report import classify, guess_warning, luck_probability, recommend
from .tiers import IMPUTED, OVERRIDE, TierIndex

# Above this the odds stop measuring evidence and start measuring broken
# assumptions — chiefly that games are independent, which they are not when a
# player shares most of their sample with one teammate.
ODDS_CEILING = 10000
DOMINANT_MATE_SHARE = 0.25
HEAVY_GUESS_SHARE = 0.20
# Games needed to detect a one-tier error at 80% power, from the fitted scale.
ONE_TIER_GAMES = 250


@dataclasses.dataclass(frozen=True)
class ScanRow:
    player_id: str
    nick: str
    tier: str
    games: int
    expected: float
    actual: int
    per_100: float
    tiers_off: float
    luck: float
    label: str
    recommendation: str
    top_mate: str
    top_mate_share: float
    guessed_share: float

    @property
    def odds(self) -> int:
        """1-in-N, capped: beyond the cap it is not evidence any more."""
        if self.luck <= 0:
            return ODDS_CEILING
        return min(int(round(1.0 / self.luck)), ODDS_CEILING)

    @property
    def caution(self) -> str:
        """The reason not to take this row at face value, if there is one."""
        if self.top_mate_share >= DOMINANT_MATE_SHARE:
            return "%.0f%% of games with %s" % (100 * self.top_mate_share, self.top_mate)
        if self.guessed_share >= HEAVY_GUESS_SHARE:
            return "%.0f%% of tiers guessed" % (100 * self.guessed_share)
        if self.games < ONE_TIER_GAMES and abs(self.tiers_off) < 1.0:
            return "only %d games; too few for a 1-tier call" % self.games
        return ""


@dataclasses.dataclass(frozen=True)
class Coverage:
    """How much of the scanned population the committee has actually tiered."""

    players_seen: int
    players_guessed: int
    guessed_share: float

    @property
    def warning(self) -> str:
        return guess_warning(
            {OVERRIDE: self.players_seen - self.players_guessed,
             IMPUTED: self.players_guessed},
            subject="this scan")


def tier_coverage(
    matches: Iterable[Dict[str, Any]],
    index: TierIndex,
    *,
    only: Optional[List[str]] = None,
) -> Coverage:
    """Who turned up, and how many of them the model had to guess a tier for.

    Reported apart from the rows because scan() drops untiered players before
    forming any verdict: a scan can look clean purely because most of the
    population was never scored.
    """
    counted = allowed(only)
    seen: set = set()
    guessed: set = set()

    for match in matches:
        if categorise(match) not in counted:
            continue
        alpha, beta = roster_ids(match)
        if len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
            continue
        channel = match.get("channel_id")
        for player, resolved in zip(alpha + beta,
                                    index.resolve_all(alpha, channel)
                                    + index.resolve_all(beta, channel)):
            seen.add(player)
            if resolved.source == IMPUTED:
                guessed.add(player)

    return Coverage(
        players_seen=len(seen),
        players_guessed=len(guessed),
        guessed_share=(len(guessed) / len(seen)) if seen else 0.0,
    )


def _logit(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return math.log(p / (1 - p))


def scan(
    matches: Iterable[Dict[str, Any]],
    index: TierIndex,
    coefficients: Sequence[float],
    scale: float,
    *,
    min_games: int = 50,
    only: Optional[List[str]] = None,
    nicks: Optional[Dict[str, str]] = None,
) -> List[ScanRow]:
    counted = allowed(only)
    played: Dict[str, List[Any]] = collections.defaultdict(list)
    mates: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    guessed: Dict[str, int] = collections.Counter()

    for match in matches:
        if categorise(match) not in counted:
            continue
        winner = winner_of(match)
        alpha, beta = roster_ids(match)
        if winner is None or len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
            continue

        channel = match.get("channel_id")
        alpha_r = index.resolve_all(alpha, channel)
        beta_r = index.resolve_all(beta, channel)
        p_alpha = predict(coefficients, feature_vector(
            [r.tier for r in alpha_r], [r.tier for r in beta_r]))
        n_guessed = sum(1 for r in alpha_r + beta_r if r.source == IMPUTED)

        for side, probability in ((alpha, p_alpha), (beta, 1.0 - p_alpha)):
            won = (winner == "alpha") if side is alpha else (winner == "beta")
            for player_id in side:
                played[player_id].append((probability, won))
                guessed[player_id] += n_guessed
                for other in side:
                    if other != player_id:
                        mates[player_id][other] += 1

    nicks = nicks or {}
    rows = []
    for player_id, games in played.items():
        tier = index.overrides.get(player_id)
        if not tier or len(games) < min_games:
            continue

        probabilities = [p for p, _ in games]
        actual = sum(1 for _, won in games if won)
        expected = sum(probabilities)
        luck = luck_probability(probabilities, actual)
        label = classify(actual - expected, luck)
        count = len(games)

        mate, shared = mates[player_id].most_common(1)[0] if mates[player_id] else ("", 0)
        rows.append(ScanRow(
            player_id=player_id,
            nick=nicks.get(player_id, player_id[:8]),
            tier=tier,
            games=count,
            expected=expected,
            actual=actual,
            per_100=100.0 * (actual - expected) / count,
            tiers_off=(_logit(actual / count) - _logit(expected / count)) / scale,
            luck=luck,
            label=label,
            recommendation=recommend(label, tier),
            top_mate=nicks.get(mate, mate[:8] if mate else ""),
            top_mate_share=shared / count if count else 0.0,
            guessed_share=guessed[player_id] / (2 * TEAM_SIZE * count) if count else 0.0,
        ))

    # Effect size first: the odds are the least trustworthy number here.
    rows.sort(key=lambda r: -abs(r.per_100))
    return rows
