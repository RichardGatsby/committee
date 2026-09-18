# 3v3 Committee Tiering Tool — Design

Date: 2026-09-18
Status: Approved

## Purpose

The tiering committee assigns gather tiers (S/A/B/C/D/E) to 3v3 players. Today that
judgement rests on memory and vibes. This tool produces a reproducible, paste-ready
evidence block per player, built entirely from the gibhub.gg API, answering one
question: **does this player's record match the tier they hold?**

The headline metric is expected wins (from tier composition) versus actual wins,
with each player's individual in-match performance alongside it.

## Data source

Base URL `https://gibhub.gg/api`, described by `openapi.yaml` in the repo root
(OpenAPI 3.1, gibhub API 1.0.0).

Public endpoints require no authentication. Only `/api/_internal/resolve-discord-ids`
requires the bearer token, which is read from the `GIBHUB_TOKEN` environment variable
and is never committed.

Endpoints used:

| Endpoint | Use |
| --- | --- |
| `GET /api/matches?size=3v3&state=finished` | match list with full rosters, winner, channel, dates |
| `GET /api/matches/{matchId}` | per-round per-player UTRO and playtime |
| `GET /api/players?size=3v3&tier=X` | roster of players holding each 3v3 tier |
| `GET /api/players/{playerId}?size=3v3` | lifetime 3v3 stats, `tiers[]`, W/L |
| `GET /api/players/{playerId}/spider?size=3v3` | per-metric percentile ranks |
| `GET /api/players/search?q=` | name to UUID resolution |
| `GET /api/players/{playerId}/matches?size=3v3` | paginated player match history |

### Rejected: the API's betting odds

`MatchDetail.betting.odds` exists but is a pari-mutuel payout multiplier from a
joke-money pool, not a win probability. Of the 40 most recent finished 3v3 matches
sampled on 2026-09-18, **every one had `betting: null`**. The one match found with
odds had three bets and multipliers of 55.14 vs 0.018. It is unusable and is not
read by this tool.

## The model

### Formulation

For each finished 3v3 match, the feature vector is the per-tier headcount difference
between the two sides:

```
x_t = (count of tier-t players on alpha) - (count of tier-t players on beta)
      for t in {S, A, B, C, D, E}

P(alpha wins) = sigmoid( sum_t  beta_t * x_t )
```

Logistic regression with **no intercept** — the sides are symmetric, so a mirrored
roster must yield exactly 0.5.

Fitted coefficients `beta_t` are the empirical value of each tier on a log-odds
scale. This is a deliberate secondary output: it shows the committee what each tier
is actually worth and whether adjacent tiers are statistically distinguishable.

Fitting is plain batch gradient descent over ~6 parameters with a fixed learning
rate, fixed iteration count, and zero-initialised weights — deterministic, no
third-party numerics.

### Training set

All matches from `GET /api/matches?size=3v3&state=finished`, paginated. Excluded:

- matches with `winner` neither `alpha` nor `beta` (draws, cancelled, unreported)
- matches whose rosters are not 3 players per side

Training uses the same tier-resolution rules as reporting, imputation included, so
the model is fitted on the same distribution it predicts over.

### Tier resolution

Tiers are **per channel** and carry only `updated_at` — there is no tier history.
A player's tier for a given match is resolved in order, and the path taken is
flagged in all output:

1. Player holds a 3v3 tier in that match's channel → flag `A` (exact)
2. No channel tier, but holds a 3v3 tier in another channel → flag `A*` (cross-channel).
   If several, the most recently updated wins.
3. No 3v3 tier anywhere → imputed from the player's lifetime 3v3 UTRO against the
   empirical per-tier UTRO bands → flag `A?` (imputed)

Imputation bands are derived once during `fit`: for each tier, the median lifetime
3v3 UTRO of its holders. An untiered player is assigned the tier whose median is
nearest their UTRO. A player with no 3v3 UTRO at all (zero rounds) is assigned the
median tier of the population and flagged `?`.

**Why imputation is required:** of the 40 most recent finished 3v3 matches, only 8
had all six players tiered in the match's own channel; 12 more had five of six. A
strict tier-only model would silently discard roughly 80% of matches. 134 players
hold a 3v3 tier in total (S:8, A:23, B:45, C:26, D:12, E:20).

Every report footer states how many tier inputs were exact, cross-channel, or
imputed.

### Per-match individual performance

For the reported player in each match, UTRO is taken from `MatchDetail.rounds[]`,
averaged across that player's rounds weighted by `playtime_percent`, and compared
to their lifetime 3v3 UTRO baseline from the player profile. Rounds where the
player does not appear are skipped; a match yielding no rounds for the player
reports UTRO as unavailable rather than zero.

## Report contents

Per player:

- Tier(s) held, with channel and `updated_at` for each
- Lifetime 3v3 record: matches, W/L, win rate, UTRO, KDR
- UTRO percentile row from the spider endpoint
- Per-match table over the selected window: date, maps, expected win % for the
  player's side, actual result, the player's weighted UTRO that match, and delta
  versus their baseline
- **Expected wins vs actual wins** over the window, with the difference labelled
  OVER / UNDER / ON TIER
- **Upsets**: wins at expected < 50% and losses at expected > 50%, each annotated
  with whether the player's own UTRO was above or below baseline in that match
- Provenance footer: tier-flag counts, coefficients fit date, data cutoff,
  sample size

### Thresholds

- Drawn matches are excluded from the expected-vs-actual totals (the model predicts
  a binary outcome) but still appear in the per-match table, marked `D`, with their
  expected percentage shown. The footer counts them.
