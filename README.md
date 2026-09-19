# committee

Evidence generator for the ET:Legacy 3v3 tiering committee. For each player it
works out what their team's tier composition said should happen in every recent
match, compares that to what actually happened, and states plainly whether the
tier they hold should change.

Python 3.9+, no runtime dependencies.

## Use

Report on one player:

    python3 -m gibhub.cli player Lepari                   # last 4 months
    python3 -m gibhub.cli player Jassi --range 1y --extremes 5
    python3 -m gibhub.cli player devix --only gathers
    python3 -m gibhub.cli player Kredenc --from 2026-01-01 --format json

Scan every tiered player at once and rank the mis-tiered:

    python3 -m gibhub.cli scan                       # last 1y, 50+ games, no PL
    python3 -m gibhub.cli scan --only gathers --min-games 100
    python3 -m gibhub.cli scan --all --out scan.csv  # every player, as CSV

One sweep of matches scores everyone, so it takes about as long as a single
player report rather than one report per player. Columns:

- **Per 100** — wins per 100 games above or below what their tier predicts. This
  is the effect size and the number to argue over.
- **Tiers off** — how many tier steps that gap is worth.
- **Decision** — the same wording a player report gives.
- **Confidence** — 1-in-N that luck alone did this, **capped at 1 in 10000**.
  Beyond that it stops measuring evidence and starts measuring broken
  assumptions, chiefly that games are independent, which they are not.
- **Read with care because** — the reason to discount the row: one teammate
  filling more than a quarter of the sample, heavy imputation, or too few games
  to detect a one-tier error.

Only players whose record differs from their tier are listed; `--all` shows
everyone. The scan scores only players carrying a **committee tier**, so a
bundle fitted without `--overrides` has nobody to score and the command says
so rather than printing an empty table.

Review a whole tier as a spreadsheet:

    python3 -m gibhub.cli bulk --tier A --tier B --out tier-ab.csv
    python3 -m gibhub.cli bulk --players shortlist.txt --out shortlist.csv

Inspect or refit the model:

    python3 -m gibhub.cli fit            # show the committed model
    python3 tools/check_fit.py           # sanity-check a fitted bundle

`--bundle` and `--cache` are global and go *before* the subcommand:

    python3 -m gibhub.cli --cache /tmp/c player Lepari

### Options that change what is counted

| option | effect |
| --- | --- |
| `--range 4m` | rolling window, the default. `1y`, `6m`, `2w` all work |
| `--from 2026-01-01` | fixed start date instead of a rolling window |
| `--to 2026-06-01` | exclusive end date |
| `--only legacy` | restrict to one kind of game; repeatable. See below |
| `--with-poland` | also count Poland gathers, which are left out by default |
| `--extremes 5` | rows in the surprising-results tables (default 3, `0` hides) |
| `--matches N` | cap matches read. Default `0` = every match in the window |

Every match in the window is read by default. `--matches N` takes the most recent
N and the report says so, because a cap can change the verdict: reading 50 of one
player's 339 matches reported OVER where the full window was ON TIER.

## Reading the output

    **Expected 13.33 wins, actual 7 — -6.33 → CLEARLY UNDER**

    ### → MOVE DOWN: A → B

If a lot of the tiers behind a verdict had to be guessed, the report says so
above the headline, where a cropped screenshot still catches it:

    > **UNRELIABLE: 46% of the tiers behind this verdict were guessed rather
    > than set by the committee. Tier those players before acting on it.
    > 18 of the 39 players in this window had no committee tier.**

`CAUTION` at 20% of tier inputs guessed, `UNRELIABLE` at 40%. Only imputed tiers
count as guesses; a tier held in another channel is a real committee decision.
Imputation error, not luck, is the largest source of false signal here, so this
is the first thing to check before arguing over a number.

The scan prints the same warning for the population it just swept. That one
matters more than it looks: the scan scores only committee-tiered players and
drops the rest silently, so a short, clean-looking table can mean the list is
thin rather than that everyone is correctly placed.

The headline sums each match's win probability into expected wins and compares it
to what happened. The label says how likely that gap is to be luck:

