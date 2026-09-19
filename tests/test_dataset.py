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


from gibhub.dataset import winner_of


def test_winner_of_reads_an_explicit_winner():
    assert winner_of({"winner": "alpha"}) == "alpha"
    assert winner_of({"winner": "beta"}) == "beta"


def test_winner_of_treats_an_explicit_draw_as_none():
    assert winner_of({"winner": "draw", "alpha_score": 3, "beta_score": 3}) is None


def test_winner_of_falls_back_to_the_scoreline_on_an_unsettled_match():
    """An 'unknown match' leaves `winner` empty even at 0-10; the score decides."""
    match = {"state": "unknown match", "winner": "", "alpha_score": 0, "beta_score": 10}
    assert winner_of(match) == "beta"
    assert winner_of({"winner": "", "alpha_score": 4, "beta_score": 2}) == "alpha"


def test_winner_of_is_a_draw_when_the_scores_are_level_or_absent():
    assert winner_of({"winner": "", "alpha_score": 3, "beta_score": 3}) is None
    assert winner_of({"winner": "", "alpha_score": None, "beta_score": None}) is None
    assert winner_of({"winner": ""}) is None


def test_an_unsettled_match_with_a_decisive_score_still_trains_the_model():
    match = _match(winner="", alpha_score=0, beta_score=10)
    assert match_to_sample(match, _index()).outcome == 0


def test_the_small_gather_channels_do_not_train_the_model():
    match = _match()
    match["tags"] = ["gather"]
    match["channel_name"] = "subAk: #3on3"
    assert match_to_sample(match, _index()) is None


def test_gathers_cups_and_team_games_all_train_the_model():
    for channel, tags in (("ET:Legacy Events: #3vs3", ["gather"]),
                          ("Poland ET:Legacy: #3v3", ["gather"]),
                          ("unsorted", None)):
        match = _match()
        match["channel_name"] = channel
        match["tags"] = tags
        assert match_to_sample(match, _index()) is not None, channel


# --- as-of training ---------------------------------------------------------

from gibhub.history import TierChange, TierHistory  # noqa: E402


def _historical_index():
    return TierIndex(
        holdings={}, bands=BANDS, utro={}, overrides={"a1": "S"},
        history=TierHistory.build([TierChange("2026-09-19", "a1", "D", "S", "")]),
    )


def test_a_training_sample_uses_the_tiers_of_its_own_date():
    index = _historical_index()
    old = _match(start_time="2026-05-01T20:00:00+02:00")
    new = _match(start_time="2026-09-20T20:00:00+02:00")
    assert match_to_sample(old, index).features != match_to_sample(new, index).features


def test_a_match_before_the_change_trains_on_the_old_tier():
    sample = match_to_sample(
        _match(start_time="2026-05-01T20:00:00+02:00"), _historical_index())
    # a1 was D then, so alpha gains nothing at S.
    assert sample.features[0] == 0.0


def test_a_match_after_the_change_trains_on_the_new_tier():
    sample = match_to_sample(
        _match(start_time="2026-09-20T20:00:00+02:00"), _historical_index())
    assert sample.features[0] == 1.0


def test_a_match_with_no_start_time_falls_back_to_current_tiers():
    match = _match()
    match.pop("start_time", None)
    assert match_to_sample(match, _historical_index()).features[0] == 1.0


def test_an_index_without_history_trains_exactly_as_before():
    index = TierIndex(holdings={}, bands=BANDS, utro={}, overrides={"a1": "S"})
    old = _match(start_time="2026-05-01T20:00:00+02:00")
    new = _match(start_time="2026-09-20T20:00:00+02:00")
    assert match_to_sample(old, index).features == match_to_sample(new, index).features


def test_a_sample_records_the_date_its_match_was_played():
    """build_bundle needs it to say how far back the training set reaches."""
    from gibhub.dataset import Sample

    assert "date" in Sample.__dataclass_fields__