- A match is an upset win when expected < 0.50, an upset loss when expected > 0.50.
- The over/under label uses actual minus expected wins: `>= +1.5` OVER,
  `<= -1.5` UNDER, otherwise ON TIER. Stated in the output so it is not a hidden
  constant.

## Components

Only `api.py` performs network I/O. `model.py`, `report.py`, and `render.py` are
pure functions over plain data structures.

| File | Purpose | Depends on |
| --- | --- | --- |
| `gibhub/api.py` | GET + JSON, retry with backoff, pagination helper, optional bearer | stdlib |
| `gibhub/cache.py` | disk cache keyed by match id, for finished matches only | stdlib |
| `gibhub/tiers.py` | tier roster fetch, UTRO bands, three-step resolution | api, cache |
| `gibhub/model.py` | pure: feature vectors, logistic fit, predict, fit metrics | — |
| `gibhub/dataset.py` | walks finished 3v3 matches into (features, outcome) rows | api, tiers |
| `gibhub/report.py` | pure: fetched data + model → `PlayerReport` | — |
| `gibhub/render.py` | pure: `PlayerReport` → markdown, CSV, JSON | — |
| `gibhub/cli.py` | argument parsing and wiring | all |
| `coefficients.json` | committed fitted model and fit metadata | — |

`PlayerReport` is a dataclass; renderers read only that, so a new output format
never touches fetching or scoring.

## CLI

```
committee player <name|uuid> [--matches 20] [--channel NAME] [--range 6m]
                             [--to YYYY-MM-DD] [--format md|json|csv]
committee bulk (--tier A [--tier B] | --players FILE) [--out FILE] [--range 6m]
committee fit [--refit]
```

- `player` — default output is Discord-ready markdown on stdout. Default window
  `--range 6m`, default `--matches 20`.
- `bulk` — one CSV row per player, for sorting a whole tier in a spreadsheet.
  Accepts tier selectors or a file of names/UUIDs, one per line. Columns:
  `player_id, nick, discord_nick, tier, tier_channel, tier_updated_at, matches,
  wins, losses, draws, win_rate, expected_wins, actual_wins, delta, label,
  upset_wins, upset_losses, utro, utro_percentile, kdr, exact_tiers,
  crosschannel_tiers, imputed_tiers`.
- `fit` — refits from the live API and rewrites `coefficients.json`, printing
  log-loss, Brier score, accuracy, and the fitted per-tier log-odds values.
  Without `--refit` it reports the stored model's metadata and exits.

Name arguments are resolved through `/api/players/search`. An ambiguous name lists
the candidates with their UUIDs and exits non-zero rather than guessing.

## Caching and reproducibility

Finished matches are immutable, so `GET /api/matches/{matchId}` responses for
`state == "finished"` are cached under `.cache/matches/<match_id>.json`
(gitignored). Nothing else is cached: player profiles change as people play, and a
stale profile would quietly produce a wrong number.

Same arguments plus same cache produce byte-identical output. Every report header
stamps the coefficients fit date, the data cutoff, and the sample size, so two
reports can be compared or shown to be incomparable. `--refit` is the only
operation that changes the model.

## Error handling

- HTTP 5xx and connection errors: three retries with exponential backoff, then a
  clear message naming the endpoint. No silent partial reports.
- HTTP 404 on a player: message with the searched term, exit non-zero.
- HTTP 429: honour `Retry-After` when present, otherwise back off.
- Missing `coefficients.json`: instruct the user to run `committee fit --refit`;
  do not fit implicitly, which would make output non-reproducible.
- A match whose roster cannot be resolved is skipped and counted in the footer,
  never silently dropped.

## Testing

TDD throughout. Fixtures are recorded from the live API into `tests/fixtures/`, and
a fake client satisfying the `api.py` interface means **no unit test performs
network I/O**.

Order of implementation, each test-first:

1. `model` — sigmoid edge cases; symmetry (mirrored rosters give exactly 0.5);
   known-answer fit on synthetic separable data; fit metrics on a known set
2. `tiers` — all three resolution paths; multi-channel tie-break by `updated_at`;
   unknown player; UTRO band construction
3. `dataset` — roster parsing; exclusion of draws and malformed rosters; feature
   vector signs
4. `report` — expected-vs-actual arithmetic; upset classification at the 0.50
   boundary; weighted UTRO averaging; absent-player match
5. `render` — golden markdown, golden CSV, JSON round-trip
6. `cli` — argument wiring, ambiguous-name path, missing-coefficients path

One integration test hits the live API as a contract check, skipped unless
`GIBHUB_INTEGRATION=1` is set.

## Known limitations

- **No tier history.** Past matches are scored with today's tiers. A player
  recently promoted A→S appears to have been overperforming as an A for their whole
  history. Mitigated by defaulting to `--range 6m` and printing each tier's
  `updated_at`; not solvable from the API as it stands.
- **Tier-based strength is partly circular** — the committee is being shown
  evidence derived from the tiers it assigns. This is deliberate: the question asked
  is "is this player's record consistent with their current tier", not "what tier
  should this player have in the absolute".
- **Imputed tiers carry model error into the result.** Flagged per input and
  counted per report so the committee can discount accordingly.
- **Per-channel tiers** mean a player active across channels may be scored against
  a tier assigned by a different channel's committee.

## Out of scope

- Any write operation against the API
- 6v6 analysis
- A web UI or hosted service
- Automatic tier assignment — the tool presents evidence, people decide
