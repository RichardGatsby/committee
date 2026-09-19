import pytest

from gibhub.scan import ODDS_CEILING, ScanRow, scan, tier_coverage
from gibhub.tiers import Holding, TierIndex

BANDS = {"S": 1.30, "E": 1.10, "A": 1.05, "B": 1.00, "C": 0.90, "D": 0.80}
COEFFICIENTS = [1.76, 1.06, 0.70, 0.35, 0.0, 1.41]  # S A B C D E, points-shaped
SCALE = 0.3525


def _index(overrides):
    return TierIndex(holdings={}, bands=BANDS, utro={}, overrides=overrides)


def _match(alpha, beta, winner, tags=("gather",), channel="ET:Legacy Events: #3vs3"):
    return {
        "match_id": "m", "winner": winner, "state": "finished",
        "tags": list(tags), "channel_name": channel, "channel_id": "c1",
        "teams": {"alpha": [{"player_id": p} for p in alpha],
                  "beta": [{"player_id": p} for p in beta]},
    }


def _row(rows, nick_or_id):
    return next(r for r in rows if r.player_id == nick_or_id)


def test_a_player_who_always_wins_reads_as_over():
    overrides = {p: "B" for p in ("x", "y", "z", "q", "r", "s")}
    matches = [_match(["x", "y", "z"], ["q", "r", "s"], "alpha") for _ in range(60)]
    rows = scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50)
    winner_row = _row(rows, "x")
    assert winner_row.actual == 60 and winner_row.games == 60
    assert winner_row.per_100 == pytest.approx(50.0)  # 100% vs an even 50%
    assert winner_row.label == "CLEARLY OVER"
    assert winner_row.recommendation.startswith("MOVE UP")
    loser_row = _row(rows, "q")
    assert loser_row.label == "CLEARLY UNDER"


def test_players_below_the_game_floor_are_left_out():
    overrides = {p: "B" for p in ("x", "y", "z", "q", "r", "s")}
    matches = [_match(["x", "y", "z"], ["q", "r", "s"], "alpha") for _ in range(10)]
    assert scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50) == []


def test_untiered_players_are_left_out():
    overrides = {"x": "B"}
    matches = [_match(["x", "y", "z"], ["q", "r", "s"], "alpha") for _ in range(60)]
    rows = scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50)
    assert [r.player_id for r in rows] == ["x"]


def test_rows_are_ranked_by_effect_size_not_by_odds():
    overrides = {p: "B" for p in "xyzqrs"}
    matches = ([_match(["x", "y", "z"], ["q", "r", "s"], "alpha")] * 60
               + [_match(["x", "y", "z"], ["q", "r", "s"], "beta")] * 60)
    rows = scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50)
    sizes = [abs(r.per_100) for r in rows]
    assert sizes == sorted(sizes, reverse=True)


def test_the_odds_are_capped_because_beyond_it_they_measure_broken_assumptions():
    row = ScanRow("p", "p", "B", 400, 180.0, 250, 17.5, 1.8, 3.4e-12,
                  "CLEARLY OVER", "MOVE UP: B → A", "mate", 0.1, 0.0)
    assert row.odds == ODDS_CEILING
    assert ScanRow("p", "p", "B", 400, 180.0, 190, 2.5, 0.3, 0.02,
                   "OVER", "x", "mate", 0.1, 0.0).odds == 50


def test_a_dominant_teammate_is_flagged_as_the_caution():
    row = ScanRow("p", "Baczo", "B", 427, 181.6, 249, 15.8, 1.8, 1e-11,
                  "CLEARLY OVER", "MOVE UP: B → A", "SkyLine", 0.29, 0.05)
    assert row.caution == "29% of games with SkyLine"


def test_heavy_imputation_is_flagged_when_no_teammate_dominates():
    row = ScanRow("p", "x", "B", 400, 180.0, 200, 5.0, 0.6, 0.01,
                  "OVER", "x", "mate", 0.10, 0.30)
    assert row.caution == "30% of tiers guessed"


