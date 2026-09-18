import pytest

from gibhub.categories import (CUP, LEGACY, OTHER_GATHER, POLAND, TEAM, categorise,
                               parse_selection)


def _match(tags=None, channel="", channel_id="1194582311182807142"):
    return {"tags": tags, "channel_name": channel, "channel_id": channel_id}


def test_a_legacy_events_gather():
    assert categorise(_match(["gather"], "ET:Legacy Events: #3vs3")) == LEGACY
    assert categorise(_match(["gather"], "ET:Legacy Gathers: #3vs3")) == LEGACY


def test_a_poland_gather():
    assert categorise(_match(["gather"], "Poland ET:Legacy: #3v3")) == POLAND


def test_any_other_gather():
    assert categorise(_match(["gather"], "subAk: #3on3")) == OTHER_GATHER
    assert categorise(_match(["gather"], "eV!L Gather: #3v3")) == OTHER_GATHER


def test_a_tagged_cup():
    assert categorise(_match(["cup"], "ET:Legacy Events: Draft Cup #7")) == CUP


def test_a_league_season_is_a_cup():
    assert categorise(_match(["et:l season 13"], "whatever")) == CUP


def test_an_untagged_tournament_is_caught_by_its_synthetic_channel_id():
    """Nations Cup and subak's cups carry no cup tag."""
    assert categorise(_match(None, "Nations Cup 3on3 - 2026", "0000000000000000018")) == CUP
    assert categorise(_match([], "subak: 3on3 CUP #2", "0000000000000000017")) == CUP


def test_an_untagged_match_in_a_real_channel_is_a_team_game():
    assert categorise(_match(None, "unsorted", "")) == TEAM
    assert categorise(_match([], "ETLAC: #3vs3", "1479851190152855562")) == TEAM


def test_the_gather_tag_wins_over_a_tournament_id():
    assert categorise(_match(["gather"], "Poland ET:Legacy: #3v3", "0000000001")) == POLAND


def test_parse_selection_accepts_friendly_spellings():
    assert parse_selection(["legacy"]) == [LEGACY]
    assert parse_selection(["pl"]) == [POLAND]
    assert parse_selection(["internal"]) == [TEAM]
    assert parse_selection(["tournament"]) == [CUP]


def test_parse_selection_expands_gathers_to_all_three():
    assert parse_selection(["gathers"]) == [LEGACY, POLAND, OTHER_GATHER]


def test_parse_selection_dedupes_and_keeps_order():
    assert parse_selection(["poland", "legacy", "poland"]) == [POLAND, LEGACY]


def test_parse_selection_rejects_nonsense():
    with pytest.raises(ValueError, match="unknown category 'banana'"):
        parse_selection(["banana"])


def test_no_selection_means_everything():
    assert parse_selection(None) == []
    assert parse_selection([]) == []
