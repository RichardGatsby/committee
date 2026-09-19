"""Pure scoring model. No I/O, no API knowledge."""

import math
from typing import Dict, Iterable, List, Sequence, Tuple

TIERS = ("S", "A", "B", "C", "D", "E")

Features = List[float]
# (features, outcome). Named to avoid colliding with dataset.Sample, which is a
# richer record carrying the match id and tier provenance.
TrainingPair = Tuple[Sequence[float], int]

# Fixed tier points, set rather than fitted. Note the ordering: E sits
# between S and A, matching the measured strength order S > E > A > B > C > D.
TIER_POINTS = {"S": 5.0, "E": 4.0, "A": 3.0, "B": 2.0, "C": 1.0, "D": 0.0}

ITERATIONS = 2000
LEARNING_RATE = 0.5
_EPSILON = 1e-12


def sigmoid(z: float) -> float:
    """Logistic function, written to avoid overflow at large |z|."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def feature_vector(alpha_tiers: Iterable[str], beta_tiers: Iterable[str]) -> Features:
    """Per-tier headcount difference, alpha minus beta, in TIERS order."""
    counts: Dict[str, float] = {tier: 0.0 for tier in TIERS}
    for tier in alpha_tiers:
        if tier not in counts:
            raise ValueError("unknown tier %r" % tier)
        counts[tier] += 1.0
    for tier in beta_tiers:
        if tier not in counts:
            raise ValueError("unknown tier %r" % tier)
        counts[tier] -= 1.0
    return [counts[tier] for tier in TIERS]


def predict(coefficients: Sequence[float], features: Sequence[float]) -> float:
    """P(alpha wins). A zero feature vector returns exactly 0.5."""
    return sigmoid(sum(c * f for c, f in zip(coefficients, features)))


def fit(
    samples: Sequence[TrainingPair],
    *,
    iterations: int = ITERATIONS,
    learning_rate: float = LEARNING_RATE,
) -> Features:
    """Batch gradient descent on the log-likelihood. No intercept: the sides are
    symmetric, so a mirrored roster must score exactly 0.5.

    Zero-initialised with a fixed step count, so the result is deterministic.
    """
    if not samples:
        raise ValueError("no samples to fit")

    width = len(TIERS)
    weights = [0.0] * width
    count = float(len(samples))

    for _ in range(iterations):
        gradient = [0.0] * width
        for features, outcome in samples:
            error = predict(weights, features) - outcome
            for index in range(width):
                gradient[index] += error * features[index]
        for index in range(width):
            weights[index] -= learning_rate * gradient[index] / count

    return weights


def points_delta(features: Sequence[float], points: Dict[str, float]) -> float:
    """Team points minus opponent points, from a per-tier headcount difference."""
    return sum(points[tier] * f for tier, f in zip(TIERS, features))


def fit_points(
    samples: Sequence[TrainingPair],
    points: Dict[str, float],
    *,
    iterations: int = ITERATIONS,
    learning_rate: float = LEARNING_RATE,
) -> Tuple[float, Features]:
    """Fit a single scale on the tier-points difference.

    The tier values are fixed on the tier list; the only free parameter is how
    much one point of team advantage is worth in log-odds. Returns the scale and
    the equivalent six coefficients (scale * points), so everything downstream
    treats this exactly like a free fit.
    """
    if not samples:
        raise ValueError("no samples to fit")

    deltas = [(points_delta(f, points), y) for f, y in samples]
    scale = 0.0
    count = float(len(deltas))

    for _ in range(iterations):
        gradient = 0.0
        for delta, outcome in deltas:
            gradient += (sigmoid(scale * delta) - outcome) * delta
        scale -= learning_rate * gradient / count

    return scale, [scale * points[tier] for tier in TIERS]


def metrics(coefficients: Sequence[float], samples: Sequence[TrainingPair]) -> Dict[str, float]:
    """Log loss, Brier score, and accuracy of `coefficients` over `samples`."""
    if not samples:
        raise ValueError("no samples to score")

    log_loss = 0.0
    brier = 0.0
    correct = 0

    for features, outcome in samples:
        p = predict(coefficients, features)
        clamped = min(max(p, _EPSILON), 1.0 - _EPSILON)
        log_loss -= outcome * math.log(clamped) + (1 - outcome) * math.log(1.0 - clamped)
        brier += (p - outcome) ** 2
        if (p >= 0.5) == bool(outcome):
            correct += 1

    count = float(len(samples))
    return {
        "log_loss": log_loss / count,
        "brier": brier / count,
        "accuracy": correct / count,
        "samples": len(samples),
    }
