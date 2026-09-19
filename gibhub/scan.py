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
from .report import (ONE_TIER_GAMES, classify, guess_warning,
                     luck_probability, recommend)
from .tiers import IMPUTED, OVERRIDE, TierIndex

# Above this the odds stop measuring evidence and start measuring broken
# assumptions — chiefly that games are independent, which they are not when a
# player shares most of their sample with one teammate.
ODDS_CEILING = 10000
DOMINANT_MATE_SHARE = 0.25
HEAVY_GUESS_SHARE = 0.20


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
    # The last in-window date the committee changed this player's tier, and how
    # many of `games` fall after it. Equal to `games` when nothing changed.
    changed_on: str = ""
    games_at_tier: int = 0

    @property
    def odds(self) -> int:
        """1-in-N, capped: beyond the cap it is not evidence any more."""
        if self.luck <= 0:
            return ODDS_CEILING
        return min(int(round(1.0 / self.luck)), ODDS_CEILING)

    @property
    def caution(self) -> str:
        """The reason not to take this row at face value, if there is one."""
        # First, because it says the verdict rests on part of the sample.
        if self.changed_on:
            return "tier changed %s; %d games at %s" % (
                self.changed_on, self.games_at_tier, self.tier)
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
        # Score against the tiers in force on the day, not today's.
        on_date = (match.get("start_time") or "")[:10] or None
        alpha_r = index.resolve_all(alpha, channel, on_date)
        beta_r = index.resolve_all(beta, channel, on_date)
        p_alpha = predict(coefficients, feature_vector(
            [r.tier for r in alpha_r], [r.tier for r in beta_r]))
        n_guessed = sum(1 for r in alpha_r + beta_r if r.source == IMPUTED)

        for side, probability in ((alpha, p_alpha), (beta, 1.0 - p_alpha)):
            won = (winner == "alpha") if side is alpha else (winner == "beta")
            for player_id in side:
                played[player_id].append((probability, won, on_date))
                guessed[player_id] += n_guessed
                for other in side:
                    if other != player_id:
                        mates[player_id][other] += 1

    nicks = nicks or {}
    window = [date for entries in played.values() for _, _, date in entries if date]
    first, last = (min(window), max(window)) if window else (None, None)

    rows = []
    for player_id, games in played.items():
        tier = index.overrides.get(player_id)
        if not tier or len(games) < min_games:
            continue

        count = len(games)
        # A tier change inside the window splits the record: only the games
        # since it test the tier the player holds now.
        inside = index.history.changes_in(player_id, first, last)
        changed_on = max(inside) if inside else ""
        current = [g for g in games
                   if not changed_on or (g[2] or "") >= changed_on]

        probabilities = [p for p, _, _ in current]
        actual = sum(1 for _, won, _ in current if won)
        expected = sum(probabilities)
        luck = luck_probability(probabilities, actual)
        label = classify(actual - expected, luck)
        scored = len(current)

        mate, shared = mates[player_id].most_common(1)[0] if mates[player_id] else ("", 0)
        rows.append(ScanRow(
            player_id=player_id,
            nick=nicks.get(player_id, player_id[:8]),
            tier=tier,
            games=count,
            expected=expected,
            actual=actual,
            per_100=100.0 * (actual - expected) / scored,
            tiers_off=(_logit(actual / scored) - _logit(expected / scored)) / scale,
            luck=luck,
            label=label,
            recommendation=recommend(label, tier),
            top_mate=nicks.get(mate, mate[:8] if mate else ""),
            top_mate_share=shared / count if count else 0.0,
            guessed_share=guessed[player_id] / (2 * TEAM_SIZE * count) if count else 0.0,
            changed_on=changed_on,
            games_at_tier=scored,
        ))

    # Effect size first: the odds are the least trustworthy number here.
    rows.sort(key=lambda r: -abs(r.per_100))
    return rows
