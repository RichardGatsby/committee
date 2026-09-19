import pytest

from gibhub.history import TierChange, parse_changes

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
