import pytest

from gibhub.history import TierChange, TierHistory
from gibhub.tiers import (EXACT, IMPUTED, OVERRIDE, Holding, ResolvedTier,
                          TierIndex, build_bands, nearest_tier)

BANDS = {"S": 1.30, "A": 1.15, "B": 1.00, "C": 0.90, "D": 0.80, "E": 0.70}


def test_nearest_tier_picks_the_closest_band():
    assert nearest_tier(BANDS, 1.29) == "S"
    assert nearest_tier(BANDS, 1.01) == "B"
    assert nearest_tier(BANDS, 0.10) == "E"
    assert nearest_tier(BANDS, 9.00) == "S"


def test_nearest_tier_breaks_ties_towards_the_stronger_tier():
    # 1.075 is equidistant from A (1.15) and B (1.00) at 0.075.
    assert nearest_tier(BANDS, 1.075) == "A"


def test_nearest_tier_without_a_utro_falls_back_to_the_median_band():
    # The six band values have a median of (1.00 + 0.90) / 2 = 0.95, nearest to C.
    assert nearest_tier(BANDS, None) == "C"


def test_nearest_tier_rejects_empty_bands():
    with pytest.raises(ValueError, match="no tier bands"):
        nearest_tier({}, 1.0)


def test_build_bands_takes_the_median_utro_per_tier():
    holders = {"S": ["p1", "p2", "p3"], "A": ["p4", "p5"]}
    utro = {"p1": 1.4, "p2": 1.3, "p3": 1.2, "p4": 1.1, "p5": 1.0}
    assert build_bands(holders, utro) == {"S": 1.3, "A": pytest.approx(1.05)}


def test_build_bands_ignores_holders_with_no_utro():
    assert build_bands({"S": ["p1", "ghost"]}, {"p1": 1.4}) == {"S": 1.4}


def test_build_bands_drops_a_tier_with_no_usable_holders():
    assert build_bands({"S": ["ghost"], "A": ["p1"]}, {"p1": 1.1}) == {"A": 1.1}


HOLDINGS = {
    "multi": (
        Holding(channel_id="poland", tier="B", updated_at="2026-01-01T00:00:00+01:00"),
        Holding(channel_id="events", tier="A", updated_at="2026-09-01T00:00:00+02:00"),
    ),
    "single": (Holding(channel_id="poland", tier="S", updated_at="2026-05-01T00:00:00+02:00"),),
}


def _index():
    return TierIndex(holdings=HOLDINGS, bands=BANDS, utro={"nobody": 0.79, "multi": 1.2})


def test_an_exact_channel_tier_wins():
    assert _index().resolve("multi", "poland") == ResolvedTier("B", "exact")
    assert _index().resolve("multi", "events") == ResolvedTier("A", "exact")


def test_another_channels_tier_is_used_when_the_match_channel_has_none():
    # The events holding is the most recently updated of the two.
    assert _index().resolve("multi", "somewhere-else") == ResolvedTier("A", "cross_channel")


def test_a_single_holding_is_used_across_channels():
    assert _index().resolve("single", "events") == ResolvedTier("S", "cross_channel")


def test_an_untiered_player_is_imputed_from_utro():
    assert _index().resolve("nobody", "poland") == ResolvedTier("D", "imputed")


def test_a_player_with_neither_tier_nor_utro_is_imputed_from_the_median_band():
    assert _index().resolve("ghost", "poland") == ResolvedTier("C", "imputed")


def test_resolve_all_returns_one_result_per_player_in_order():
    resolved = _index().resolve_all(["multi", "ghost"], "poland")
    assert resolved == [ResolvedTier("B", "exact"), ResolvedTier("C", "imputed")]


def test_tiers_of_returns_just_the_letters():
    assert _index().tiers_of(["multi", "ghost"], "poland") == ["B", "C"]


def test_nearest_tier_ties_break_on_band_strength_not_the_letter():
    """The letters are not an ordered ladder: E is the second-strongest tier here."""
    # 1.0 is exactly equidistant from E (1.5) and A (0.5); E has the higher band.
    assert nearest_tier({"E": 1.5, "A": 0.5}, 1.0) == "E"
    # The letter order would have picked A, since "A" sorts before "E".
    assert nearest_tier({"A": 1.5, "E": 0.5}, 1.0) == "A"


from gibhub.tiers import capped_bands

# Real-shaped bands: E outranks A, so a letter-based cap would not work.
REAL_BANDS = {"S": 1.250, "E": 1.099, "A": 1.042, "B": 0.976, "C": 0.752, "D": 0.603}


def test_capping_at_a_excludes_both_s_and_e():
    assert set(capped_bands(REAL_BANDS, "A")) == {"A", "B", "C", "D"}


def test_capping_at_b_excludes_a_as_well():
    assert set(capped_bands(REAL_BANDS, "B")) == {"B", "C", "D"}


def test_no_cap_keeps_every_band():
    assert capped_bands(REAL_BANDS, None) == REAL_BANDS
    assert capped_bands(REAL_BANDS, "S") == REAL_BANDS


def test_an_unknown_cap_tier_is_ignored_rather_than_emptying_the_bands():
    assert capped_bands({"A": 1.0, "B": 0.9}, "S") == {"A": 1.0, "B": 0.9}


