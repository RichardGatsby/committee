import pytest

from gibhub.tiers import Holding, ResolvedTier, TierIndex, build_bands, nearest_tier

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
