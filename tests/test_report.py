import json

import pytest

from gibhub.report import MatchRow, build_report, classify, side_of, weighted_utro
from gibhub.tiers import Holding, TierIndex

MATCH = {
    "match_id": "m1",
    "channel_id": "poland",
    "winner": "alpha",
    "teams": {
        "alpha": [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}],
        "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
    },
    "rounds": [
        {"alpha": [{"player_id": "a1", "utro": 1.0, "playtime_percent": 100}], "beta": []},
        {"alpha": [], "beta": [{"player_id": "a1", "utro": 0.5, "playtime_percent": 50}]},
    ],
}


def test_side_of_finds_the_player():
    assert side_of(MATCH, "a2") == "alpha"
    assert side_of(MATCH, "b3") == "beta"


def test_side_of_returns_none_for_a_stranger():
    assert side_of(MATCH, "zzz") is None


def test_weighted_utro_weights_by_playtime():
    # (1.0 * 100 + 0.5 * 50) / 150
    assert weighted_utro(MATCH, "a1") == pytest.approx(0.8333333333333334)


def test_weighted_utro_is_none_when_the_player_has_no_rounds():
    assert weighted_utro(MATCH, "b1") is None


def test_weighted_utro_ignores_rounds_with_no_utro():
    match = {"rounds": [
        {"alpha": [{"player_id": "a1", "utro": None, "playtime_percent": 100}], "beta": []},
        {"alpha": [{"player_id": "a1", "utro": 1.2, "playtime_percent": 80}], "beta": []},
    ]}
    assert weighted_utro(match, "a1") == pytest.approx(1.2)


def test_weighted_utro_ignores_zero_playtime():
    match = {"rounds": [
        {"alpha": [{"player_id": "a1", "utro": 9.9, "playtime_percent": 0}], "beta": []},
        {"alpha": [{"player_id": "a1", "utro": 1.0, "playtime_percent": 100}], "beta": []},
    ]}
    assert weighted_utro(match, "a1") == pytest.approx(1.0)


def test_weighted_utro_on_the_recorded_fixture():
    match = json.load(open("tests/fixtures/match_detail.json"))
    player_id = match["rounds"][0]["alpha"][0]["player_id"]
    value = weighted_utro(match, player_id)
    assert value is not None and 0.0 < value < 3.0


BANDS = {"S": 1.30, "A": 1.15, "B": 1.00, "C": 0.90, "D": 0.80, "E": 0.70}
COEFFICIENTS = [0.9, 0.6, 0.3, 0.0, -0.4, -0.8]


def test_classify_labels_the_delta():
    assert classify(2.6) == "OVER"
    assert classify(1.5) == "OVER"
    assert classify(0.4) == "ON TIER"
    assert classify(-1.5) == "UNDER"
    assert classify(-3.0) == "UNDER"


def _detail(match_id, winner, rounds_utro):
    return {
        "match_id": match_id,
        "channel_id": "poland",
        "winner": winner,
        "state": "finished",
        "start_time": "2026-09-01T20:00:00+02:00",
        "maps": [{"map": "supply"}, {"map": "adlernest"}],
        "teams": {
            "alpha": [{"player_id": "me"}, {"player_id": "a2"}, {"player_id": "a3"}],
            "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
        },
        "rounds": [
            {"alpha": [{"player_id": "me", "utro": rounds_utro, "playtime_percent": 100}],
             "beta": []}
        ],
    }


def _index():
    holdings = {
        "me": (Holding("poland", "S", "2026-09-01"),),
        "b1": (Holding("poland", "E", "2026-09-01"),),
    }
    return TierIndex(holdings=holdings, bands=BANDS, utro={})


PROFILE = {
    "player_id": "me",
    "nick": "^1Me",
    "discord_nick": "me",
    "tiers": [{"channel_id": "poland", "channel_name": "Poland", "tier": "S", "size": 6,
               "updated_at": "2026-09-01T00:00:00+02:00"}],
    "lifetime": {"matches": 100, "match_wins": 60, "match_losses": 38, "match_draws": 2,
                 "utro": 1.20, "kdr": 1.15},
}

