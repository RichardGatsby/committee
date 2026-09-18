import json

from gibhub.dataset import match_to_sample, roster_ids
from gibhub.tiers import Holding, TierIndex

BANDS = {"S": 1.30, "A": 1.15, "B": 1.00, "C": 0.90, "D": 0.80, "E": 0.70}


def _index(holdings=None, utro=None):
    return TierIndex(holdings=holdings or {}, bands=BANDS, utro=utro or {})


def _match(**overrides):
    match = {
        "match_id": "m1",
        "channel_id": "poland",
        "winner": "alpha",
        "state": "finished",
        "teams": {
            "alpha": [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}],
            "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
        },
    }
    match.update(overrides)
    return match


def test_roster_ids_reads_both_sides():
    assert roster_ids(_match()) == (["a1", "a2", "a3"], ["b1", "b2", "b3"])


def test_roster_ids_tolerates_a_null_side():
    assert roster_ids(_match(teams={"alpha": None, "beta": None})) == ([], [])


def test_an_alpha_win_is_outcome_one():
    sample = match_to_sample(_match(), _index())
    assert sample.outcome == 1
    assert sample.match_id == "m1"


def test_a_beta_win_is_outcome_zero():
    assert match_to_sample(_match(winner="beta"), _index()).outcome == 0


def test_a_draw_is_skipped():
    assert match_to_sample(_match(winner=""), _index()) is None


def test_a_missing_winner_is_skipped():
    assert match_to_sample(_match(winner=None), _index()) is None


def test_an_incomplete_roster_is_skipped():
    match = _match()
    match["teams"]["alpha"] = [{"player_id": "a1"}, {"player_id": "a2"}]
    assert match_to_sample(match, _index()) is None


def test_features_reflect_the_resolved_tiers():
    holdings = {
        "a1": (Holding("poland", "S", "2026-01-01"),),
        "b1": (Holding("poland", "E", "2026-01-01"),),
    }
    # a2, a3, b2, b3 are untiered with no UTRO, so all impute to the median band (C).
    sample = match_to_sample(_match(), _index(holdings=holdings))
    assert sample.features == [1.0, 0.0, 0.0, 0.0, 0.0, -1.0]


def test_sources_are_recorded_for_all_six_players():
    holdings = {"a1": (Holding("poland", "S", "2026-01-01"),)}
    sample = match_to_sample(_match(), _index(holdings=holdings))
    assert sample.sources == ["exact"] + ["imputed"] * 5


def test_it_handles_the_recorded_fixture():
    match = json.load(open("tests/fixtures/match_detail.json"))
    sample = match_to_sample(match, _index())
    assert sample is not None
    assert sample.outcome in (0, 1)
    assert len(sample.features) == 6


def test_roster_ids_falls_back_to_the_rounds_when_there_is_no_teams_block():
    # GET /api/matches/{id} carries no `teams` field; only the match list does.
    match = {
        "rounds": [
            {"alpha": [{"player_id": "a1", "playtime_percent": 100}],
             "beta": [{"player_id": "b1", "playtime_percent": 100}]},
            {"alpha": [{"player_id": "a2", "playtime_percent": 100},
                       {"player_id": "a3", "playtime_percent": 100}],
             "beta": [{"player_id": "b2", "playtime_percent": 100},
                      {"player_id": "b3", "playtime_percent": 100}]},
        ]
    }
    assert roster_ids(match) == (["a1", "a2", "a3"], ["b1", "b2", "b3"])


def test_a_substitute_is_dropped_in_favour_of_the_three_who_played_most():
    match = {
        "rounds": [
            {"alpha": [{"player_id": "a1", "playtime_percent": 100},
                       {"player_id": "a2", "playtime_percent": 100},
                       {"player_id": "a3", "playtime_percent": 100},
                       {"player_id": "sub", "playtime_percent": 5}],
             "beta": []},
        ]
    }
    assert roster_ids(match)[0] == ["a1", "a2", "a3"]


def test_the_teams_block_wins_when_both_are_present():
    match = {
        "teams": {"alpha": [{"player_id": "listed"}], "beta": []},
        "rounds": [{"alpha": [{"player_id": "derived", "playtime_percent": 100}], "beta": []}],
    }
    assert roster_ids(match) == (["listed"], [])