def test_a_small_sample_is_flagged_when_the_effect_is_under_a_tier():
    row = ScanRow("p", "x", "B", 80, 40.0, 45, 6.25, 0.5, 0.2,
                  "ON TIER", "KEEP at B", "mate", 0.1, 0.0)
    assert row.caution == "only 80 games; too few for a 1-tier call"


def test_a_clean_large_sample_has_no_caution():
    row = ScanRow("p", "x", "B", 400, 180.0, 230, 12.5, 1.4, 1e-6,
                  "CLEARLY OVER", "x", "mate", 0.1, 0.05)
    assert row.caution == ""


def test_the_teammate_share_counts_only_shared_games():
    overrides = {p: "B" for p in "xyzqrs"}
    matches = ([_match(["x", "y", "z"], ["q", "r", "s"], "alpha")] * 40
               + [_match(["x", "q", "r"], ["y", "z", "s"], "alpha")] * 20)
    rows = scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50)
    row = _row(rows, "x")
    assert row.games == 60
    # y and z share 40 of x's 60 games; q and r share 20.
    assert row.top_mate_share == pytest.approx(40 / 60)


def test_the_small_gather_channels_are_excluded_like_everywhere_else():
    overrides = {p: "B" for p in "xyzqrs"}
    matches = [_match(["x", "y", "z"], ["q", "r", "s"], "alpha",
                      channel="subAk: #3on3") for _ in range(60)]
    assert scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50) == []


def test_nicks_are_used_when_supplied():
    overrides = {p: "B" for p in "xyzqrs"}
    matches = [_match(["x", "y", "z"], ["q", "r", "s"], "alpha") for _ in range(60)]
    rows = scan(matches, _index(overrides), COEFFICIENTS, SCALE, min_games=50,
                nicks={"x": "Baczo", "y": "SkyLine"})
    row = _row(rows, "x")
    assert row.nick == "Baczo"
    assert row.top_mate == "SkyLine"


# --- population tier coverage ----------------------------------------------
#
# Reported separately from the rows: a scan can look clean simply because the
# players it could not tier were dropped before any verdict was formed.

SIX = ("x", "y", "z", "q", "r", "s")


def _sixty():
    return [_match(["x", "y", "z"], ["q", "r", "s"], "alpha") for _ in range(60)]


def test_coverage_of_a_fully_tiered_population_is_clean():
    overrides = {p: "B" for p in SIX}
    found = tier_coverage(_sixty(), _index(overrides))

    assert found.players_seen == 6
    assert found.players_guessed == 0
    assert found.guessed_share == 0.0
    assert found.warning == ""


def test_coverage_counts_distinct_players_not_appearances():
    overrides = {p: "B" for p in SIX}
    found = tier_coverage(_sixty(), _index(overrides))

    assert found.players_seen == 6


def test_coverage_share_is_the_fraction_of_guessed_tier_inputs():
    overrides = {"x": "B", "y": "B", "z": "B"}
    found = tier_coverage(_sixty(), _index(overrides))

    assert found.players_guessed == 3
    assert found.guessed_share == pytest.approx(0.5)


def test_a_half_guessed_population_is_unreliable():
    overrides = {"x": "B", "y": "B", "z": "B"}
    assert tier_coverage(_sixty(), _index(overrides)).warning.startswith("UNRELIABLE")


def test_a_quarter_guessed_population_earns_a_caution():
    overrides = {p: "B" for p in ("x", "y", "z", "q")}
    found = tier_coverage(_sixty(), _index(overrides))

    assert found.guessed_share == pytest.approx(1 / 3.0)
    assert found.warning.startswith("CAUTION")


def test_coverage_ignores_matches_outside_the_counted_categories():
    overrides = {p: "B" for p in SIX}
    poland = [_match(["x", "y", "z"], ["q", "r", "s"], "alpha",
                     channel="Poland ET:Legacy: #3v3") for _ in range(60)]
    assert tier_coverage(poland, _index(overrides)).players_seen == 0


def test_coverage_of_no_matches_is_empty_rather_than_a_division_by_zero():
    found = tier_coverage([], _index({}))

    assert found.players_seen == 0
    assert found.guessed_share == 0.0
    assert found.warning == ""
