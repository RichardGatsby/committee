import json

import pytest

from gibhub.bundle import Bundle, BundleMissing, load, save
from gibhub.tiers import Holding


def _bundle():
    return Bundle(
        fitted_at="2026-09-18T12:00:00+00:00",
        data_cutoff="2026-09-18",
        sample_size=4200,
        coefficients=[0.9, 0.6, 0.3, 0.0, -0.4, -0.8],
        fit_metrics={"log_loss": 0.62, "brier": 0.21, "accuracy": 0.66, "samples": 4200},
        bands={"S": 1.3, "A": 1.15, "B": 1.0, "C": 0.9, "D": 0.8, "E": 0.7},
        utro={"p1": 1.24},
        holdings={"p1": (Holding("poland", "A", "2026-09-18T08:37:09+02:00"),)},
        channel_names={"poland": "Poland ET:Legacy: #3v3"},
    )


def test_a_bundle_round_trips_through_disk(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), path)
    assert load(path) == _bundle()


def test_the_saved_file_is_readable_json(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["coefficients"] == {"S": 0.9, "A": 0.6, "B": 0.3, "C": 0.0, "D": -0.4, "E": -0.8}
    assert payload["holdings"]["p1"][0]["tier"] == "A"
    assert payload["sample_size"] == 4200


def test_loading_a_missing_bundle_tells_the_user_to_fit(tmp_path):
    with pytest.raises(BundleMissing, match=r"fit --refit"):
        load(tmp_path / "nope.json")


def test_a_bundle_exposes_a_tier_index():
    index = _bundle().index()
    assert index.resolve("p1", "poland").tier == "A"
    assert index.resolve("p1", "poland").source == "exact"


def test_coefficients_are_saved_by_tier_name_not_position(tmp_path):
    """Positional coefficients would silently corrupt if TIERS ever changed order."""
    path = tmp_path / "coefficients.json"
    save(_bundle(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload["coefficients"], dict)
