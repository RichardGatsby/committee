"""Fetching the raw material a model bundle is built from."""

import datetime
from typing import Dict, Tuple

from .bundle import Bundle
from .dataset import iter_samples
from .model import TIERS, fit, metrics
from .tiers import Holding, TierIndex, build_bands

SIZE_3V3 = "3v3"
ROUNDS_3V3 = 6  # the API reports a 3v3 match as size 6 (players per match)
MIN_ROUNDS = 10
PAGE_SIZE = 100  # /leaderboards rejects anything above 100


def fetch_utro(client, min_rounds: int = MIN_ROUNDS) -> Dict[str, float]:
    """Sample-regularised 3v3 UTRO for every player, in one sweep.

    `utro_shrunken` rather than `utro`: the raw board is topped by players with a
    single round, which would wreck imputation.
    """
    values = {}
    params = {"metric": "utro_shrunken", "size": SIZE_3V3, "minGames": 1}
    for row in client.paginate("/leaderboards", params, page_size=PAGE_SIZE):
        if (row.get("rounds") or 0) < min_rounds:
            continue
        values[row["player_id"]] = row["value"]
    return values


def fetch_tier_holdings(client) -> Tuple[Dict[str, Tuple[Holding, ...]], Dict[str, str]]:
    """Per-channel 3v3 tiers for every tiered player, plus channel display names.

    The tier listing endpoint returns neither the channel nor the tier on each row,
    so each tiered player's profile has to be read for its `tiers[]` block.
    """
    player_ids = []
    for tier in TIERS:
        params = {"size": SIZE_3V3, "tier": tier}
        for row in client.paginate("/players", params, page_size=PAGE_SIZE):
            if row["player_id"] not in player_ids:
                player_ids.append(row["player_id"])

    holdings = {}
    channel_names = {}
    for player_id in player_ids:
        profile = client.get("/players/" + player_id, {"size": SIZE_3V3})
        entries = []
        for entry in profile.get("tiers") or []:
            if entry.get("size") != ROUNDS_3V3:
                continue  # a 6v6 tier says nothing about 3v3
            entries.append(
                Holding(
                    channel_id=entry["channel_id"],
                    tier=entry["tier"],
                    updated_at=entry["updated_at"],
                )
            )
            if entry.get("channel_name"):
                channel_names[entry["channel_id"]] = entry["channel_name"]
        if entries:
            holdings[player_id] = tuple(entries)

    return holdings, channel_names


def build_bundle(client, to=None, limit=None) -> Bundle:
    """Fetch everything, fit, and return a bundle ready to save."""
    utro = fetch_utro(client)
    holdings, channel_names = fetch_tier_holdings(client)

    holders = {tier: [] for tier in TIERS}
    for player_id, entries in holdings.items():
        for entry in entries:
            holders[entry.tier].append(player_id)
    bands = build_bands(holders, utro)

    index = TierIndex(holdings=holdings, bands=bands, utro=utro)
    samples = list(iter_samples(client, index, to=to, limit=limit))
    if not samples:
        raise ValueError("no usable 3v3 matches found; cannot fit")

    training = [(sample.features, sample.outcome) for sample in samples]
    coefficients = fit(training)

    return Bundle(
        fitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        data_cutoff=to or datetime.date.today().isoformat(),
        sample_size=len(samples),
        coefficients=coefficients,
        fit_metrics=metrics(coefficients, training),
        bands=bands,
        utro=utro,
        holdings=holdings,
        channel_names=channel_names,
    )