def test_a_strong_untiered_player_is_capped_at_a_not_given_s_or_e():
    # UTRO 1.40 is nearest S by a mile, but an unknown player cannot be imputed S.
    assert nearest_tier(REAL_BANDS, 1.40) == "S"
    assert nearest_tier(REAL_BANDS, 1.40, cap="A") == "A"


def test_the_cap_does_not_affect_players_below_it():
    assert nearest_tier(REAL_BANDS, 0.60, cap="A") == "D"
    assert nearest_tier(REAL_BANDS, 0.98, cap="A") == "B"


def test_capping_at_b_pushes_a_strong_unknown_down_to_b():
    assert nearest_tier(REAL_BANDS, 1.40, cap="B") == "B"


def test_an_untiered_player_with_no_utro_uses_the_capped_median():
    # Capped bands A/B/C/D sort to 0.603, 0.752, 0.976, 1.042; median 0.864,
    # equidistant from B and C, and ties go to the stronger band.
    assert nearest_tier(REAL_BANDS, None, cap="A") == "B"
    # Uncapped, the median of all six sits higher.
    assert nearest_tier(REAL_BANDS, None) == "B"


def test_the_index_applies_the_cap_when_imputing():
    index = TierIndex(holdings={}, bands=REAL_BANDS, utro={"strong": 1.40},
                      impute_max="A")
    assert index.resolve("strong", "any") == ResolvedTier("A", "imputed")
    uncapped = TierIndex(holdings={}, bands=REAL_BANDS, utro={"strong": 1.40})
    assert uncapped.resolve("strong", "any") == ResolvedTier("S", "imputed")


def test_the_cap_never_touches_a_real_tier_holding():
    index = TierIndex(holdings={"p": (Holding("ch", "S", "2026-01-01"),)},
                      bands=REAL_BANDS, utro={}, impute_max="A")
    assert index.resolve("p", "ch") == ResolvedTier("S", "exact")
    assert index.resolve("p", "other") == ResolvedTier("S", "cross_channel")


def test_an_override_beats_every_other_source():
    index = TierIndex(
        holdings={"p": (Holding("ch", "D", "2026-01-01"),)},
        bands=REAL_BANDS, utro={"p": 0.60}, impute_max="A",
        overrides={"p": "A"},
    )
    assert index.resolve("p", "ch") == ResolvedTier("A", "override")
    assert index.resolve("p", "elsewhere") == ResolvedTier("A", "override")


def test_an_override_is_not_subject_to_the_impute_cap():
    index = TierIndex(holdings={}, bands=REAL_BANDS, utro={}, impute_max="A",
                      overrides={"p": "S"})
    assert index.resolve("p", "ch") == ResolvedTier("S", "override")


def test_players_without_an_override_are_unaffected():
    index = TierIndex(holdings={}, bands=REAL_BANDS, utro={"q": 1.40},
                      impute_max="A", overrides={"p": "S"})
    assert index.resolve("q", "ch") == ResolvedTier("A", "imputed")


# --- as-of resolution -------------------------------------------------------


def _dated_index():
    return TierIndex(
        holdings={}, bands={"S": 1.3, "A": 1.05, "B": 1.0}, utro={},
        overrides={"p1": "S"},
        history=TierHistory.build([TierChange("2026-09-19", "p1", "E", "S", "")]),
    )


def test_without_a_date_the_current_override_wins():
    assert _dated_index().resolve("p1", "c1").tier == "S"


def test_a_match_before_the_change_sees_the_old_tier():
    assert _dated_index().resolve("p1", "c1", on_date="2026-05-01").tier == "E"


def test_a_match_on_the_change_date_sees_the_new_tier():
    assert _dated_index().resolve("p1", "c1", on_date="2026-09-19").tier == "S"


def test_a_historical_tier_is_still_a_real_decision():
    assert _dated_index().resolve("p1", "c1", on_date="2026-05-01").source == OVERRIDE


def test_before_a_first_tiering_the_player_falls_back_to_imputation():
    index = TierIndex(
        holdings={}, bands={"A": 1.05, "B": 1.0}, utro={"p2": 1.0},
        overrides={"p2": "A"},
        history=TierHistory.build([TierChange("2026-09-19", "p2", None, "A", "")]),
    )
    resolved = index.resolve("p2", "c1", on_date="2026-01-01")
    assert resolved.source == IMPUTED
    assert resolved.tier == "B"


def test_before_a_first_tiering_a_channel_holding_still_wins():
    """Untiered then does not mean untiered entirely."""
    index = TierIndex(
        holdings={"p2": (Holding("c1", "C", "2026-01-01"),)},
        bands={"A": 1.05, "B": 1.0}, utro={}, overrides={"p2": "A"},
        history=TierHistory.build([TierChange("2026-09-19", "p2", None, "A", "")]),
    )
    resolved = index.resolve("p2", "c1", on_date="2026-01-01")
    assert (resolved.tier, resolved.source) == ("C", EXACT)


def test_resolve_all_threads_the_date_through():
    resolved = _dated_index().resolve_all(["p1"], "c1", on_date="2026-05-01")
    assert [r.tier for r in resolved] == ["E"]


def test_tiers_of_threads_the_date_through():
    assert _dated_index().tiers_of(["p1"], "c1", on_date="2026-05-01") == ["E"]


def test_an_index_with_no_history_behaves_exactly_as_before():
    index = TierIndex(holdings={}, bands={"A": 1.05}, utro={}, overrides={"p1": "A"})
    assert index.resolve("p1", "c1", on_date="1999-01-01").tier == "A"
