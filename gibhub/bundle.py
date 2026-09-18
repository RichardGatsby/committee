"""Persistence for the fitted model bundle."""

import dataclasses
import json
import os
from typing import Dict, List, Tuple

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

    def index(self) -> TierIndex:
        return TierIndex(holdings=self.holdings, bands=self.bands, utro=self.utro)


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
    }
    temporary = str(path) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
    os.replace(temporary, str(path))


def load(path=DEFAULT_PATH) -> Bundle:
    if not os.path.exists(str(path)):
        raise BundleMissing(
            "no model bundle at %s — run: python3 -m gibhub.cli fit --refit" % path
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
    )
