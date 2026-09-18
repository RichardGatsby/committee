import pytest

from gibhub.categories import (CUP, GATHERS, LEGACY, OTHER_GATHER, POLAND, allowed,
                               categorise, parse_selection)


def _match(tags=None, channel="", channel_id="1194582311182807142"):
    return {"tags": tags, "channel_name": channel, "channel_id": channel_id}


def test_a_legacy_events_gather():
    assert categorise(_match(["gather"], "ET:Legacy Events: #3vs3")) == LEGACY
    assert categorise(_match(["gather"], "ET:Legacy Gathers: #3vs3")) == LEGACY


def test_a_poland_gather():
    assert categorise(_match(["gather"], "Poland ET:Legacy: #3v3")) == POLAND


def test_the_small_gather_channels_are_their_own_category():
    assert categorise(_match(["gather"], "subAk: #3on3")) == OTHER_GATHER
    assert categorise(_match(["gather"], "eV!L Gather: #3v3")) == OTHER_GATHER
    assert categorise(_match(["gather"], "Frag Center: #3v3")) == OTHER_GATHER


def test_a_tagged_cup():
    assert categorise(_match(["cup"], "ET:Legacy Events: Draft Cup #7")) == CUP


def test_a_league_season_is_a_cup():
    assert categorise(_match(["et:l season 13"], "whatever")) == CUP


def test_an_untagged_tournament_is_a_cup():
    assert categorise(_match(None, "Nations Cup 3on3 - 2026", "0000000000000000018")) == CUP
    assert categorise(_match([], "subak: 3on3 CUP #2", "0000000000000000017")) == CUP


def test_team_games_between_named_teams_count_as_cups():
    """Scrims are played by fixed teams, like cups, not by picked sides."""
    assert categorise(_match(None, "unsorted", "")) == CUP
    assert categorise(_match([], "ETLAC: #3vs3", "1479851190152855562")) == CUP


def test_the_gather_tag_wins_over_a_tournament_id():
    assert categorise(_match(["gather"], "Poland ET:Legacy: #3v3", "0000000001")) == POLAND


def test_gathers_means_legacy_and_poland_only():
    assert GATHERS == (LEGACY, POLAND)
    assert parse_selection(["gathers"]) == [LEGACY, POLAND]


def test_team_and_cup_select_the_same_category():
    assert parse_selection(["team"]) == [CUP]
    assert parse_selection(["internal"]) == [CUP]
    assert parse_selection(["tournament"]) == [CUP]


def test_parse_selection_accepts_friendly_spellings():
    assert parse_selection(["legacy"]) == [LEGACY]
    assert parse_selection(["pl"]) == [POLAND]


def test_parse_selection_dedupes_and_keeps_order():
    assert parse_selection(["poland", "legacy", "poland"]) == [POLAND, LEGACY]


def test_parse_selection_rejects_nonsense():
    with pytest.raises(ValueError, match="unknown category 'banana'"):
        parse_selection(["banana"])


def test_a_report_leaves_out_poland_and_the_small_channels_by_default():
    """Poland is over half the volume; counted by default it dominates every
    verdict, so it is opt-in via --with-poland."""
    from gibhub.categories import REPORT_DEFAULT, TRAINING_DEFAULT

    assert allowed(None) == (LEGACY, CUP)
    assert allowed([]) == REPORT_DEFAULT
    assert POLAND not in allowed(None)
    assert OTHER_GATHER not in allowed(None)


def test_the_model_still_trains_on_poland():
    """Dropping two thirds of the sample would weaken the fit for no gain."""
    from gibhub.categories import TRAINING_DEFAULT

    assert allowed(None, TRAINING_DEFAULT) == (LEGACY, POLAND, CUP)
    assert OTHER_GATHER not in TRAINING_DEFAULT


def test_an_explicit_selection_overrides_the_default_either_way():
    from gibhub.categories import TRAINING_DEFAULT

    assert allowed([POLAND]) == (POLAND,)
    assert allowed([POLAND], TRAINING_DEFAULT) == (POLAND,)


def test_they_can_still_be_asked_for_by_name():
    assert allowed(parse_selection(["other"])) == (OTHER_GATHER,)
    assert OTHER_GATHER in allowed(parse_selection(["all"]))
