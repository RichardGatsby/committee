"""Scan behaviour once the committee has changed somebody's tier."""

import csv
import io

import pytest

from gibhub.history import TierChange, TierHistory
from gibhub.render import to_scan_csv
from gibhub.scan import scan
from gibhub.tiers import TierIndex

BANDS = {"S": 1.30, "E": 1.10, "A": 1.05, "B": 1.00, "C": 0.90, "D": 0.80}
COEFFICIENTS = [1.76, 1.06, 0.70, 0.35, 0.0, 1.41]  # S A B C D E, points-shaped
SCALE = 0.3525
SIX = ("x", "y", "z", "q", "r", "s")

ALL_B = {p: "B" for p in SIX}
PROMOTED = dict(ALL_B, x="S")
CHANGE = [TierChange("2026-06-01", "x", "B", "S", "")]


def _index(overrides, changes=()):
    return TierIndex(holdings={}, bands=BANDS, utro={}, overrides=overrides,
                     history=TierHistory.build(list(changes)))


def _on(date, winner="alpha"):
    return {
        "match_id": "m", "winner": winner, "state": "finished",
        "tags": ["gather"], "channel_name": "ET:Legacy Events: #3vs3",
        "channel_id": "c1", "start_time": date + "T20:00:00+02:00",
        "teams": {"alpha": [{"player_id": p} for p in ("x", "y", "z")],
                  "beta": [{"player_id": p} for p in ("q", "r", "s")]},
    }


def _days(month, count, winner="alpha"):
    return [_on("2026-%02d-%02d" % (month, i % 28 + 1), winner) for i in range(count)]


def _row(rows, player_id):
    return next(r for r in rows if r.player_id == player_id)


def test_a_scan_row_scores_each_match_at_its_own_date():
    index = _index(PROMOTED, CHANGE)
    early = _row(scan(_days(1, 60), index, COEFFICIENTS, SCALE, min_games=50), "x")
    late = _row(scan(_days(10, 60), index, COEFFICIENTS, SCALE, min_games=50), "x")
    assert early.expected != late.expected


def test_matches_before_a_promotion_use_the_old_tier():
    """At B among Bs the sides are level, so the expectation is exactly half."""
    index = _index(PROMOTED, CHANGE)
    row = _row(scan(_days(1, 60), index, COEFFICIENTS, SCALE, min_games=50), "x")
    assert row.expected == pytest.approx(30.0)


def test_matches_after_a_promotion_use_the_new_tier():
    index = _index(PROMOTED, CHANGE)
    row = _row(scan(_days(10, 60), index, COEFFICIENTS, SCALE, min_games=50), "x")
    assert row.expected > 30.0


def test_a_player_whose_tier_changed_in_window_is_flagged():
    index = _index(PROMOTED, CHANGE)
    matches = _days(5, 30) + _days(7, 30)
    caution = _row(scan(matches, index, COEFFICIENTS, SCALE, min_games=50), "x").caution
    assert "tier changed 2026-06-01" in caution
    assert "30 games at S" in caution


def test_the_change_caution_outranks_the_dominant_mate_one():
    """A tier change is the more important reason to distrust the row."""
    index = _index(PROMOTED, CHANGE)
    matches = _days(5, 30) + _days(7, 30)
    row = _row(scan(matches, index, COEFFICIENTS, SCALE, min_games=50), "x")
    assert row.caution.startswith("tier changed")


def test_an_unchanged_player_carries_no_change_caution():
    index = _index(PROMOTED, CHANGE)
    rows = scan(_days(5, 30) + _days(7, 30), index, COEFFICIENTS, SCALE, min_games=50)
    assert "tier changed" not in _row(rows, "y").caution


def test_a_change_before_the_window_is_not_flagged():
    index = _index(PROMOTED, CHANGE)
    rows = scan(_days(7, 60), index, COEFFICIENTS, SCALE, min_games=50)
    assert "tier changed" not in _row(rows, "x").caution


def test_the_verdict_uses_only_games_at_the_current_tier():
    """30 losses at B then 30 wins at S must not be judged as one record."""
    index = _index(PROMOTED, CHANGE)
    matches = _days(5, 30, "beta") + _days(7, 30, "alpha")
    row = _row(scan(matches, index, COEFFICIENTS, SCALE, min_games=50), "x")
    assert row.games == 60
    assert row.games_at_tier == 30
    assert row.actual == 30


def test_games_at_tier_equals_games_when_nothing_changed():
    rows = scan(_days(7, 60), _index(ALL_B), COEFFICIENTS, SCALE, min_games=50)
    assert _row(rows, "y").games_at_tier == _row(rows, "y").games


def test_an_unchanged_population_scores_exactly_as_before():
    matches = _days(7, 60)
    plain = scan(matches, _index(ALL_B), COEFFICIENTS, SCALE, min_games=50)
    empty_log = scan(matches, _index(ALL_B, []), COEFFICIENTS, SCALE, min_games=50)
    assert plain == empty_log


# --- csv --------------------------------------------------------------------


def _split_rows():
    return scan(_days(5, 30) + _days(7, 30), _index(PROMOTED, CHANGE),
                COEFFICIENTS, SCALE, min_games=50)


def _parsed(rows):
    return {r["player_id"]: r for r in csv.DictReader(io.StringIO(to_scan_csv(rows)))}


def test_the_scan_csv_carries_the_change_columns():
    header = to_scan_csv(_split_rows()).splitlines()[0]
    assert "changed_on" in header
    assert "games_at_tier" in header


def test_the_scan_csv_reports_the_split_sample():
    row = _parsed(_split_rows())["x"]
    assert row["changed_on"] == "2026-06-01"
    assert row["games_at_tier"] == "30"


def test_an_unchanged_player_has_an_empty_change_date_in_csv():
    assert _parsed(_split_rows())["y"]["changed_on"] == ""
