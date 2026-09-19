---
name: code-quality
description: Use when writing, changing or reviewing any Python in this repo - enforces test-first development, a functional core with I/O at the edges, and the stdlib-only Python 3.9 conventions the codebase already follows
---

# Code Quality

Two rules carry most of the weight: **the test comes first**, and **the logic is
pure**. Everything below is detail on those.

## TDD, without the escape hatches

One cycle per behaviour, not per feature:

1. Write one failing test that names the behaviour.
2. Run it. **Read the failure.** A test that fails for the wrong reason (import
   error, typo in the fixture) has told you nothing.
3. Write the smallest implementation that passes.
4. Run the whole suite, not just the new test.
5. Commit.

Rationalisations to refuse:

| Thought | Reality |
|---|---|
| "I'll add tests after, it's quicker" | You will write tests that pass against what you built, not against what was asked. |
| "It's too small to test" | Then the test is small. `sigmoid(0.0) == 0.5` is one line and it caught a real bug. |
| "It's just I/O, can't test it" | Inject the dependency. `Client` takes an `opener` and a `sleep` precisely so tests pass fakes. |
| "The test needs the network" | Record a fixture with `tools/record_fixtures.py`. No unit test hits the network. |
| "I'll delete the test, the behaviour changed" | Change the assertion and say so in the commit. Deleting coverage is a decision, not a cleanup. |

When a test fails after a change, the first question is always *is the test
wrong, or is the code wrong?* Both happen here. `sigmoid(50.0) < 1.0` failed
because the test was wrong — it rounds to exactly 1.0 in float64. The
monotonicity assertion on tier coefficients failed because the *assumption* was
wrong: E really is the second strongest tier. Investigate before you edit.

### What a good test looks like here

- Named for the behaviour: `test_mirrored_rosters_give_a_zero_vector`, not
  `test_feature_vector_2`.
- One behaviour per test. If the name needs "and" to join two *assertions*,
  split it; "and" joining two nouns (`..._excludes_both_s_and_e`) is just
  English.
- Asserts on values, not on "it didn't raise".
- Exercises the boundary: empty input, a single sample, an unknown tier, a
  match with no winner.
- Uses real recorded data for parsing, hand-built data for logic. Parsing tests
  that invent their own JSON drift away from what the API actually returns.
- Pins the things that must never change: no intercept, exactly 0.5 on mirrored
  rosters, only finished matches cached.

## Functional core, imperative shell

`model.py`, `report.py`, `scan.py`, `render.py`, `categories.py`, `tiers.py` and
`dataset.py` are pure. Keep them that way.

Pure means: same inputs, same outputs, no sockets, no disk, no `datetime.now()`,
no logging, no mutation of anything the caller owns.

    # no
    def build_report(player):
        matches = client.get("/matches", {"player": player})   # I/O in the core
        cutoff = datetime.now() - timedelta(days=120)          # hidden clock

    # yes
    def build_report(matches, index, coefficients, scale, *, window):
        ...                                                     # everything given

The caller does the fetching and passes the clock in. This is why the whole
suite runs offline in under a second, and why the same command with the same
cache produces byte-identical output.

Practical consequences:

- **Return new values, do not mutate arguments.** Build a new dict; do not
  `.update()` the one you were handed.
- **No module-level mutable state.** Module constants are fine and must be
  uppercase tuples or frozen mappings, never lists you append to.
- **Derive, do not store.** `ScanRow.odds` and `.caution` are properties
  computed from the row's own fields. Two fields that can disagree will.
- **Prefer comprehensions and generators to accumulator loops** when the result
  is a transformation. Keep the loop when it is genuinely a fold with early
  exit — readable beats clever.
- **Total functions where you can.** Return `Optional` and let the caller
  decide, rather than raising from deep inside a scoring loop.
- **`@dataclasses.dataclass` for records**, with defaults that make an empty
  instance meaningful. `frozen=True` unless something genuinely needs to change.

I/O lives in `api.py`, `cache.py`, `build.py`, `fetch.py`, `cli.py` and
`bundle.py`. That is the whole list. Adding a seventh is a design change worth
stating out loud.

`bundle.py` is the awkward one: its `Bundle` record and `index()` are pure, and
only `save()` and `load()` touch disk. Keep the split that way round.

## Python conventions in this repo

- **Python 3.9, standard library only.** No third-party runtime dependency, ever.
  pytest is a dev dependency and nothing in `gibhub/` may import it.
- **Type hints on every public function in the pure core.** `typing.Dict`,
  `typing.Optional`, `typing.Sequence` — not `dict[str, float]` or `str | None`,
  which 3.9 rejects at runtime in annotations that get evaluated. The shell is
  looser by deliberate exception: `cli.py` passes `argparse.Namespace` around and
  annotating every `args` adds noise without catching anything.
- **Accept the widest type, return the narrowest.** Parameters take `Mapping` /
  `Sequence` / `Iterable`; returns are concrete `Dict` / `List`.
- **Keyword-only for anything optional.** `def fit(samples, *, iterations=2000)`.
  A call site with three bare numbers in it is unreadable and unsafe to reorder.
- **Module docstring says what the module is for and what it may not do:**
  `"""Pure scoring model. No I/O, no API knowledge."""`
- **Comments explain why, never what.** The comment on `TIER_POINTS` earns its
  place because the ordering looks like a typo and is not. A comment restating
  the line below it is noise.
- **`_leading_underscore` for module-private helpers.** `_median`, `_EPSILON`.
- **Raise `ValueError` with the offending value in the message:**
  `raise ValueError("unknown tier %r" % tier)`. `%r` shows the quotes, which is
  how you spot trailing whitespace.
- **Never catch bare `except:`.** Catch the exception you expect and let the
  rest surface.
- **Determinism is a feature.** Fixed iteration counts, zero initialisation,
  sorted iteration over dicts wherever output order is user-visible. Two runs
  must produce identical bytes.
- **`tempfile.mkstemp` for any file write**, then rename. A shared `.tmp`
  filename already caused one concurrency bug here.
- **Avoid negative zero in output.** `value or 0.0` before formatting.

## Size and shape

Files are 60-400 lines. When one passes roughly 400, look for the seam — it
usually has two responsibilities by then. Split by responsibility, not by layer.

A function that needs a scroll to read is doing several things. `build_report`
is long because it is a sequence of clearly named steps; if a step needs a
comment to explain what it does, it wants to be a function with that name.

## Before you say it is done

    python3 -m pytest

Green, every time, with no new skips. Then read your own diff as if someone else
wrote it. The question is not "does it work" but "will the next person
misunderstand this". If the answer is maybe, the fix is usually a better name.

## References

The functional-core / imperative-shell split is Gary Bernhardt's "Boundaries"
talk: <https://www.destroyallsoftware.com/talks/boundaries>
