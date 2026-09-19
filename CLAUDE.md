# committee

Evidence generator for ET:Legacy 3v3 tiering. Given a player, it
reconstructs what each recent match's tier composition predicted, compares that
to the result, and states whether the tier they hold should change.

Read `README.md` for what the tool does and how to run it. This file covers how
to work on it.

## Non-negotiables

- **Python 3.9, standard library only.** No numpy, no requests, no pandas. The
  tool runs on whatever machine is to hand; a pip install is a reason
  not to run it. Type hints use `typing.Dict` / `typing.List`, not the 3.10+
  builtin generics.
- **TDD.** Test first, watch it fail, then implement. See the `code-quality`
  skill.
- **No unit test touches the network.** Fixtures in `tests/fixtures/` are
  recorded responses. `tests/test_integration.py` is the only exception and is
  skipped unless `GIBHUB_INTEGRATION=1`.
- **Conventional commits.** See the `conventional-commits` skill.
- **Prose is for people, not for a model.** See the `unslop` skill.

## Shape of the code

One direction of dependency: I/O at the edges, pure functions in the middle.

    cli.py          argument parsing, output selection
    build.py        fetch + assemble a Bundle          -- network
    fetch.py        match iteration over the API       -- network
    api.py          HTTP, retries, pagination          -- network, ONLY module
    cache.py        finished matches on disk           -- filesystem
    bundle.py       coefficients.json (de)serialisation  -- filesystem
    dataset.py      matches -> training samples
    categories.py   which kind of game is this
    tiers.py        override -> exact -> cross-channel -> imputed
    model.py        logistic scoring                   -- pure
    report.py       one player's verdict               -- pure
    scan.py         every player's verdict             -- pure
    render.py       markdown / CSV / JSON              -- pure

`api.py` is the only module that opens a socket. If you find yourself importing
`urllib` anywhere else, the design has gone wrong. `model.py`, `report.py`,
`scan.py` and `render.py` must stay importable with no network, no filesystem
and no clock.

## Domain facts that trip people up

- **The tier order is S > E > A > B > C > D.** E is the second *strongest* tier,
  not the weakest. Never sort tiers alphabetically, never assume "the tier above
  A" is S. Read neighbours off `TIER_POINTS` or off the fitted bands.
- **Tier points are fixed** (S 5, E 4, A 3, B 2, C 1, D 0). The
  only fitted parameter is the scale: one point of roster advantage is worth
  ~0.44 log-odds. Changing the points is a tiering decision, not a modelling
  one.
- **There is no intercept, by design.** Two mirrored rosters must score exactly
  0.5. A test asserts this; do not "improve" the fit by adding a bias term
  without raising it as a decision first.
- **Tiers are dated, from `data/tier-changes.tsv` forward.** Every match is
  scored against the tier in force on the day it was played, so a promotion no
  longer rewrites the past. Anything before a player's first logged change
  resolves to their current tier, which for most players is every match there
  is — history only exists from the moment it starts being recorded.
  `TierIndex.resolve(player, channel, on_date)` is the whole mechanism; pass the
  match date or the answer is "today".
- **The API's betting odds are unusable** — a pari-mutuel joke-money pool, null
  in every 3v3 match sampled. Do not wire them in.
- **Imputation is the main source of false signal.** A player with no assigned
  tier gets one from their shrunken UTRO, capped at A by measured strength.
  `report.guess_warning` raises this above the headline at 20% and 40% of tier
  inputs guessed; the footer carries the exact counts either way.
- **`GET /api/matches/{id}` has no `teams` block.** Rosters come from the rounds,
  top three by playtime.
- **The API 403s without a User-Agent** and caps `pageSize` at 100.

## Running things

    python3 -m pytest                                    # must be green
    GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py
    python3 tools/check_fit.py                           # after any refit

Refitting rewrites `coefficients.json`, which is committed. Do it deliberately,
in its own commit, and paste the metrics into the message:

    python3 tools/resolve_tierlist.py data/tierlist-events-3v3.txt overrides.txt
    python3 -m gibhub.cli fit --refit \
        --tier-channel Events --points --impute-max A --overrides overrides.txt

A refit that moves accuracy, Brier or log loss the wrong way is a finding to
report, not a number to bury.

## Secrets

The repo is public. Recorded fixtures are scrubbed of `ip` and `pw` fields and a
guard test fails if either reappears. No token belongs in any committed file,
including in example commands. The public endpoints this tool actually calls
need no authentication at all.

## Known limitations worth repeating to anyone reading the output

- The approach is partly circular by design: it asks whether a record is
  consistent with the tier held, not what tier a player deserves in the absolute.
- The alpha side wins 52.5% of matches and the model cannot express that.
- A row with few games and a large effect reads as `KEEP`, which means "too few
  games to call", not "correctly tiered".
- 15 of 155 names on the tier list still have no account mapped, mostly C and D.
