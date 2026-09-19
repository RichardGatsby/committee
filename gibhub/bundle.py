"""Persistence for the fitted model bundle."""

import dataclasses
import json
import os
import tempfile
from typing import Dict, List, Optional, Tuple

from .history import TierChange, TierHistory
from .model import TIERS
from .tiers import Holding, TierIndex

DEFAULT_PATH = "coefficients.json"


class BundleMissing(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Bundle:
    fitted_at: str
    data_cutoff: str
    sample_size: int
    coefficients: List[float]
    fit_metrics: Dict[str, float]
    bands: Dict[str, float]
    utro: Dict[str, float]
    holdings: Dict[str, Tuple[Holding, ...]]
    channel_names: Dict[str, str]
    # Channels the tier index was restricted to at fit time; empty means all.
    tier_channels: List[str] = dataclasses.field(default_factory=list)
    # Fixed committee points per tier, when the fit was constrained to them.
    # Empty means the six coefficients were fitted freely.
    tier_points: Dict[str, float] = dataclasses.field(default_factory=dict)
    # Log-odds per point of team advantage; only meaningful with tier_points.
    scale: Optional[float] = None
    # Strongest tier imputation may assign; None means uncapped.
    impute_max: Optional[str] = None
    # player_id -> tier, supplied by the committee rather than the API.
    overrides: Dict[str, str] = dataclasses.field(default_factory=dict)
    # Earliest match in the training set. None on bundles fitted before this
    # was recorded; sample_size alone says nothing about how far back it goes.
    data_start: Optional[str] = None
    # Dated committee decisions, oldest first. Empty until one is logged.
    history: List[TierChange] = dataclasses.field(default_factory=list)

    def index(self) -> TierIndex:
        return TierIndex(holdings=self.holdings, bands=self.bands, utro=self.utro,
                         impute_max=self.impute_max, overrides=self.overrides,
                         history=TierHistory.build(self.history))


def save(bundle: Bundle, path=DEFAULT_PATH) -> None:
    payload = {
        "fitted_at": bundle.fitted_at,
        "data_cutoff": bundle.data_cutoff,
        "sample_size": bundle.sample_size,
        # Keyed by tier name so a change to TIERS ordering cannot silently
        # reinterpret an existing bundle.
        "coefficients": dict(zip(TIERS, bundle.coefficients)),
        "fit_metrics": bundle.fit_metrics,
        "bands": bundle.bands,
        "utro": bundle.utro,
        "holdings": {
            player_id: [dataclasses.asdict(holding) for holding in holdings]
            for player_id, holdings in sorted(bundle.holdings.items())
        },
        "channel_names": bundle.channel_names,
        "tier_channels": bundle.tier_channels,
        "tier_points": bundle.tier_points,
        "scale": bundle.scale,
        "impute_max": bundle.impute_max,
        "overrides": bundle.overrides,
        "data_start": bundle.data_start,
        "history": [dataclasses.asdict(change) for change in bundle.history],
    }
    destination = str(path)
    directory = os.path.dirname(destination) or "."
    os.makedirs(directory, exist_ok=True)
    # A unique temp name per writer, and the same rename dance cache.py uses:
    # a shared ".tmp" lets two concurrent refits clobber each other, and the
    # loser's os.replace then fails with ENOENT.
    handle_fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
        os.replace(temporary, destination)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def load(path=DEFAULT_PATH) -> Bundle:
    if not os.path.exists(str(path)):
        raise BundleMissing(
            "no model bundle at %s - run: python3 -m gibhub.cli fit --refit" % path
        )
    with open(str(path), "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    return Bundle(
        fitted_at=payload["fitted_at"],
        data_cutoff=payload["data_cutoff"],
        sample_size=payload["sample_size"],
        coefficients=[payload["coefficients"][tier] for tier in TIERS],
        fit_metrics=payload["fit_metrics"],
        bands=payload["bands"],
        utro=payload["utro"],
        holdings={
            player_id: tuple(Holding(**holding) for holding in holdings)
            for player_id, holdings in payload["holdings"].items()
        },
        channel_names=payload.get("channel_names", {}),
        tier_channels=payload.get("tier_channels", []),
        tier_points=payload.get("tier_points", {}),
        scale=payload.get("scale"),
        impute_max=payload.get("impute_max"),
        overrides=payload.get("overrides", {}),
        data_start=payload.get("data_start"),
        history=[TierChange(**entry) for entry in payload.get("history") or []],
    )
