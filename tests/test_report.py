import json

import pytest

from gibhub.report import (MatchRow, build_report, classify, luck_probability,
                           side_of, weighted_utro)
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


def test_classify_reads_off_the_luck_probability_not_the_raw_gap():
    assert classify(2.6, 0.005) == "CLEARLY OVER"
    assert classify(2.6, 0.03) == "OVER"
    assert classify(2.6, 0.30) == "ON TIER"
    assert classify(-6.0, 0.005) == "CLEARLY UNDER"
    assert classify(-6.0, 0.03) == "UNDER"
    assert classify(-6.0, 0.30) == "ON TIER"


def test_the_same_gap_means_different_things_at_different_sample_sizes():
    """+5 wins is real over 20 matches and noise over 400 — the old fixed
    +-1.5 win threshold could not tell those apart."""
    small = luck_probability([0.5] * 20, 15)
    large = luck_probability([0.5] * 400, 205)
    assert classify(5.0, small) == "OVER"
    assert classify(5.0, large) == "ON TIER"
    assert small < large


def test_luck_probability_of_exactly_average_is_near_a_half():
    assert luck_probability([0.5] * 100, 50) == pytest.approx(0.54, abs=0.02)


def test_luck_probability_falls_as_the_result_gets_more_extreme():
    ps = [0.5] * 100
    assert luck_probability(ps, 60) < luck_probability(ps, 55) < luck_probability(ps, 51)


def test_luck_probability_handles_a_certain_outcome():
    assert luck_probability([1.0, 1.0], 2) == pytest.approx(1.0)
    assert luck_probability([], 0) == 1.0


def test_luck_probability_is_two_directional():
    ps = [0.5] * 100
    # Equally unlikely either side of the mean.
    assert luck_probability(ps, 65) == pytest.approx(luck_probability(ps, 35), abs=1e-9)


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
    assert report.decided == 0


def test_an_unsettled_match_is_scored_from_its_scoreline_not_called_a_draw():
    detail = _detail("m1", "", 1.2)
    detail["state"] = "unknown match"
    detail["alpha_score"] = 0
    detail["beta_score"] = 10
    report = build_report(PROFILE, SPIDER, [detail], _index(), COEFFICIENTS, {})
    # The player is on alpha, so 0-10 is a loss, not a draw.
    assert report.rows[0].result == "L"
    assert report.draws == 0


def test_the_four_outcome_buckets_partition_the_decided_matches():
    """Every decided match is exactly one of: stack win, upset loss,
    upset win, underdog loss."""
    strong = _detail("m1", "alpha", 1.2)   # player on alpha with S vs E: favoured
    lost_favoured = _detail("m2", "beta", 1.2)

    underdog = _detail("m3", "beta", 1.2)
    underdog["teams"]["alpha"] = [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}]
    underdog["teams"]["beta"] = [{"player_id": "me"}, {"player_id": "b2"}, {"player_id": "b3"}]
    lost_underdog = dict(underdog, match_id="m4", winner="alpha")

    index = TierIndex(
        holdings={"me": (Holding("poland", "S", "2026-09-01"),),
                  "b1": (Holding("poland", "E", "2026-09-01"),),
                  "a1": (Holding("poland", "S", "2026-09-01"),)},
        bands=BANDS, utro={},
    )
    # m3/m4 put 'me' on beta as an E-tier underdog against a1's S.
    index2 = TierIndex(
        holdings={"a1": (Holding("poland", "S", "2026-09-01"),),
                  "me": (Holding("poland", "E", "2026-09-01"),)},
        bands=BANDS, utro={},
    )

    favoured = build_report(PROFILE, SPIDER, [strong, lost_favoured], index,
                            COEFFICIENTS, {})
    assert (favoured.stack_wins, favoured.upset_losses) == (1, 1)
    assert (favoured.upset_wins, favoured.underdog_losses) == (0, 0)

    dogs = build_report(PROFILE, SPIDER, [underdog, lost_underdog], index2,
                        COEFFICIENTS, {})
    assert (dogs.upset_wins, dogs.underdog_losses) == (1, 1)
    assert (dogs.stack_wins, dogs.upset_losses) == (0, 0)

    for report in (favoured, dogs):
        decided = sum(1 for row in report.rows if row.result in ("W", "L"))
        assert (report.stack_wins + report.upset_losses
                + report.upset_wins + report.underdog_losses) == decided


