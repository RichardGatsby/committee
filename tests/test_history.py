import pytest

from gibhub.history import TierChange, TierHistory, parse_changes

SAMPLE = """\
# date\tplayer\tfrom\tto\tnote
2026-09-19\tjussi8030\tE\tS\t+22.58 over 336 games
2026-10-01\ttreyzz\t-\tB\tfirst tiering
"""


def test_parses_one_change_per_line():
    changes = parse_changes(SAMPLE)
    assert changes == [
        TierChange("2026-09-19", "jussi8030", "E", "S", "+22.58 over 336 games"),
        TierChange("2026-10-01", "treyzz", None, "B", "first tiering"),
    ]


def test_a_dash_means_previously_untiered():
    assert parse_changes(SAMPLE)[1].previous is None


def test_comments_and_blank_lines_are_skipped():
    assert parse_changes("# note\n\n\n") == []


def test_an_empty_file_is_an_empty_log():
    assert parse_changes("") == []


def test_a_missing_column_is_rejected():
    with pytest.raises(ValueError, match="line 1"):
        parse_changes("2026-09-19\tjussi8030\tE\n")


def test_an_unparseable_date_is_rejected():
    with pytest.raises(ValueError, match="19-09-2026"):
        parse_changes("19-09-2026\tjussi8030\tE\tS\tx\n")


def test_an_unknown_tier_is_rejected():
    with pytest.raises(ValueError, match="'Z'"):
        parse_changes("2026-09-19\tjussi8030\tE\tZ\tx\n")


def test_the_note_may_be_empty():
    assert parse_changes("2026-09-19\tp\tE\tS\t\n")[0].note == ""


def test_the_note_is_optional_entirely():
    assert parse_changes("2026-09-19\tp\tE\tS\n")[0].note == ""


def test_a_note_containing_tabs_keeps_everything_after_the_fourth_column():
    change = parse_changes("2026-09-19\tp\tE\tS\twhy\tand more\n")[0]
    assert change.note == "why\tand more"


def test_changes_come_back_sorted_by_date():
    text = "2026-10-01\tp\tA\tS\tb\n2026-09-19\tp\tE\tA\ta\n"
    assert [c.date for c in parse_changes(text)] == ["2026-09-19", "2026-10-01"]


def test_two_changes_on_one_date_keep_the_order_they_were_written():
    text = "2026-09-19\tp\tE\tA\tfirst\n2026-09-19\tp\tA\tS\tsecond\n"
    assert [c.note for c in parse_changes(text)] == ["first", "second"]


# --- lookup ----------------------------------------------------------------

def _history():
    return TierHistory.build([
        TierChange("2026-03-01", "p1", "B", "A", ""),
        TierChange("2026-09-19", "p1", "A", "S", ""),
        TierChange("2026-05-01", "p2", None, "C", ""),
    ])


def test_a_player_with_no_changes_keeps_their_current_tier():
    assert _history().tier_at("stranger", "2026-06-01", current="B") == "B"


def test_before_every_change_gives_the_earliest_previous_tier():
    assert _history().tier_at("p1", "2026-01-01", current="S") == "B"


def test_between_two_changes_gives_the_middle_tier():
    assert _history().tier_at("p1", "2026-06-01", current="S") == "A"


def test_the_day_before_a_change_still_has_the_old_tier():
    assert _history().tier_at("p1", "2026-09-18", current="S") == "A"


def test_on_the_day_of_a_change_the_new_tier_applies():
    assert _history().tier_at("p1", "2026-09-19", current="S") == "S"


def test_after_the_last_change_gives_the_current_tier():
    assert _history().tier_at("p1", "2026-12-01", current="S") == "S"


def test_before_a_first_tiering_there_is_no_tier():
    assert _history().tier_at("p2", "2026-01-01", current="C") is None


def test_no_date_means_the_current_tier():
    assert _history().tier_at("p1", None, current="S") == "S"


def test_eras_lists_each_span_the_player_held():
    assert _history().eras("p1", current="S") == [
        (None, "2026-03-01", "B"),
        ("2026-03-01", "2026-09-19", "A"),
        ("2026-09-19", None, "S"),
    ]


def test_eras_of_an_unchanged_player_is_one_open_span():
    assert _history().eras("stranger", current="B") == [(None, None, "B")]


def test_eras_can_start_untiered():
    assert _history().eras("p2", current="C") == [
        (None, "2026-05-01", None),
        ("2026-05-01", None, "C"),
    ]


def test_an_empty_history_never_changes_an_answer():
    empty = TierHistory.build([])
    assert empty.tier_at("p1", "2020-01-01", current="S") == "S"
    assert empty.eras("p1", current="S") == [(None, None, "S")]


def test_build_sorts_changes_it_is_handed_out_of_order():
    history = TierHistory.build([
        TierChange("2026-09-19", "p1", "A", "S", ""),
        TierChange("2026-03-01", "p1", "B", "A", ""),
    ])
    assert history.tier_at("p1", "2026-01-01", current="S") == "B"


def test_players_lists_everyone_with_a_recorded_change():
    assert sorted(_history().players()) == ["p1", "p2"]


def test_changes_in_returns_the_dates_inside_a_window():
    assert _history().changes_in("p1", "2026-04-01", "2026-12-01") == ["2026-09-19"]


def test_changes_in_excludes_dates_outside_the_window():
    assert _history().changes_in("p1", "2026-10-01", "2026-12-01") == []
