"""Fetching the raw material a model bundle is built from."""

import datetime
from typing import Dict, Tuple

from .bundle import Bundle
from .dataset import iter_samples
from .model import TIERS, fit, fit_points, metrics
from .history import TierHistory
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


def filter_holdings(holdings, channel_names, tokens):
    """Keep only tiers assigned in the named channels.

    A token matches a channel id exactly, or any case-insensitive substring of a
    channel name ("events" matches "ET:Legacy Events: #3vs3"). Players left with
    no holding drop out of the index entirely and are imputed instead.
    """
    if not tokens:
        return holdings, channel_names

    lowered = [token.lower() for token in tokens]

    def keep(channel_id):
        name = (channel_names.get(channel_id) or "").lower()
        return any(token == channel_id or (token and token in name) for token in lowered)

    kept = {}
    for player_id, entries in holdings.items():
        matching = tuple(entry for entry in entries if keep(entry.channel_id))
        if matching:
            kept[player_id] = matching

    names = {cid: name for cid, name in channel_names.items() if keep(cid)}
    if not kept:
        raise ValueError(
            "no 3v3 tiers match channel filter %r; known channels: %s"
            % (tokens, ", ".join(sorted(channel_names.values())) or "none")
        )
    return kept, names


def build_bundle(client, to=None, limit=None, tier_channels=None, points=None,
                 impute_max=None, overrides=None, history=None) -> Bundle:
    """Fetch everything, fit, and return a bundle ready to save."""
    utro = fetch_utro(client)
    holdings, channel_names = fetch_tier_holdings(client)
    holdings, channel_names = filter_holdings(holdings, channel_names, tier_channels)

    holders = {tier: [] for tier in TIERS}
    for player_id, entries in holdings.items():
        for entry in entries:
            holders[entry.tier].append(player_id)
    bands = build_bands(holders, utro)

    changes = list(history or [])
    index = TierIndex(holdings=holdings, bands=bands, utro=utro,
                      impute_max=impute_max, overrides=overrides or {},
                      history=TierHistory.build(changes))
    samples = list(iter_samples(client, index, to=to, limit=limit))
    if not samples:
        raise ValueError("no usable 3v3 matches found; cannot fit")

    # How far back the training set actually reaches. sample_size alone reads
    # like a count of some window; it is the whole history the fit could see.
    dated = sorted(sample.date for sample in samples if sample.date)
    data_start = dated[0] if dated else None

    training = [(sample.features, sample.outcome) for sample in samples]
    if points:
        scale, coefficients = fit_points(training, points)
    else:
        scale, coefficients = None, fit(training)

    return Bundle(
        fitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        data_cutoff=to or datetime.date.today().isoformat(),
        data_start=data_start,
        sample_size=len(samples),
        coefficients=coefficients,
        fit_metrics=metrics(coefficients, training),
        bands=bands,
        utro=utro,
        holdings=holdings,
        channel_names=channel_names,
        tier_channels=list(tier_channels or []),
        tier_points=dict(points or {}),
        scale=scale,
        impute_max=impute_max,
        overrides=dict(overrides or {}),
        history=changes,
    )
