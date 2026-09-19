# Tier history design

**Date:** 2026-09-19
**Status:** approved, not yet implemented

## The problem

Tiers have no history, so every past match is scored against today's tiers. When
the committee changes a tier, the whole record is retroactively rewritten.

Measured by **simulation**: a scratch copy of `coefficients.json` with hevimies
(`jussi8030`) moved from E to S, and the 4-month scan re-run against it. No tier
was changed and none is proposed here — he was chosen because the tool already
reads `MOVE UP: E → S` for him, so he is the most likely first case, not a
decided one.

| player | before | after | swing | verdict |
| --- | --- | --- | --- | --- |
| jussi8030 | +10.8 | +1.0 | −9.8 | CLEARLY OVER → ON TIER |
| Plain | −15.1 | −11.0 | +4.1 | CLEARLY UNDER → UNDER |
| tezaXo | +10.7 | +13.6 | +2.9 | ON TIER → OVER |
| devix | +0.1 | −2.4 | −2.5 | ON TIER → ON TIER |

17 of 18 scanned players moved. Three harms:

1. **The evidence deletes itself.** hevimies goes +22.58 CLEARLY OVER → +0.39 ON
   TIER over the same 336 matches. The record that justified the promotion is
   gone the moment it is applied.
2. **It manufactures a case against a third party.** tezaXo played no new games
   and went 1 in 17 → 1 in 45, ON TIER → OVER. He mostly *faced* hevimies, so
   strengthening the opponent retroactively inflated his record.
3. **It destroys a real case.** Plain went 1 in 335 → 1 in 41 without playing.

Everyone moves because hevimies is in roughly a fifth of the match pool. Any
promotion of an active player does this.

## Where history comes from

**Not the API.** There is no `tier_history` field, and `updated_at` on holdings
is useless: all 134 holdings read 2026-09, a bulk re-sync rather than a decision
date.

**Not git.** All six commits touching `data/tierlist-events-3v3.txt` are pure
additions. There is not one promotion or demotion in the history. Seeding from
git would record bulk name resolution as committee decisions.

**An append-only change log**, written when a decision is made.

## Decisions

### 1. A separate `data/tier-changes.tsv`

    # date       player   from  to  note
    2026-10-04   somebody   B     A   +9.1 over 412 games, 1 in 300

Tab-separated, one decision per line, append-only, sorted by date.

- `player` is the same token the tier list uses (a nick or a UUID), resolved by
  `tools/resolve_tierlist.py` exactly as the tier list is.
- `from` is `-` when the player held no committee tier before.
- `note` is free text and carries why.

Rejected: dates inline in the tier list. That file is hand-edited by the
committee and already carries alias syntax (`hevimies -> jussi8030`); adding
date syntax puts two things to get wrong on one line. The cost of two files is
drift, closed by a validation check (decision 6).

Performance played no part: the as-of lookup adds 5 ms to a 6,400-match scan
that takes 2,600 ms, and the file is parsed once at load either way.

### 2. Resolution is as-of the match date

`TierIndex.resolve(player_id, channel_id, on_date=None)`.

The tier in force at date D is the `from` of the earliest change dated after D;
if no change is dated after D, the current tier stands. A `from` of `-` falls
through to the normal holdings-then-imputation path, so a player who was
untiered then is correctly counted as a guess then — which also makes the
guessed-tier alarm read higher on older windows, as it should.

`on_date=None` keeps today's behaviour exactly, and an empty log makes every
as-of lookup identical to the current one. **The feature ships inert.** The
first commit that changes any output is the first real decision logged.

### 3. The headline scores every match at its as-of tier; the recommendation
comes from the current era

Scoring everything as-of uses the whole sample and stops rewriting the past. But
the headline then mixes eras. Take the simulated case: a player reads CLEARLY
OVER off 336 E-era games while now holding S, and `recommend()` — which takes the
current tier — would print `NO HIGHER TIER: already S, and beating it`. True of
the E evidence, actively misleading about S.

So the recommendation is computed from the **current era only**, the matches
since the last change. When the tier never changed, that is the whole window and
nothing differs from today.

An era table sits under the headline:

    Tier era          Games   Expected   Actual   Diff   Verdict
    E  ..2026-10-04     336      115.4      138  +22.6   CLEARLY OVER
    S  2026-10-04..      12        7.9        8   +0.1   ON TIER

This is the payoff: *"we moved him to S in October; after 12 games, is he ON
TIER?"* is a question the tool cannot answer today.

A current era below `ONE_TIER_GAMES` (250) gets an explicit "too few games to
judge S yet" line rather than a quiet ON TIER.

### 4. The model refits on as-of tiers

`match_to_sample` resolves each training match at its own date. The distortion
is near zero today and grows with every logged decision; leaving it would have
the model and the reports quietly disagree about who held what.

This changes `coefficients.json`. Before/after metrics go in the commit message,
per the `conventional-commits` skill.

### 5. Scan mirrors the report

Rows are scored at as-of tiers, the verdict uses current-era matches, and a
player whose tier changed inside the window gets a `caution`: `tier changed
2026-10-04; 12 games at S`. No new column — the existing caution mechanism
carries it.

### 6. Validation closes the two-file gap

`tools/check_tier_history.py` fails when:

- a player **who has log entries** has a last `to` disagreeing with the current
  tier list (drift),
- one player's dates are out of order or duplicated,
- a chain does not join up: an entry leaves tier A but the next starts from B,
- a date is unparseable, or a `player` token does not resolve.

It deliberately does **not** require every listed player to have a log entry.
The log starts empty and most players will never appear in it; demanding an
entry per player would fail on all 140 on day one and be silenced immediately.

Run in CI alongside `tools/check_fit.py`.

### 7. History starts at the first logged decision

No bootstrap, and the log ships empty. It means exactly one thing: the committee
changed its mind on this date. Nothing is written to it as part of building the
feature — the first entry is whatever the committee actually decides, whenever
that happens. The cost is thin data at the start, and that cost only grows if we
wait.

## Out of scope

- Per-channel history. The log covers the committee tier, which is what `scan`
  uses and what dominates reports. API holdings stay current-only.
- As-of `bands` and `utro`. Imputation keeps using current values; making those
  historical is a much larger change for a much smaller gain.
- Backfilling decisions made before today.

## Known limitation to state in the README

History only exists from the first logged change. Everything before the first
entry for a player resolves to their earliest recorded `from`, which for a player
with no entries at all is simply their tier today — identical to current
behaviour. This is honest, and it is the argument for having the log in place
before the next decision rather than after the next twenty.
