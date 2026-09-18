"""Tier resolution. Pure functions over data that build.py has already fetched."""

import dataclasses
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .model import TIERS

EXACT = "exact"
CROSS_CHANNEL = "cross_channel"
IMPUTED = "imputed"


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def build_bands(
    holders: Mapping[str, Iterable[str]], utro: Mapping[str, float]
) -> Dict[str, float]:
    """Median UTRO per tier. Tiers whose holders all lack a UTRO are dropped."""
    bands = {}
    for tier, player_ids in holders.items():
        values = [utro[pid] for pid in player_ids if pid in utro]
        if values:
            bands[tier] = _median(values)
    return bands


def nearest_tier(bands: Mapping[str, float], utro: Optional[float]) -> str:
    """The tier whose band is closest to `utro`.

    Ties go to the tier with the higher band — the empirically stronger one — and
    then to the label, so the result never depends on dict ordering. Note that the
    tie-break reads strength from the data, not from the letters: in this dataset
    E is the second-strongest tier, not the weakest (see README).

    With no UTRO at all, the median band stands in for the player.
    """
    if not bands:
        raise ValueError("no tier bands available")
    if utro is None:
        utro = _median(list(bands.values()))
    return min(bands, key=lambda tier: (abs(bands[tier] - utro), -bands[tier], tier))


@dataclasses.dataclass(frozen=True)
class Holding:
    """A tier a player holds in one channel."""

    channel_id: str
    tier: str
    updated_at: str


@dataclasses.dataclass(frozen=True)
class ResolvedTier:
    tier: str
    source: str  # EXACT, CROSS_CHANNEL or IMPUTED


@dataclasses.dataclass(frozen=True)
class TierIndex:
    """Everything needed to assign a tier to any player in any channel."""

    holdings: Mapping[str, Sequence[Holding]]
    bands: Mapping[str, float]
    utro: Mapping[str, float]

    def resolve(self, player_id: str, channel_id: Optional[str]) -> ResolvedTier:
        held = self.holdings.get(player_id) or ()

        for holding in held:
            if holding.channel_id == channel_id:
                return ResolvedTier(holding.tier, EXACT)

        if held:
            # No tier in this channel: fall back to the most recently updated one.
            newest = max(held, key=lambda holding: holding.updated_at)
            return ResolvedTier(newest.tier, CROSS_CHANNEL)

        return ResolvedTier(nearest_tier(self.bands, self.utro.get(player_id)), IMPUTED)

    def resolve_all(
        self, player_ids: Iterable[str], channel_id: Optional[str]
    ) -> List[ResolvedTier]:
        return [self.resolve(player_id, channel_id) for player_id in player_ids]

    def tiers_of(self, player_ids: Iterable[str], channel_id: Optional[str]) -> List[str]:
        return [resolved.tier for resolved in self.resolve_all(player_ids, channel_id)]