| label | meaning | decision |
| --- | --- | --- |
| `CLEARLY OVER` | wins **more** than the tier predicts; luck explains it less than 1 time in 100 | `MOVE UP` |
| `OVER` | same, less than 1 time in 20 | `CONSIDER MOVING UP` |
| `ON TIER` | within what luck produces | `KEEP` |
| `UNDER` | wins **fewer**, less than 1 time in 20 | `CONSIDER MOVING DOWN` |
| `CLEARLY UNDER` | wins fewer, less than 1 time in 100 | `MOVE DOWN` |

OVER means the tier is too **low** (they beat it), UNDER means it is too **high**.
The target tier comes off the points scale rather than the alphabet, so "up" from
A is E, not S.

The label reads off that probability rather than a raw win count, because the same
gap means different things at different sample sizes: +5 wins is real over 20
matches and noise over 400. An earlier version used a fixed ±1.5 win threshold and
called a player OVER on a +4 gap across 324 matches — a 1.2% edge that is noise.

Below the headline:

- **stacked vs underdog** — the record when favoured against when not, so a record
  built entirely on stacked teams is visible rather than hidden inside one number
- **By type of game** — a separate verdict per kind of game
- **Biggest underdog wins** and **worst losses while favoured** — the most
  surprising results with both lineups, their tiers, and the player's own rating

`Tier lead` is the team's tier-points margin. `Win chance` is what the model gave
them. `His rating` is UTRO for that match, playtime-weighted, with the change from
their baseline for the window in brackets.

The per-match table is not printed — it runs to hundreds of rows — but the verdict
is computed from every match in the window. `--format json` has them all.

## Types of game

Matches are split by the `gather` tag, the channel, and whether that channel is a
real Discord one or a synthetic tournament one:

| key | covers | counted |
| --- | --- | --- |
| `legacy` | ET:Legacy Events and ET:Legacy Gathers 3v3 | yes |
| `poland` | Poland ET:Legacy 3v3 | yes |
| `cup` | cups, tournaments, league seasons, and games between named teams | yes |
| `other` | the small gather channels: subAk, eV!L, Frag Center, PRAWDZIWY | **no** |

**Reports count `legacy` + `cup` by default.** Poland is over half the match
volume, so counting it by default lets it dominate every verdict; `--with-poland`
adds it back, and `--only poland` isolates it. The small one-off channels are
dropped everywhere unless named.

**The model still trains on Poland.** Dropping two thirds of the sample would
weaken the fit for no gain, since the tiers being fitted are the same either way.
So the training set is legacy + poland + cup while a report defaults to
legacy + cup.

`--only gathers` means legacy + poland. `--only team` is a synonym for `cup`:
both are played by fixed teams rather than picked sides, which is the distinction
that matters when reading a result.

Tournaments carrying no `cup` tag — Nations Cup and subak's cups among them — are
caught by their zero-padded channel id, which is how the API marks a tournament
channel apart from a Discord one.

## The tier list

The API's own tiers are incomplete, so the committee's list is the source of
truth. It lives in `data/tierlist-events-3v3.txt`, one name per line under its
tier heading:

    [A]
    Jassi
    chuCk -> czkk_             # Discord name differs from the in-game one
    hevimies -> jussi8030

`Name -> lookup` pins an entry whose Discord name is not searchable to the account
to use (a nick or a UUID). Resolve it into an overrides file, then refit:

    python3 tools/resolve_tierlist.py data/tierlist-events-3v3.txt overrides.txt
    python3 -m gibhub.cli fit --refit \
        --tier-channel Events --points --impute-max A --overrides overrides.txt

The resolver refuses to guess. A fuzzy hit is accepted only when the found nick
shares a substring with the search term — without that, search returns `Gilbey`
for `maNic` and `juissi` for `poshtat` — and two list entries resolving to one
account are both rejected rather than silently one-tiered. Anything it cannot
place is printed for a human to resolve by UUID.

## How the model works

