# committee

Evidence generator for the ET:Legacy 3v3 tiering committee. For each player it
shows the win probability their team's tier composition implied for every recent
match, what actually happened, and how the player themself performed — so the
committee can see whether a record matches the tier held.

Python 3.9+, no runtime dependencies.

## Use

Report on one player (Discord-ready markdown):

    python3 -m gibhub.cli player Kredenc
    python3 -m gibhub.cli player Kredenc --matches 40 --range 1y
    python3 -m gibhub.cli player adeb5cb6-285a-5680-af40-6ad161f885b2 --format json

Review a whole tier as a spreadsheet:

    python3 -m gibhub.cli bulk --tier A --tier B --out tier-ab.csv
    python3 -m gibhub.cli bulk --players shortlist.txt --out shortlist.csv

Inspect or refit the model:

    python3 -m gibhub.cli fit            # show the committed model
    python3 -m gibhub.cli fit --refit    # refit from the live API (~45s)
    python3 tools/check_fit.py           # sanity-check a fitted bundle

`--bundle` and `--cache` are global options and go *before* the subcommand:

    python3 -m gibhub.cli --cache /tmp/c player Kredenc

## Reading the output

`exp` is the probability the player's side wins, given the six players' tiers.
`res` is what happened. A win at `exp` below 50% or a loss above it is marked
`upset`. The headline line sums the per-match probabilities into expected wins and
compares that to actual wins:

- **OVER** — won at least 1.5 more than their tier predicted
- **UNDER** — won at least 1.5 fewer
- **ON TIER** — within that band

`utro` is the player's own performance rating for the match, playtime-weighted,
with the change from their lifetime 3v3 baseline in brackets. A run of losses
while favoured with UTRO *above* baseline says something different about a player
than the same losses with UTRO below it.

## The tier letters are not an A-to-E ladder

**In this data the tiers rank S > E > A > B > C > D.** Tier E is the second
*strongest* tier, not the weakest — its holders have a 51.5% 3v3 win rate over
5,413 matches and the second-highest median UTRO (1.10, against A's 1.04). The
pattern is identical in both tiered channels, which suggests E stands for
something like "Elite" rather than being the bottom of an alphabetical ladder.

The model never assumed an order — it fits each tier's value from results — and
the fitted order agrees with the independently computed UTRO bands on all 15 tier
pairs. But it is worth knowing before reading any output, and worth confirming
with whoever assigns the tiers.

    tier   fitted (log-odds)   median UTRO
    S           +0.69             1.240
    E           +0.43             1.104
    A           +0.19             1.040
    B           -0.10             0.972
    C           -0.33             0.793
    D           -0.88             0.603

## How the model works

A logistic regression over per-tier headcount differences, fitted on 6,918 decided
3v3 matches. It has no intercept, so two identically-tiered rosters always score
exactly 50%. Current fit: 62.4% accuracy, 0.229 Brier, 0.650 log loss.

Players without a tier in the match's channel fall back to their tier elsewhere;
players with no tier at all get one imputed from their 3v3 `utro_shrunken`. This
matters more than it sounds: only 8 of the 40 most recent 3v3 matches had all six
players tiered in their own channel, so a tier-only model would discard most of
the data. Every report footer counts how many of its inputs were imputed — treat a
report that is mostly imputed with corresponding caution.

## Reproducibility

`coefficients.json` is the committed model: coefficients, the tier index,
per-player UTRO, and a provenance stamp. Finished matches are immutable and cached
in `.cache/`, so the same command with the same cache produces identical output.
Only `fit --refit` changes the model.

## Known limitations

- **Tiers have no history**, so past matches are scored against today's tiers. A
  recently promoted player looks like they were overperforming for their whole
  history — hence the 6-month default window.
- **Tiers are per-channel**, so a player active in several channels may be scored
  against another channel's assignment. Those inputs are counted as
  "cross-channel" in the footer.
- **The approach is partly circular** by design: it asks whether a record is
  consistent with the tier held, not what tier a player should have in the
  absolute.
- **The API's own betting odds are unusable** and are not read. They are
  pari-mutuel payout multipliers from a joke-money pool, absent from every one of
  40 sampled 3v3 matches.

## Development

    python3 -m pytest                                    # unit tests, no network
    GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py
    python3 tools/record_fixtures.py                     # refresh test fixtures

`GIBHUB_TOKEN` is only needed for the `_internal` endpoints, which this tool does
not call. Public endpoints need no authentication.

Design and plan: `docs/superpowers/specs/` and `docs/superpowers/plans/`.
