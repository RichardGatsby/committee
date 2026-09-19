from gibhub.history import TierChange
from tools.check_tier_history import Problem, check


def _change(date, player, previous, tier):
    return TierChange(date, player, previous, tier, "")


def test_a_clean_log_has_no_problems():
    assert check({"p1": "S"}, [_change("2026-09-19", "p1", "E", "S")]) == []


def test_an_empty_log_against_a_full_tier_list_is_fine():
    """Most players will never appear in the log. That is not a problem."""
    assert check({"p1": "S", "p2": "A", "p3": "B"}, []) == []


def test_a_logged_destination_must_match_the_current_list():
    problems = check({"p1": "A"}, [_change("2026-09-19", "p1", "E", "S")])
    assert len(problems) == 1
    assert problems[0].player == "p1"
    assert "list says A" in problems[0].detail
    assert "log ends at S" in problems[0].detail


def test_a_logged_player_missing_from_the_list_is_reported():
    problems = check({}, [_change("2026-09-19", "p1", "E", "S")])
    assert "not on the tier list" in problems[0].detail


def test_dates_must_not_go_backwards_for_one_player():
    problems = check(
        {"p1": "S"},
        [_change("2026-10-01", "p1", "E", "A"), _change("2026-09-19", "p1", "A", "S")])
    assert any("out of order" in p.detail for p in problems)


def test_two_entries_on_one_date_for_one_player_are_rejected():
    problems = check(
        {"p1": "S"},
        [_change("2026-09-19", "p1", "E", "A"), _change("2026-09-19", "p1", "A", "S")])
    assert any("same date" in p.detail for p in problems)


def test_a_chain_must_join_up():
    problems = check(
        {"p1": "S"},
        [_change("2026-09-19", "p1", "E", "A"), _change("2026-10-01", "p1", "B", "S")])
    assert any("leaves A but the next starts from B" in p.detail for p in problems)


def test_a_joined_up_chain_passes():
    assert check(
        {"p1": "S"},
        [_change("2026-09-19", "p1", "E", "A"),
         _change("2026-10-01", "p1", "A", "S")]) == []


def test_a_first_tiering_may_start_from_nothing():
    assert check({"p1": "B"}, [_change("2026-09-19", "p1", None, "B")]) == []


def test_a_removal_may_end_at_nothing():
    assert check({}, [_change("2026-09-19", "p1", "B", None)]) == []


def test_a_removal_that_is_still_listed_is_reported():
    problems = check({"p1": "B"}, [_change("2026-09-19", "p1", "B", None)])
    assert "log ends at untiered" in problems[0].detail


def test_players_are_reported_in_a_stable_order():
    problems = check(
        {"b": "A", "a": "A"},
        [_change("2026-09-19", "b", "E", "S"), _change("2026-09-19", "a", "E", "S")])
    assert [p.player for p in problems] == ["a", "b"]


def test_the_committed_log_and_overrides_agree():
    """Guard: the shipped files must stay consistent with each other."""
    import os

    from gibhub.history import parse_changes

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log = os.path.join(root, "data", "tier-changes.tsv")
    with open(log, "r", encoding="utf-8") as handle:
        changes = parse_changes(handle.read())
    # Names, not UUIDs, in the source log; check only what does not need
    # resolving, which with an empty log is everything.
    assert check({}, changes) == []