Each tier is worth fixed points — **S 5, E 4, A 3, B 2, C 1, D 0** — and a team's
strength is the sum of its three players' points. The only fitted parameter is how
much one point of advantage is worth:

    P(win) = sigmoid(0.44 × (my team's points − their points))

So a +2 point edge is a 71% favourite, +4 is 85%. There is no intercept, so two
equal rosters always score exactly 50%. Fitted on 6,382 decided 3v3 matches:
63.9% accuracy, 0.220 Brier, 0.630 log loss.

Fitting all six tier values freely instead scores marginally better but is harder
to check by hand, and it valued S well below what the 5-point scale implies — so
the fixed scale somewhat overrates S relative to what results show. Run
`fit --refit` without `--points` to compare.

### The tier letters are not an A-to-E ladder

**The strength order is S > E > A > B > C > D.** Tier E is the second *strongest*
tier: its holders have a 51.5% 3v3 win rate over 5,413 matches and the second
highest median UTRO, and the pattern is identical in both tiered channels. E
appears to stand for something like "Elite".

Nothing in the tool assumes an order — the fitted values agree with the
independently computed UTRO bands on all 15 tier pairs — but every place that
needs "the next tier up" reads it off the points scale, never the alphabet.

    tier   points   log-odds   median UTRO
    S         5      +2.19        1.250
    E         4      +1.75        1.099
    A         3      +1.32        1.042
    B         2      +0.88        0.976
    C         1      +0.44        0.748
    D         0       0.00        0.603

### Players with no tier

Tiers are per channel. A player without one in the match's channel falls back to
their tier elsewhere; a player with none anywhere gets one imputed from their 3v3
`utro_shrunken`, **capped at A** (`--impute-max`). The cap exists because a
genuinely elite player would already have been tiered, and is applied by measured
strength, so capping at A also excludes E.

This matters more than it sounds: before the committee list was loaded, only 8 of
the 40 most recent 3v3 matches had all six players tiered in their own channel. It
also moves verdicts. The same player's record, scored four ways:

| model | gap | luck |
| --- | --- | --- |
| free six-coefficient fit | +24.7 | 1 in 1667 |
| fixed points, uncapped imputation | +20.2 | 1 in 250 |
| fixed points, imputation capped at A | +15.3 | 1 in 43 |
| the above plus the committee tier list | +10.3 | 1 in 11 |

Most of that player's apparent overperformance was imputation error. **Treat a
report whose inputs are largely imputed as provisional** — the footer counts the
four sources (committee override, exact channel tier, cross-channel, imputed).

## Reproducibility

`coefficients.json` is the committed model: the fitted scale, tier points, tier
index, per-player UTRO, the overrides and the imputation cap. Finished matches are
immutable and cached in `.cache/`, so the same command with the same cache gives
identical output. Only `fit --refit` changes the model, and every report footer
stamps the fit date, sample size and window so two reports can be compared — or
shown to be incomparable.

## Known limitations

- **Tiers have no history**, so past matches are scored against today's tiers. A
  recently promoted player looks like they were overperforming all year. Hence the
  4-month default window.
- **Tiers are per channel**, so a player active in several may be scored against
  another channel's assignment; those inputs are counted as "cross-channel".
- **The approach is partly circular** by design: it asks whether a record is
  consistent with the tier held, not what tier a player should have in the
  absolute.
- **The `cup` bucket is inferred by exclusion** — anything without a `gather` tag.
  A gather reported in an unrecognised channel would land there.
- **The API's own betting odds are unusable** and are not read: pari-mutuel payout
  multipliers from a joke-money pool, absent from all 40 sampled 3v3 matches.

## Development

    python3 -m pytest                                    # unit tests, no network
    GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py
    python3 tools/record_fixtures.py                     # refresh test fixtures

`GIBHUB_TOKEN` is only needed for the `_internal` endpoints, which this tool does
not call. Public endpoints need no authentication.

Design and plan: `docs/superpowers/specs/` and `docs/superpowers/plans/`.

Working on this: `CLAUDE.md` has the baseline context and the domain facts that
trip people up. Conventions live in `.claude/skills/`:

| skill | covers |
| --- | --- |
| `code-quality` | test-first, functional core with I/O at the edges, stdlib-only Python 3.9 |
| `unslop` | prose in docs, commits and committee-facing output |
| `conventional-commits` | commit format, and what a refit must record |
