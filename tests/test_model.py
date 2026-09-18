import pytest

from gibhub.model import TIERS, feature_vector, predict, sigmoid


def test_sigmoid_at_zero_is_exactly_half():
    assert sigmoid(0.0) == 0.5


def test_sigmoid_is_monotonic_and_bounded():
    assert 0.0 < sigmoid(-10.0) < sigmoid(0.0) < sigmoid(10.0) < 1.0
    # Saturates to the exact bounds at large |z|; it must never leave [0, 1].
    assert sigmoid(50.0) <= 1.0
    assert sigmoid(-50.0) >= 0.0


def test_sigmoid_does_not_overflow_on_large_negative():
    assert sigmoid(-1000.0) == pytest.approx(0.0, abs=1e-12)


def test_tier_order_is_strongest_first():
    assert TIERS == ("S", "A", "B", "C", "D", "E")


def test_feature_vector_counts_the_difference_per_tier():
    features = feature_vector(["S", "A", "A"], ["B", "C", "E"])
    assert features == [1.0, 2.0, -1.0, -1.0, 0.0, -1.0]


def test_mirrored_rosters_give_a_zero_vector():
    assert feature_vector(["S", "B", "D"], ["D", "S", "B"]) == [0.0] * 6


def test_feature_vector_rejects_an_unknown_tier():
    with pytest.raises(ValueError, match="unknown tier 'Z'"):
        feature_vector(["Z", "A", "A"], ["B", "C", "E"])


def test_predict_on_mirrored_rosters_is_exactly_half():
    coefficients = [0.9, 0.6, 0.3, 0.0, -0.4, -0.8]
    assert predict(coefficients, feature_vector(["S", "B", "D"], ["D", "S", "B"])) == 0.5


def test_predict_favours_the_stronger_side():
    coefficients = [0.9, 0.6, 0.3, 0.0, -0.4, -0.8]
    assert predict(coefficients, feature_vector(["S", "S", "S"], ["E", "E", "E"])) > 0.9


from gibhub.model import fit, metrics


def _separable_samples():
    """Alpha wins whenever it has one extra S; beta wins the mirror image."""
    samples = []
    for _ in range(20):
        samples.append(([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1))
        samples.append(([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0))
    return samples


def test_fit_learns_a_positive_weight_for_the_deciding_tier():
    weights = fit(_separable_samples())
    assert weights[0] > 0.5
    assert all(abs(w) < 1e-9 for w in weights[1:])


def test_fit_is_deterministic():
    assert fit(_separable_samples()) == fit(_separable_samples())


def test_fit_rejects_an_empty_sample_set():
    with pytest.raises(ValueError, match="no samples"):
        fit([])


def test_fit_on_balanced_evidence_stays_near_zero():
    samples = [([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1), ([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0)]
    assert fit(samples)[0] == pytest.approx(0.0, abs=1e-9)


def test_metrics_on_a_perfect_fit():
    samples = _separable_samples()
    result = metrics(fit(samples), samples)
    assert result["accuracy"] == 1.0
    assert result["brier"] < 0.25
    assert result["log_loss"] < 0.7
    assert result["samples"] == 40


def test_metrics_on_a_coin_flip_model():
    samples = _separable_samples()
    result = metrics([0.0] * 6, samples)
    assert result["brier"] == pytest.approx(0.25)
    assert result["log_loss"] == pytest.approx(0.6931471805599453)


from gibhub.model import TIER_POINTS, fit_points, points_delta


def test_the_default_points_put_e_between_s_and_a():
    assert TIER_POINTS["S"] > TIER_POINTS["E"] > TIER_POINTS["A"] > TIER_POINTS["B"]
    assert TIER_POINTS["B"] > TIER_POINTS["C"] > TIER_POINTS["D"]


def test_points_delta_sums_the_tier_values():
    # alpha has an extra S (5) and one fewer D (0): +5.
    assert points_delta([1.0, 0, 0, 0, -1.0, 0], TIER_POINTS) == 5.0
    # A mirrored roster is worth nothing either way.
    assert points_delta([0.0] * 6, TIER_POINTS) == 0.0


def test_points_delta_uses_the_tiers_order():
    # feature order is S, A, B, C, D, E — the E slot is last, worth 4.
    assert points_delta([0, 0, 0, 0, 0, 1.0], TIER_POINTS) == 4.0


def test_fit_points_learns_a_positive_scale():
    samples = [([1.0, 0, 0, 0, -1.0, 0], 1)] * 20 + [([-1.0, 0, 0, 0, 1.0, 0], 0)] * 20
    scale, coefficients = fit_points(samples, TIER_POINTS)
    assert scale > 0
    # Coefficients stay proportional to the fixed points.
    assert coefficients == [scale * TIER_POINTS[t] for t in ("S", "A", "B", "C", "D", "E")]


def test_fit_points_is_deterministic():
    samples = [([1.0, 0, 0, 0, -1.0, 0], 1)] * 10 + [([-1.0, 0, 0, 0, 1.0, 0], 0)] * 10
    assert fit_points(samples, TIER_POINTS) == fit_points(samples, TIER_POINTS)


def test_fit_points_rejects_an_empty_sample_set():
    with pytest.raises(ValueError, match="no samples"):
        fit_points([], TIER_POINTS)


def test_a_points_fit_keeps_mirrored_rosters_at_exactly_half():
    samples = [([1.0, 0, 0, 0, -1.0, 0], 1)] * 10 + [([-1.0, 0, 0, 0, 1.0, 0], 0)] * 10
    _, coefficients = fit_points(samples, TIER_POINTS)
    assert predict(coefficients, [0.0] * 6) == 0.5
