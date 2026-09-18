# committee

Evidence generator for the ET:Legacy 3v3 tiering committee. For each player it
shows the win probability their team's tier composition implied for every recent
match, what actually happened, and how the player themself performed — so the
committee can see whether a record matches the tier held.

Python 3.9+, no runtime dependencies.

## Use

Report on one player (Discord-ready markdown):

    python3 -m gibhub.cli player Kredenc                  # last 4 months
    python3 -m gibhub.cli player Kredenc --range 1y
    python3 -m gibhub.cli player Kredenc --from 2026-01-01 --extremes 5
    python3 -m gibhub.cli player adeb5cb6-285a-5680-af40-6ad161f885b2 --format json

The default window is a rolling **4 months** and every match in it is read.
`--matches N` caps that, but a cap takes the most recent N and the report says so
— on one player a 50-match cap turned a correct "ON TIER" into a spurious "OVER".

Review a whole tier as a spreadsheet:

    python3 -m gibhub.cli bulk --tier A --tier B --out tier-ab.csv
    python3 -m gibhub.cli bulk --players shortlist.txt --out shortlist.csv

Inspect or refit the model:

    python3 -m gibhub.cli fit            # show the committed model
    python3 tools/check_fit.py           # sanity-check a fitted bundle

    # refit from the live API (~45s). This is how the committed model was made:
    python3 -m gibhub.cli fit --refit \
        --tier-channel Events --points --impute-max A

`--tier-channel` restricts the tier index to one channel's assignments (matching a
channel id or a substring of its name), so the coefficients and UTRO bands come
only from that committee's tiers. `--points` fixes the tier values instead of
fitting six free ones; `--points "S=5,E=4,A=3,B=2,C=1,D=0"` sets your own scale.
`--impute-max` caps what an untiered player can be imputed as.

`--bundle` and `--cache` are global options and go *before* the subcommand:

    python3 -m gibhub.cli --cache /tmp/c player Kredenc

## Reading the output

`exp` is the probability the player's side wins, given the six players' tiers.
`res` is what happened. A win at `exp` below 50% or a loss above it is marked
`upset`. The headline sums the per-match probabilities into expected wins and
compares that to actual wins, then says how likely that gap is to be luck:

    **Expected 179.06 wins, actual 183 — +3.94 → ON TIER**
    _(+1 per 100 games; luck alone does this 1 time in 3)_

- **CLEARLY OVER / CLEARLY UNDER** — a gap this big happens by luck less than 1
  time in 100. Strong evidence the tier is wrong.
- **OVER / UNDER** — less than 1 time in 20. Reasonable evidence.
- **ON TIER** — within what luck produces. No evidence either way.

Each report then states the decision outright, naming the tier to move to. OVER
means winning *more* than the tier predicts, so the tier is too low and the player
moves **up**; UNDER means the tier is too high and they move **down**:

    ### → MOVE DOWN: A → B
    ### → CONSIDER MOVING UP: B → A
    ### → KEEP at E

The target tier comes off the points scale, not the alphabet, so "up" from A is E
rather than S.

The label reads off that probability rather than a raw win count, because the same
gap means different things at different sample sizes: +5 wins is real over 20
matches and noise over 400. An earlier version used a fixed +-1.5 win threshold and
called a player OVER on a +4 gap across 324 matches — a 1.2% edge that is pure
noise. The two numbers in brackets are the ones to argue over: **per 100 games** is
how big the effect is, comparable between players however many matches each has
played, and **1 time in N** is how sure you can be.

`pts` is the team's tier-points margin, `utro` the player's own performance rating
for the match, playtime-weighted, with the change from their baseline in brackets.

`--extremes N` (default 3) additionally tables the N biggest underdog wins and the
N worst losses while favoured, each with both lineups and their tier sources, so a
surprising result can be read without digging.

## Types of game

Matches are split into five kinds, read off the `gather` tag, the channel, and
whether that channel is a real Discord one or a synthetic tournament one:

| key | what it covers | counted |
| --- | --- | --- |
| `legacy` | ET:Legacy Events and ET:Legacy Gathers 3v3 | yes |
| `poland` | Poland ET:Legacy 3v3 | yes |
| `cup` | cups, tournaments, league seasons, and games between named teams | yes |
| `other` | the small gather channels: subAk, eV!L, Frag Center, PRAWDZIWY | **no** |

`gathers` means **legacy + poland** — the two channels the committee tiers for.
The small one-off gather channels are dropped from reports *and* from the fit,
since nobody is tiered on them; ask for them by name (`--only other`, or
`--only all`) to see them.

Cups and team games share a category because both are played by fixed teams
rather than picked sides, which is the distinction that matters for reading a
result. Tournaments carrying no `cup` tag — Nations Cup and subak's cups among
them — are caught by their zero-padded channel id, which is how the API marks a
tournament channel apart from a Discord one.

A report covering more than one kind gets a **By type of game** table with a
separate verdict for each, since a player can be correctly tiered in gathers and
not in team games. `--only` restricts the whole report and is repeatable:
`--only legacy`, `--only gathers`, `--only team`. A run of losses
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

    tier   points   log-odds   median UTRO
    S         5      +1.761        1.250
    E         4      +1.409        1.099
    A         3      +1.057        1.042
    B         2      +0.704        0.976
    C         1      +0.352        0.752
    D         0       0.000        0.603

The default point scale puts E at 4, between S and A, to match this.

## How the model works

Each tier is worth fixed points — **S 5, E 4, A 3, B 2, C 1, D 0** — and a team's
strength is the sum of its three players' points. The only fitted parameter is how
much one point of advantage is worth, currently **0.352 log-odds per point**:

    P(win) = sigmoid(0.352 * (my team's points - their points))

So a +2 point edge is a 67% favourite, +4 is 83%. There is no intercept, so two
equal rosters always score exactly 50%. Fitted on 6,920 decided 3v3 matches:
62.3% accuracy, 0.228 Brier, 0.647 log loss.

Fitting all six tier values freely instead scores marginally better (62.8%,
0.227 Brier) but is harder to check by hand, and it valued S at only +0.94
log-odds against the +1.76 the 5-point scale implies — so the fixed scale
somewhat overrates S relative to what results show. Run `fit --refit` without
`--points` to compare.

Players without a tier in the match's channel fall back to their tier elsewhere;
players with no tier at all get one imputed from their 3v3 `utro_shrunken`,
**capped at A** by default (`--impute-max`). The cap exists because a genuinely
elite player would already have been tiered, so imputing S or E to an unknown is
unjustified. It is applied by measured strength, not by letter — capping at "A"
also excludes E, since E outranks A here.

Imputation matters more than it sounds: only 8 of the 40 most recent 3v3 matches
had all six players tiered in their own channel, so a tier-only model would
discard most of the data. Every report footer counts how many of its inputs were
imputed — treat a report that is mostly imputed with corresponding caution, and
note that the cap is a conservative assumption that can move a player's verdict.

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
  "cross-channel" in the footer. With `--tier-channel` this gets more common, not
  less: everyone keeps the selected channel's tier wherever they play.
- **The stats line is scoped to `--range`, not career-to-date.** It is labelled
  with its window for that reason. The UTRO baseline each match is compared
  against is scoped the same way.
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