def test_an_exactly_even_match_is_neither_stack_nor_underdog():
    detail = _detail("m1", "alpha", 1.2)
    # An empty tier index gives both sides the same imputed tier: exactly 50%.
    even_index = TierIndex(holdings={}, bands=BANDS, utro={})
    report = build_report(PROFILE, SPIDER, [detail], even_index, COEFFICIENTS, {})
    assert report.rows[0].expected == 0.5
    assert report.even_matches == 1
    assert (report.stack_wins, report.upset_wins) == (0, 0)
    assert report.actual_wins == 1


def test_points_are_reported_from_the_players_own_side():
    from gibhub.model import TIER_POINTS

    # 'me' is S (5) on alpha, b1 is E (4) on beta; the rest impute to the same
    # tier on both sides and cancel. So alpha leads by 1 point.
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.2)], _index(),
                          COEFFICIENTS, {}, tier_points=TIER_POINTS)
    assert report.rows[0].points == 1.0


def test_points_flip_sign_for_a_player_on_beta():
    from gibhub.model import TIER_POINTS

    detail = _detail("m1", "alpha", 1.2)
    detail["teams"]["alpha"] = [{"player_id": "b1"}, {"player_id": "a2"}, {"player_id": "a3"}]
    detail["teams"]["beta"] = [{"player_id": "me"}, {"player_id": "x2"}, {"player_id": "x3"}]
    report = build_report(PROFILE, SPIDER, [detail], _index(), COEFFICIENTS, {},
                          tier_points=TIER_POINTS)
    # 'me' (S, 5) is now on beta against b1 (E, 4): beta leads by 1.
    assert report.rows[0].points == 1.0


def test_points_are_absent_without_a_points_scale():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.2)], _index(),
                          COEFFICIENTS, {})
    assert report.rows[0].points is None


def test_a_level_match_reports_positive_zero_points_not_negative_zero():
    from gibhub.model import TIER_POINTS

    detail = _detail("m1", "alpha", 1.2)
    detail["teams"]["alpha"] = [{"player_id": "x1"}, {"player_id": "x2"}, {"player_id": "x3"}]
    detail["teams"]["beta"] = [{"player_id": "me"}, {"player_id": "y2"}, {"player_id": "y3"}]
    even = TierIndex(holdings={}, bands=BANDS, utro={})
    report = build_report(PROFILE, SPIDER, [detail], even, COEFFICIENTS, {},
                          tier_points=TIER_POINTS)
    assert report.rows[0].points == 0.0
    assert "%+g" % report.rows[0].points == "+0"


def test_a_report_carries_the_effect_size_per_hundred_games():
    details = [_detail("m%d" % i, "alpha", 1.2) for i in range(4)]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert report.decided == 4
    assert report.per_100 == pytest.approx(100.0 * report.delta / 4)
    assert 0.0 <= report.luck <= 1.0


def _categorised(match_id, winner, channel, tags, channel_id="1194582311182807142"):
    detail = _detail(match_id, winner, 1.2)
    detail["channel_name"] = channel
    detail["tags"] = tags
    detail["channel_id"] = channel_id
    return detail


def test_the_report_splits_results_by_type_of_game():
    details = [
        _categorised("m1", "alpha", "ET:Legacy Events: #3vs3", ["gather"]),
        _categorised("m2", "beta", "Poland ET:Legacy: #3v3", ["gather"]),
        _categorised("m3", "alpha", "unsorted", None, ""),
    ]
    # Poland is opt-in, so by default only legacy and cup are counted.
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert [c[0] for c in report.categories] == ["legacy", "cup"]

    with_poland = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {},
                               only=["legacy", "poland", "cup"])
    keys = [c[0] for c in with_poland.categories]
    # Team games sit under cups: both are played by fixed teams, not picked sides.
    assert keys == ["legacy", "poland", "cup"]
    assert all(c[1] == 1 for c in with_poland.categories)


