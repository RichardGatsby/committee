import pytest

from tools.resolve_tierlist import UnresolvedChange, resolve_change_players

NAMES = {"hevimies": "uuid-hevi", "treyzz": "uuid-trey"}
UUID = "76903d56-f455-5be9-8c7f-b8d4c11c5b97"


def _change(player):
    return ("2026-09-19", player, "E", "S", "why")


def test_a_name_on_the_tier_list_resolves_to_its_account():
    assert resolve_change_players([_change("hevimies")], NAMES) == [
        ("2026-09-19", "uuid-hevi", "E", "S", "why")
    ]


def test_a_uuid_is_taken_as_is():
    assert resolve_change_players([_change(UUID)], NAMES)[0][1] == UUID


def test_a_name_is_matched_case_insensitively():
    assert resolve_change_players([_change("HEViMIES")], NAMES)[0][1] == "uuid-hevi"


def test_an_unknown_name_raises_rather_than_being_dropped():
    """A silently dropped decision is worse than no log at all."""
    with pytest.raises(UnresolvedChange, match="ghost"):
        resolve_change_players([_change("ghost")], NAMES)


def test_the_error_names_the_date_so_the_line_can_be_found():
    with pytest.raises(UnresolvedChange, match="2026-09-19"):
        resolve_change_players([_change("ghost")], NAMES)


def test_an_empty_log_resolves_to_nothing():
    assert resolve_change_players([], NAMES) == []


def test_order_is_preserved():
    changes = [_change("hevimies"), _change("treyzz")]
    assert [c[1] for c in resolve_change_players(changes, NAMES)] == [
        "uuid-hevi", "uuid-trey"
    ]