SPIDER = {"metrics": [{"key": "utro", "value": 1.2, "avg": 1.0, "percentile": 87.5}]}


def test_a_favoured_win_is_not_an_upset():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.3)], _index(),
                          COEFFICIENTS, {})
    row = report.rows[0]
    assert row.result == "W"
    assert row.expected > 0.5
    assert row.upset is False


def test_a_win_against_the_odds_is_an_upset_win():
    detail = _detail("m2", "beta", 1.4)
    detail["teams"]["alpha"] = [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}]
    detail["teams"]["beta"] = [{"player_id": "me"}, {"player_id": "b2"}, {"player_id": "b3"}]
    index = TierIndex(
        holdings={"a1": (Holding("poland", "S", "2026-09-01"),),
                  "me": (Holding("poland", "E", "2026-09-01"),)},
        bands=BANDS, utro={},
    )
    report = build_report(PROFILE, SPIDER, [detail], index, COEFFICIENTS, {})
    row = report.rows[0]
    assert row.result == "W"
    assert row.expected < 0.5
    assert row.upset is True
    assert report.upset_wins == 1
    assert report.upset_losses == 0


def test_a_loss_while_favoured_is_an_upset_loss():
    report = build_report(PROFILE, SPIDER, [_detail("m3", "beta", 0.7)], _index(),
                          COEFFICIENTS, {})
    assert report.rows[0].result == "L"
    assert report.upset_losses == 1


def test_expected_wins_sum_the_per_match_probabilities():
    details = [_detail("m1", "alpha", 1.2), _detail("m2", "beta", 1.1)]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert report.actual_wins == 1
    assert report.expected_wins == pytest.approx(2 * report.rows[0].expected)
    assert report.delta == pytest.approx(report.actual_wins - report.expected_wins)


def test_draws_are_listed_but_excluded_from_the_totals():
    details = [_detail("m1", "alpha", 1.2), _detail("m2", "", 1.0)]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert [row.result for row in report.rows] == ["W", "D"]
    assert report.draws == 1
    assert report.actual_wins == 1
    assert report.expected_wins == pytest.approx(report.rows[0].expected)


def test_utro_delta_is_against_the_lifetime_baseline():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.5)], _index(),
                          COEFFICIENTS, {})
    assert report.rows[0].utro == pytest.approx(1.5)
    assert report.rows[0].utro_delta == pytest.approx(0.30)


def test_a_match_the_player_is_not_in_is_skipped():
    detail = _detail("m1", "alpha", 1.2)
    detail["teams"]["alpha"] = [{"player_id": "x"}, {"player_id": "y"}, {"player_id": "z"}]
    report = build_report(PROFILE, SPIDER, [detail], _index(), COEFFICIENTS, {})
    assert report.rows == []
    assert report.skipped == 1


def test_source_counts_are_totalled_across_matches():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.2)], _index(),
                          COEFFICIENTS, {})
    assert report.source_counts["exact"] == 2
    assert report.source_counts["imputed"] == 4
    assert report.source_counts["cross_channel"] == 0


def test_lifetime_and_percentiles_are_carried_through():
    report = build_report(PROFILE, SPIDER, [], _index(), COEFFICIENTS,
                          {"fitted_at": "2026-09-18T00:00:00+00:00"})
    assert report.nick == "^1Me"
    assert report.lifetime["win_rate"] == pytest.approx(60 / 98)
    assert report.percentiles == [("utro", 87.5)]
    assert report.provenance["fitted_at"] == "2026-09-18T00:00:00+00:00"
    assert report.label == "ON TIER"


def test_an_unsettled_match_is_scored_from_its_scoreline_not_called_a_draw():
    detail = _detail("m1", "", 1.2)
    detail["state"] = "unknown match"
    detail["alpha_score"] = 0
    detail["beta_score"] = 10
    report = build_report(PROFILE, SPIDER, [detail], _index(), COEFFICIENTS, {})
    # The player is on alpha, so 0-10 is a loss, not a draw.
    assert report.rows[0].result == "L"
    assert report.draws == 0
