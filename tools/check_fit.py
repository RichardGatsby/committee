"""Sanity-check a fitted bundle before trusting it. Exits non-zero on failure.

    python3 tools/check_fit.py [coefficients.json]

Deliberately does NOT assume the tier letters form an ordered ladder: in this
dataset the order by strength is S > E > A > B > C > D, so E is the second
strongest tier rather than the weakest. What it does assert is that the fitted
tier values agree with the independent UTRO bands about which tiers are stronger.
"""

import json
import sys

TIERS = ("S", "A", "B", "C", "D", "E")


def main(path="coefficients.json"):
    bundle = json.load(open(path, encoding="utf-8"))
    coefficients = bundle["coefficients"]
    bands = bundle["bands"]
    metrics = bundle["fit_metrics"]

    print("samples: %d   cutoff: %s" % (bundle["sample_size"], bundle["data_cutoff"]))
    print("metrics: %s" % metrics)

    ranked = sorted(TIERS, key=lambda t: -coefficients[t])
    print("\ntier strength, fitted (log-odds) vs UTRO band:")
    for tier in ranked:
        print("  %s  %+.4f   band %s" % (
            tier, coefficients[tier],
            "%.3f" % bands[tier] if tier in bands else "n/a"))
    print("\norder by fitted value: %s" % " > ".join(ranked))
    print("order by UTRO band:    %s" % " > ".join(
        sorted((t for t in TIERS if t in bands), key=lambda t: -bands[t])))

    failures = []
    if bundle["sample_size"] < 500:
        failures.append("suspiciously few training matches")
    if metrics["accuracy"] <= 0.5:
        failures.append("accuracy is no better than a coin flip")
    if metrics["brier"] >= 0.25:
        failures.append("Brier score is no better than always predicting 0.5")

    # The fit and the UTRO bands are independent views of tier strength. They need
    # not agree exactly, but a strong disagreement means one of them is wrong.
    common = [t for t in TIERS if t in bands]
    by_fit = sorted(common, key=lambda t: -coefficients[t])
    by_band = sorted(common, key=lambda t: -bands[t])
    discordant = sum(
        1
        for i, a in enumerate(common)
        for b in common[i + 1:]
        if (by_fit.index(a) < by_fit.index(b)) != (by_band.index(a) < by_band.index(b))
    )
    pairs = len(common) * (len(common) - 1) // 2
    print("\ndisagreeing tier pairs between fit and UTRO bands: %d of %d" % (discordant, pairs))
    if discordant > pairs // 3:
        failures.append("fitted tier order disagrees with the UTRO bands")

    if failures:
        print("\nFAILED: " + "; ".join(failures))
        return 1
    print("\nfit OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "coefficients.json"))
