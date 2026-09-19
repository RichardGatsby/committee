---
name: conventional-commits
description: Use before every git commit in this repo - Conventional Commits 1.0.0 format, the types and scopes this project uses, and what a model refit or a tier-list change must record
---

# Conventional Commits

Format, from the [Conventional Commits 1.0.0
spec](https://www.conventionalcommits.org/en/v1.0.0/):

    <type>(<optional scope>): <description>

    <optional body>

    <optional footer>

Rules the spec fixes and this repo does not bend:

- Type is lowercase, followed by an optional scope in parentheses, then `: `.
- Description is imperative mood, lowercase, **no trailing full stop**:
  "add the scan command", not "Added the scan command." or "adds scanning".
- Subject line stays under 72 characters.
- Blank line before the body. Body wraps at 72.
- A breaking change gets `!` before the colon **and** a `BREAKING CHANGE:`
  footer explaining what a user must now do differently.

## Types

| type | for |
|---|---|
| `feat` | a new capability a user of the CLI can reach |
| `fix` | wrong output, a crash, a bug in scoring or parsing |
| `refactor` | same behaviour, different structure |
| `test` | tests or fixtures only |
| `docs` | README, CLAUDE.md, skills, docs/ |
| `chore` | tooling, .gitignore, housekeeping |
| `perf` | measurably faster, with the measurement in the body |
| `data` | the committee tier list, overrides, or a refit of `coefficients.json` |

`data` is local to this project. Model and tier-list state is committed, so a
change to it is neither a feature nor a fix, and burying a refit under `chore`
hides the thing most worth reviewing.

## Scopes

Optional. Use the module or subsystem: `model`, `report`, `scan`, `render`,
`tiers`, `cache`, `api`, `cli`, `tierlist`, `fixtures`. Leave it off when the
change is genuinely repo-wide.

## When the body is mandatory

**Any change to `coefficients.json`.** Record the before and after so the next
person can see whether the model got better or worse:

    data(model): refit after resolving seven tier-list names

    Thomas=toxiN, unbiased moderator=r4pZ, chuCk=czkk_,
    Retiredius=Swanidius, FATiHHOT=FiREBALL, plus ToMfu and poshtat
    pinned by UUID. 140 of 155 names now resolve, up from 133.

    accuracy 0.6393 (was 0.6393), brier 0.2204 (was 0.2204),
    log loss 0.6304 (was 0.6304), scale 0.4385 (was 0.3525)

**Any change to a player's tier**, naming who decided and on what basis. These
are committee decisions and the log is the record of them.

**Any behaviour change that moves a published verdict.** Say which verdict moved
and by how much. A silent change to the scoring path is the one thing here that
can embarrass someone in public.

**Anything non-obvious.** The subject says what; the body says why the obvious
alternative was rejected.

## Examples from this repo

    feat(scan): rank every tiered player by mis-tiering
    fix(dataset): fall back to the scoreline when winner is unset
    fix(cache): give each writer its own temp file
    test(fixtures): fail the build if a gather password reappears
    docs: state the tiering decision outright
    data(tierlist): tier treyzz as B
    refactor(report): derive odds from the row instead of storing them

Bad, and why:

    Resolve seven more committee tier-list names     -- no type
    fix: bug                                          -- says nothing
    feat: Added new scanning feature.                 -- tense, caps, full stop
    chore: refit                                      -- wrong type, no metrics
    wip                                               -- not a commit

## Before committing

1. `python3 -m pytest` is green. A pipeline into `tail` returns `tail`'s exit
   status, so `pytest | tail && git commit` will happily commit a red suite.
   Run them as separate commands.
2. `git diff --staged` — read what you are actually committing. Check no token,
   password, IP or personal email is in it.
3. One logical change per commit. A refit and a feature are two commits.
4. Attribution footer, per the session's configured trailer.
