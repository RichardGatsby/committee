import dataclasses
import json

import pytest

from gibhub.bundle import Bundle, BundleMissing, load, save
from gibhub.history import TierChange
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


def test_save_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), str(path))
    assert [p.name for p in tmp_path.iterdir()] == ["coefficients.json"]


def test_save_does_not_collide_with_a_concurrent_writer(tmp_path, monkeypatch):
    """Two writers must not share one temp name.

    cache.py had this bug: the loser's os.replace fired after the winner had
    already renamed the shared .tmp away, and failed with ENOENT. Simulate the
    interleaving by saving again from inside the first save's json.dump.
    """
    path = tmp_path / "coefficients.json"
    real_dump = json.dump
    nested = []

    def dump_then_interleave(payload, handle, **kwargs):
        real_dump(payload, handle, **kwargs)
        if not nested:
            nested.append(True)
            monkeypatch.setattr(json, "dump", real_dump)
            save(_bundle(), str(path))

    monkeypatch.setattr(json, "dump", dump_then_interleave)
    save(_bundle(), str(path))

    assert json.loads(path.read_text())["sample_size"] == 4200
    assert [p.name for p in tmp_path.iterdir()] == ["coefficients.json"]


def test_save_removes_the_temp_file_when_serialisation_fails(tmp_path, monkeypatch):
    path = tmp_path / "coefficients.json"

    def explode(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(json, "dump", explode)
    with pytest.raises(ValueError, match="boom"):
        save(_bundle(), str(path))
    assert list(tmp_path.iterdir()) == []


# --- tier history -----------------------------------------------------------


def test_history_round_trips(tmp_path):
    path = tmp_path / "coefficients.json"
    bundle = dataclasses.replace(
        _bundle(), history=[TierChange("2026-09-19", "p1", "E", "S", "why")]
    )
    save(bundle, str(path))
    assert load(str(path)).history == bundle.history


def test_a_first_tiering_round_trips_with_a_null_previous(tmp_path):
    path = tmp_path / "coefficients.json"
    bundle = dataclasses.replace(
        _bundle(), history=[TierChange("2026-09-19", "p1", None, "B", "")]
    )
    save(bundle, str(path))
    assert load(str(path)).history[0].previous is None


def test_a_bundle_without_history_loads_as_empty(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), str(path))
    payload = json.loads(path.read_text())
    del payload["history"]
    path.write_text(json.dumps(payload))
    assert load(str(path)).history == []


def test_a_fresh_bundle_has_no_history():
    assert _bundle().history == []


def test_the_index_carries_the_history():
    bundle = dataclasses.replace(
        _bundle(), overrides={"p1": "S"},
        history=[TierChange("2026-09-19", "p1", "E", "S", "")],
    )
    assert bundle.index().resolve("p1", "x", on_date="2026-01-01").tier == "E"


def test_an_index_from_a_bundle_without_history_is_unaffected():
    bundle = dataclasses.replace(_bundle(), overrides={"p1": "S"})
    assert bundle.index().resolve("p1", "x", on_date="2026-01-01").tier == "S"