def test_only_restricts_the_report_to_one_type():
    details = [
        _categorised("m1", "alpha", "ET:Legacy Events: #3vs3", ["gather"]),
        _categorised("m2", "beta", "Poland ET:Legacy: #3v3", ["gather"]),
    ]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {},
                          only=["poland"])
    assert len(report.rows) == 1
    assert report.rows[0].category == "poland"
    assert report.decided == 1


def test_a_filtered_out_match_is_not_counted_as_skipped():
    details = [_categorised("m1", "alpha", "Poland ET:Legacy: #3v3", ["gather"])]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {},
                          only=["legacy"])
    assert report.rows == []
    assert report.skipped == 0


def test_the_small_gather_channels_are_dropped_from_a_report_by_default():
    details = [
        _categorised("m1", "alpha", "ET:Legacy Events: #3vs3", ["gather"]),
        _categorised("m2", "alpha", "subAk: #3on3", ["gather"]),
    ]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert [r.category for r in report.rows] == ["legacy"]
    assert report.skipped == 0


def test_they_are_included_when_asked_for_by_name():
    details = [_categorised("m1", "alpha", "subAk: #3on3", ["gather"])]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {},
                          only=["other-gather"])
    assert [r.category for r in report.rows] == ["other-gather"]


def test_the_header_shows_only_tiers_from_the_channel_being_scored():
    profile = dict(PROFILE, tiers=[
        {"channel_id": "events", "channel_name": "Events", "tier": "E", "size": 6,
         "updated_at": "2026-09-01"},
        {"channel_id": "poland", "channel_name": "Poland", "tier": "B", "size": 6,
         "updated_at": "2026-09-01"},
    ])
    scoped = build_report(profile, SPIDER, [], _index(), COEFFICIENTS, {},
                          tier_channel_ids={"events"})
    assert [t["tier"] for t in scoped.tiers] == ["E"]

    unscoped = build_report(profile, SPIDER, [], _index(), COEFFICIENTS, {})
    assert [t["tier"] for t in unscoped.tiers] == ["E", "B"]


def test_tier_neighbours_come_off_the_points_scale_not_the_letters():
    from gibhub.report import stronger_and_weaker

    # Strength order is S > E > A > B > C > D.
    assert stronger_and_weaker("A") == ("E", "B")
    assert stronger_and_weaker("E") == ("S", "A")
    assert stronger_and_weaker("S") == (None, "E")
    assert stronger_and_weaker("D") == ("C", None)
    assert stronger_and_weaker(None) == (None, None)


def test_the_recommendation_says_which_way_to_move():
    from gibhub.report import recommend

    # OVER means winning more than the tier predicts, so the tier is too low.
    assert recommend("CLEARLY OVER", "A") == "MOVE UP: A → E"
    assert recommend("OVER", "A") == "CONSIDER MOVING UP: A → E"
    assert recommend("CLEARLY UNDER", "A") == "MOVE DOWN: A → B"
    assert recommend("UNDER", "A") == "CONSIDER MOVING DOWN: A → B"
    assert recommend("ON TIER", "A") == "KEEP at A"


def test_the_recommendation_handles_the_ends_of_the_ladder():
    from gibhub.report import recommend

    assert recommend("CLEARLY OVER", "S") == "MOVE UP from S (no tier above of it)"
    assert recommend("CLEARLY UNDER", "D") == "MOVE DOWN from D (no tier below of it)"


def test_the_recommendation_without_a_known_tier():
    from gibhub.report import recommend

    assert recommend("ON TIER", None) == "KEEP current tier"
    assert recommend("CLEARLY UNDER", None) == "MOVE DOWN"


def test_a_committee_override_is_the_tier_the_verdict_is_about():
    index = TierIndex(holdings={}, bands=BANDS, utro={}, overrides={"me": "A"})
    report = build_report(dict(PROFILE, tiers=[]), SPIDER, [], index, COEFFICIENTS, {})
    assert report.current_tier == "A"
    assert report.recommendation == "KEEP at A"
