# Tier History Implementation Plan

**Goal:** Score every match against the tiers in force on the day it was played,
so a promotion stops rewriting the past.

**Architecture:** An append-only `data/tier-changes.tsv` is resolved to UUIDs
alongside the tier list, stored in the bundle, and consulted by a new optional
`on_date` argument to `TierIndex.resolve`. Everything downstream threads the
match date through. With an empty log every lookup is identical to today's, so
the feature ships inert.

**Tech stack:** Python 3.9 stdlib, pytest. No new dependencies.

Design: `docs/superpowers/specs/2026-09-19-tier-history-design.md`

---

## File structure

| file | responsibility |
| --- | --- |
| `gibhub/history.py` | **new.** Parse and query the change log. Pure. |
| `gibhub/tiers.py` | `TierIndex.resolve` gains `on_date`. |
| `gibhub/bundle.py` | carry `history` through save/load. |
| `gibhub/build.py` | put history into the bundle; refit as-of. |
| `gibhub/dataset.py` | resolve training matches at their own date. |
| `gibhub/report.py` | per-row tier, eras, current-era recommendation. |
| `gibhub/render.py` | the era table. |
| `gibhub/scan.py` | as-of scoring, current-era verdict, change caution. |
| `gibhub/cli.py` | `--tier-history` flag. |
| `tools/resolve_tierlist.py` | resolve log player tokens to UUIDs. |
| `tools/check_tier_history.py` | **new.** Drift and format validation. |
| `data/tier-changes.tsv` | **new.** The log itself. |

---

## Task 1: Parse the change log

**Files:** Create `gibhub/history.py`, `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history.py
import pytest

from gibhub.history import TierChange, parse_changes

SAMPLE = """\
# date\tplayer\tfrom\tto\tnote
2026-09-19\tjussi8030\tE\tS\t+22.58 over 336 games
2026-10-01\ttreyzz\t-\tB\tfirst tiering
"""


def test_parses_one_change_per_line():
    changes = parse_changes(SAMPLE)
    assert changes == [
        TierChange("2026-09-19", "jussi8030", "E", "S", "+22.58 over 336 games"),
        TierChange("2026-10-01", "treyzz", None, "B", "first tiering"),
    ]


def test_a_dash_means_previously_untiered():
    assert parse_changes(SAMPLE)[1].previous is None


def test_comments_and_blank_lines_are_skipped():
    assert parse_changes("# note\n\n\n") == []


def test_a_missing_column_is_rejected():
    with pytest.raises(ValueError, match="line 1"):
        parse_changes("2026-09-19\tjussi8030\tE\n")


def test_an_unparseable_date_is_rejected():
    with pytest.raises(ValueError, match="19-09-2026"):
        parse_changes("19-09-2026\tjussi8030\tE\tS\tx\n")


def test_an_unknown_tier_is_rejected():
    with pytest.raises(ValueError, match="'Z'"):
        parse_changes("2026-09-19\tjussi8030\tE\tZ\tx\n")


def test_the_note_may_be_empty():
    assert parse_changes("2026-09-19\tp\tE\tS\t\n")[0].note == ""


def test_changes_come_back_sorted_by_date():
    text = "2026-10-01\tp\tA\tS\tb\n2026-09-19\tp\tE\tA\ta\n"
    assert [c.date for c in parse_changes(text)] == ["2026-09-19", "2026-10-01"]
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'gibhub.history'`

- [ ] **Step 3: Implement**

```python
# gibhub/history.py
"""The tier change log. Pure: parsing and lookup, no I/O."""

import bisect
import dataclasses
import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import TIER_POINTS

UNTIERED = "-"


@dataclasses.dataclass(frozen=True)
class TierChange:
    """One tier decision, on one date, about one player."""

    date: str
    player: str
    previous: Optional[str]   # None when the player held no assigned tier
    tier: str
    note: str = ""


def _tier(raw: str, line_number: int) -> Optional[str]:
    if raw == UNTIERED:
        return None
    if raw not in TIER_POINTS:
        raise ValueError("line %d: unknown tier %r" % (line_number, raw))
    return raw


def parse_changes(text: str) -> List[TierChange]:
    """Read the log. Blank lines and `#` comments are ignored."""
    changes = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) < 4:
            raise ValueError(
                "line %d: expected date, player, from, to, note; got %r" % (number, raw)
            )
        date, player, previous, tier = (f.strip() for f in fields[:4])
        note = fields[4].strip() if len(fields) > 4 else ""
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ValueError("line %d: bad date %r, want YYYY-MM-DD" % (number, date))
        changes.append(
            TierChange(date, player, _tier(previous, number), _tier(tier, number), note)
        )
    # Stable sort: two decisions on one date keep the order they were written.
    return sorted(changes, key=lambda change: change.date)
```

- [ ] **Step 4: Run and watch them pass**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add gibhub/history.py tests/test_history.py
git commit -m "feat(history): parse the assigned tier change log"
```

---

## Task 2: Look up the tier in force on a date

**Files:** Modify `gibhub/history.py`, `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_history.py
from gibhub.history import TierHistory


def _history():
    return TierHistory.build([
        TierChange("2026-03-01", "p1", "B", "A", ""),
        TierChange("2026-09-19", "p1", "A", "S", ""),
        TierChange("2026-05-01", "p2", None, "C", ""),
    ])


def test_a_player_with_no_changes_has_no_opinion():
    assert _history().tier_at("stranger", "2026-06-01", current="B") == "B"


def test_before_every_change_gives_the_earliest_previous_tier():
    assert _history().tier_at("p1", "2026-01-01", current="S") == "B"


def test_between_two_changes_gives_the_middle_tier():
    assert _history().tier_at("p1", "2026-06-01", current="S") == "A"


def test_on_the_day_of_a_change_the_new_tier_applies():
    assert _history().tier_at("p1", "2026-09-19", current="S") == "S"


def test_after_the_last_change_gives_the_current_tier():
    assert _history().tier_at("p1", "2026-12-01", current="S") == "S"


def test_before_a_first_tiering_there_is_no_tier():
    assert _history().tier_at("p2", "2026-01-01", current="C") is None


def test_no_date_means_the_current_tier():
    assert _history().tier_at("p1", None, current="S") == "S"


def test_eras_lists_each_span_the_player_held():
    assert _history().eras("p1", current="S") == [
        (None, "2026-03-01", "B"),
        ("2026-03-01", "2026-09-19", "A"),
        ("2026-09-19", None, "S"),
    ]


def test_eras_of_an_unchanged_player_is_one_open_span():
    assert _history().eras("stranger", current="B") == [(None, None, "B")]


def test_an_empty_history_never_changes_an_answer():
    empty = TierHistory.build([])
    assert empty.tier_at("p1", "2020-01-01", current="S") == "S"
    assert empty.eras("p1", current="S") == [(None, None, "S")]
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: FAIL, `ImportError: cannot import name 'TierHistory'`

- [ ] **Step 3: Implement**

```python
# append to gibhub/history.py
Era = Tuple[Optional[str], Optional[str], Optional[str]]  # (from_date, to_date, tier)


@dataclasses.dataclass(frozen=True)
class TierHistory:
    """Per-player change lists, sorted by date, ready for bisect."""

    dates: Mapping[str, Sequence[str]]
    previous: Mapping[str, Sequence[Optional[str]]]

    @classmethod
    def build(cls, changes: Sequence[TierChange]) -> "TierHistory":
        dates: Dict[str, List[str]] = {}
        previous: Dict[str, List[Optional[str]]] = {}
        for change in sorted(changes, key=lambda c: c.date):
            dates.setdefault(change.player, []).append(change.date)
            previous.setdefault(change.player, []).append(change.previous)
        return cls(dates=dates, previous=previous)

    def tier_at(
        self, player: str, on_date: Optional[str], *, current: Optional[str]
    ) -> Optional[str]:
        """The assigned tier in force for `player` on `on_date`.

        The tier that day is the `from` of the earliest change dated after it;
        with no later change, the current tier stands. A change dated exactly
        on_date has already taken effect.
        """
        if on_date is None:
            return current
        dates = self.dates.get(player)
        if not dates:
            return current
        position = bisect.bisect_right(dates, on_date)
        if position >= len(dates):
            return current
        return self.previous[player][position]

    def eras(self, player: str, *, current: Optional[str]) -> List[Era]:
        """Every span the player held a tier, oldest first, as
        (start, end, tier). Open-ended spans use None."""
        dates = self.dates.get(player)
        if not dates:
            return [(None, None, current)]
        spans: List[Era] = []
        start: Optional[str] = None
        for index, date in enumerate(dates):
            spans.append((start, date, self.previous[player][index]))
            start = date
        spans.append((start, None, current))
        return spans
```

- [ ] **Step 4: Run and watch them pass**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add gibhub/history.py tests/test_history.py
git commit -m "feat(history): resolve the tier in force on a given date"
```

---

## Task 3: Teach TierIndex about dates

**Files:** Modify `gibhub/tiers.py`, `tests/test_tiers.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_tiers.py
from gibhub.history import TierChange, TierHistory


def _dated_index():
    return TierIndex(
        holdings={}, bands={"S": 1.3, "A": 1.05, "B": 1.0}, utro={},
        overrides={"p1": "S"},
        history=TierHistory.build([TierChange("2026-09-19", "p1", "E", "S", "")]),
    )


def test_without_a_date_the_current_override_wins():
    assert _dated_index().resolve("p1", "c1").tier == "S"


def test_a_match_before_the_change_sees_the_old_tier():
    assert _dated_index().resolve("p1", "c1", on_date="2026-05-01").tier == "E"


def test_a_match_on_the_change_date_sees_the_new_tier():
    assert _dated_index().resolve("p1", "c1", on_date="2026-09-19").tier == "S"


def test_a_historical_tier_is_still_a_real_decision():
    assert _dated_index().resolve("p1", "c1", on_date="2026-05-01").source == OVERRIDE


def test_before_a_first_tiering_the_player_falls_back_to_imputation():
    index = TierIndex(
        holdings={}, bands={"A": 1.05, "B": 1.0}, utro={"p2": 1.0},
        overrides={"p2": "A"},
        history=TierHistory.build([TierChange("2026-09-19", "p2", None, "A", "")]),
    )
    resolved = index.resolve("p2", "c1", on_date="2026-01-01")
    assert resolved.source == IMPUTED
    assert resolved.tier == "B"


def test_resolve_all_threads_the_date_through():
    tiers = [r.tier for r in _dated_index().resolve_all(["p1"], "c1",
                                                        on_date="2026-05-01")]
    assert tiers == ["E"]


def test_an_index_with_no_history_behaves_exactly_as_before():
    index = TierIndex(holdings={}, bands={"A": 1.05}, utro={}, overrides={"p1": "A"})
    assert index.resolve("p1", "c1", on_date="1999-01-01").tier == "A"
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_tiers.py -v`
Expected: FAIL, `TypeError: __init__() got an unexpected keyword argument 'history'`

- [ ] **Step 3: Implement**

In `gibhub/tiers.py`, add the import and the field:

```python
from .history import TierHistory
```

```python
    overrides: Mapping[str, str] = dataclasses.field(default_factory=dict)
    # Dated tier decisions. Empty means every lookup is as it is today.
    history: TierHistory = dataclasses.field(
        default_factory=lambda: TierHistory.build([])
    )
```

Replace `resolve` and `resolve_all`:

```python
    def resolve(
        self, player_id: str, channel_id: Optional[str], on_date: Optional[str] = None
    ) -> ResolvedTier:
        override = self.overrides.get(player_id)
        if on_date is not None:
            override = self.history.tier_at(player_id, on_date, current=override)
        if override:
            return ResolvedTier(override, OVERRIDE)

        held = self.holdings.get(player_id) or ()

        for holding in held:
            if holding.channel_id == channel_id:
                return ResolvedTier(holding.tier, EXACT)

        if held:
            newest = max(held, key=lambda holding: holding.updated_at)
            return ResolvedTier(newest.tier, CROSS_CHANNEL)

        return ResolvedTier(
            nearest_tier(self.bands, self.utro.get(player_id), self.impute_max), IMPUTED
        )

    def resolve_all(
        self,
        player_ids: Iterable[str],
        channel_id: Optional[str],
        on_date: Optional[str] = None,
    ) -> List[ResolvedTier]:
        return [self.resolve(pid, channel_id, on_date) for pid in player_ids]
```

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m pytest`
Expected: all pass. Every existing call omits `on_date`, so nothing moves.

- [ ] **Step 5: Commit**

```bash
git add gibhub/tiers.py tests/test_tiers.py
git commit -m "feat(tiers): resolve a tier as of a match date"
```

---

## Task 4: Carry history in the bundle

**Files:** Modify `gibhub/bundle.py`, `tests/test_bundle.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_bundle.py
from gibhub.history import TierChange


def test_history_round_trips(tmp_path):
    path = tmp_path / "coefficients.json"
    bundle = dataclasses.replace(
        _bundle(), history=[TierChange("2026-09-19", "p1", "E", "S", "why")]
    )
    save(bundle, str(path))
    assert load(str(path)).history == bundle.history


def test_a_bundle_without_history_loads_as_empty(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), str(path))
    payload = json.loads(path.read_text())
    del payload["history"]
    path.write_text(json.dumps(payload))
    assert load(str(path)).history == []


def test_the_index_carries_the_history(tmp_path):
    bundle = dataclasses.replace(
        _bundle(), overrides={"p1": "S"},
        history=[TierChange("2026-09-19", "p1", "E", "S", "")]
    )
    assert bundle.index().resolve("p1", "x", on_date="2026-01-01").tier == "E"
```

Add `import dataclasses` to the top of `tests/test_bundle.py`.

- [ ] **Step 2: Run and watch it fail**

Run: `python3 -m pytest tests/test_bundle.py -v`
Expected: FAIL, `TypeError: __init__() got an unexpected keyword argument 'history'`

- [ ] **Step 3: Implement**

In `gibhub/bundle.py`, import and add the field after `overrides`:

```python
from .history import TierChange, TierHistory
```

```python
    # Dated tier decisions, oldest first.
    history: List[TierChange] = dataclasses.field(default_factory=list)
```

Pass it to the index:

```python
    def index(self) -> TierIndex:
        return TierIndex(holdings=self.holdings, bands=self.bands, utro=self.utro,
                         impute_max=self.impute_max, overrides=self.overrides,
                         history=TierHistory.build(self.history))
```

In `save()`, add to the payload dict:

```python
        "history": [dataclasses.asdict(change) for change in bundle.history],
```

In `load()`, add to the `Bundle(...)` call:

```python
        history=[TierChange(**entry) for entry in payload.get("history") or []],
```

- [ ] **Step 4: Run and watch it pass**

Run: `python3 -m pytest tests/test_bundle.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gibhub/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): persist the tier change log"
```

---

## Task 5: Resolve player tokens in the log

**Files:** Modify `tools/resolve_tierlist.py`, `gibhub/cli.py`, `tests/test_cli.py`
**Create:** `data/tier-changes.tsv`

- [ ] **Step 1: Create the empty log**

```bash
printf '# Tier decisions. Append-only, one per line.\n# date\\tplayer\\tfrom\\tto\\tnote   ("-" in from = previously untiered)\n' > data/tier-changes.tsv
```

- [ ] **Step 2: Write the failing test**

```python
# append to tests/test_cli.py
def test_load_history_resolves_and_sorts(tmp_path):
    from gibhub.cli import load_history

    path = tmp_path / "tier-changes.tsv"
    path.write_text(
        "# comment\n"
        "2026-10-01\tuuid-2\tA\tS\tlater\n"
        "2026-09-19\tuuid-1\tE\tA\tearlier\n"
    )
    changes = load_history(str(path))
    assert [c.date for c in changes] == ["2026-09-19", "2026-10-01"]
    assert changes[0].player == "uuid-1"


def test_no_history_file_means_no_history():
    from gibhub.cli import load_history

    assert load_history(None) == []
```

- [ ] **Step 3: Run and watch it fail**

Run: `python3 -m pytest tests/test_cli.py -k history -v`
Expected: FAIL, `ImportError: cannot import name 'load_history'`

- [ ] **Step 4: Implement**

In `gibhub/cli.py`, next to `load_overrides`:

```python
def load_history(path: Optional[str]) -> List[TierChange]:
    """Read the resolved change log. Missing file means no history."""
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return parse_changes(handle.read())
```

Import `from .history import TierChange, parse_changes`.

Add the flag to the `fit` subparser, beside `--overrides`:

```python
    fit_parser.add_argument(
        "--tier-history", dest="tier_history", default="tier-history.txt",
        help="resolved tier change log (default: tier-history.txt)")
```

In `cmd_fit`, pass `history=load_history(args.tier_history)` into `build_bundle`.

- [ ] **Step 5: Teach the resolver to emit it**

In `tools/resolve_tierlist.py`, after writing `overrides.txt`, add a third
positional argument `changes_in` and a fourth `changes_out`. For each log line,
resolve the `player` token through the same `candidates()` / `related()` path
the tier list uses, and write `date\tuuid\tfrom\tto\tnote  # nick`. A token that
does not resolve is a hard error, not a warning: a silently dropped decision is
worse than none.

- [ ] **Step 6: Run the suite**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add tools/resolve_tierlist.py gibhub/cli.py tests/test_cli.py data/tier-changes.tsv
git commit -m "feat(tierlist): resolve the change log alongside the tier list"
```

---

## Task 6: Train the model on as-of tiers

**Files:** Modify `gibhub/dataset.py`, `gibhub/build.py`, `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_dataset.py
from gibhub.history import TierChange, TierHistory


def test_a_training_sample_uses_the_tiers_of_its_own_date():
    index = TierIndex(
        holdings={}, bands={"S": 1.3, "E": 1.2, "A": 1.05}, utro={},
        overrides={"a1": "S"},
        history=TierHistory.build([TierChange("2026-09-19", "a1", "A", "S", "")]),
    )
    old = dict(MATCH, start_time="2026-05-01T20:00:00+02:00")
    new = dict(MATCH, start_time="2026-09-20T20:00:00+02:00")
    assert match_to_sample(old, index).features != match_to_sample(new, index).features
```

- [ ] **Step 2: Run and watch it fail**

Run: `python3 -m pytest tests/test_dataset.py -k own_date -v`
Expected: FAIL, the two feature vectors are equal

- [ ] **Step 3: Implement**

In `match_to_sample`, replace the two resolve calls:

```python
    channel_id = match.get("channel_id")
    on_date = (match.get("start_time") or "")[:10] or None
    alpha_resolved = index.resolve_all(alpha, channel_id, on_date)
    beta_resolved = index.resolve_all(beta, channel_id, on_date)
```

In `build.py`, add `history=None` to `build_bundle`'s signature, build the index
with `history=TierHistory.build(history or [])`, and pass `history=list(history
or [])` into the returned `Bundle`.

- [ ] **Step 4: Run and watch it pass**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gibhub/dataset.py gibhub/build.py tests/test_dataset.py
git commit -m "feat(dataset): train each match against the tiers of its own date"
```

---

## Task 7: Eras in the player report

**Files:** Modify `gibhub/report.py`, `tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_report.py
from gibhub.history import TierChange, TierHistory


def _history_index():
    return TierIndex(
        holdings={}, bands={"S": 1.3, "E": 1.2, "A": 1.05, "D": 0.8},
        utro={}, overrides={"me": "S", "a2": "D", "a3": "D",
                            "b1": "D", "b2": "D", "b3": "D"},
        history=TierHistory.build([TierChange("2026-09-15", "me", "E", "S", "")]),
    )


def _dated(match_id, winner, when):
    return dict(_detail(match_id, winner, 1.2), start_time=when + "T20:00:00+02:00")


def test_rows_carry_the_tier_the_subject_held_that_day():
    report = build_report(
        PROFILE, SPIDER,
        [_dated("m1", "alpha", "2026-09-01"), _dated("m2", "alpha", "2026-09-20")],
        _history_index(), COEFFICIENTS, {})
    assert [row.own_tier for row in report.rows] == ["E", "S"]


def test_eras_split_the_window_at_the_change():
    report = build_report(
        PROFILE, SPIDER,
        [_dated("m1", "alpha", "2026-09-01"), _dated("m2", "alpha", "2026-09-20")],
        _history_index(), COEFFICIENTS, {})
    assert [(era.tier, era.games) for era in report.eras] == [("E", 1), ("S", 1)]


def test_an_unchanged_player_has_exactly_one_era():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.3)], _index(),
                          COEFFICIENTS, {})
    assert len(report.eras) == 1


def test_the_recommendation_comes_from_the_current_era_only():
    """Two losses at E, one win at S. The S era is ON TIER; the whole window
    is not. The recommendation must speak about S."""
    report = build_report(
        PROFILE, SPIDER,
        [_dated("m1", "beta", "2026-09-01"), _dated("m2", "beta", "2026-09-02"),
         _dated("m3", "alpha", "2026-09-20")],
        _history_index(), COEFFICIENTS, {})
    assert report.current_tier == "S"
    assert report.recommendation == recommend(report.eras[-1].label, "S")


def test_a_thin_current_era_is_flagged_rather_than_called_on_tier():
    report = build_report(
        PROFILE, SPIDER, [_dated("m1", "alpha", "2026-09-20")],
        _history_index(), COEFFICIENTS, {})
    assert report.current_era_is_thin is True
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_report.py -k era -v`
Expected: FAIL, `TypeError: __init__() got an unexpected keyword argument 'own_tier'`

- [ ] **Step 3: Implement**

Add to `MatchRow`:

```python
    # The tier the subject held on the day of this match.
    own_tier: Optional[str] = None
```

Add an era record above `PlayerReport`:

```python
@dataclasses.dataclass(frozen=True)
class TierEra:
    """One span the subject held a tier, and how they did in it."""

    tier: Optional[str]
    start: Optional[str]
    end: Optional[str]
    games: int
    expected: float
    actual: int
    luck: float
    label: str
```

Add to `PlayerReport`, after `players_guessed`:

```python
    eras: List[TierEra] = dataclasses.field(default_factory=list)
    # True when the current era is too short to judge the tier it tests.
    current_era_is_thin: bool = False
```

In `build_report`, resolve with the match date and record the subject's own tier:

```python
        on_date = (match.get("start_time") or "")[:10] or None
        alpha_resolved = index.resolve_all(alpha, channel_id, on_date)
        beta_resolved = index.resolve_all(beta, channel_id, on_date)
        own_tier = (alpha_resolved if side == "alpha" else beta_resolved)[
            (alpha if side == "alpha" else beta).index(player_id)
        ].tier
```

pass `own_tier=own_tier` into the `MatchRow(...)`, then after the loop:

```python
    eras = _eras(rows, index.history, player_id, current_tier)
    current = eras[-1] if eras else None
    thin = bool(current and current.games < ONE_TIER_GAMES and len(eras) > 1)
    label = current.label if (current and len(eras) > 1) else classify(delta, luck)
```

and use `label` for `recommendation=recommend(label, current_tier)`.

`_eras` groups decided rows by `own_tier` in date order and scores each group
with the existing `luck_probability` and `classify`:

```python
def _eras(rows, history, player_id, current_tier) -> List[TierEra]:
    """Group the window's decided matches into the tier spans they fall in."""
    spans = history.eras(player_id, current=current_tier)
    out = []
    for start, end, tier in spans:
        inside = [r for r in rows if r.result in ("W", "L")
                  and (start is None or r.date >= start)
                  and (end is None or r.date < end)]
        if not inside and len(spans) > 1:
            continue
        probabilities = [r.expected for r in inside]
        actual = sum(1 for r in inside if r.result == "W")
        luck = luck_probability(probabilities, actual) if inside else 1.0
        out.append(TierEra(
            tier=tier, start=start, end=end, games=len(inside),
            expected=sum(probabilities), actual=actual, luck=luck,
            label=classify(actual - sum(probabilities), luck),
        ))
    return out
```

Import `ONE_TIER_GAMES` from `.scan` is circular — move that constant into
`report.py` and have `scan.py` import it from there.

- [ ] **Step 4: Run the suite**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gibhub/report.py gibhub/scan.py tests/test_report.py
git commit -m "feat(report): split a player's record into tier eras"
```

---

## Task 8: Render the era table

**Files:** Modify `gibhub/render.py`, `tests/test_render.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_render.py
from gibhub.report import TierEra

ERAS = [
    TierEra("E", None, "2026-09-19", 336, 115.42, 138, 0.0004, "CLEARLY OVER"),
    TierEra("S", "2026-09-19", None, 12, 7.9, 8, 0.5, "ON TIER"),
]


def test_the_era_table_appears_when_the_tier_changed():
    text = to_markdown(dataclasses.replace(REPORT, eras=ERAS))
    assert "Tier era" in text
    assert "..2026-09-19" in text
    assert "2026-09-19.." in text


def test_no_era_table_when_the_tier_never_changed():
    text = to_markdown(dataclasses.replace(REPORT, eras=ERAS[:1]))
    assert "Tier era" not in text


def test_a_thin_current_era_says_so():
    text = to_markdown(dataclasses.replace(
        REPORT, eras=ERAS, current_era_is_thin=True))
    assert "Too few games to judge S yet" in text


def test_the_era_table_sits_under_the_headline():
    text = to_markdown(dataclasses.replace(REPORT, eras=ERAS))
    assert text.index("**Expected") < text.index("Tier era")
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_render.py -k era -v`
Expected: FAIL, `"Tier era" not in text`

- [ ] **Step 3: Implement**

In `to_markdown`, after the `### → recommendation` line:

```python
        if len(report.eras) > 1:
            lines.append("")
            lines.append("**By tier held**")
            lines.extend(table(
                ["Tier era", "Games", "Expected wins", "Actual wins", "Difference",
                 "Verdict"],
                [["%-2s %s..%s" % (era.tier or "-", era.start or "", era.end or ""),
                  era.games, "%.1f" % era.expected, era.actual,
                  "%+.1f" % (era.actual - era.expected), era.label]
                 for era in report.eras],
                aligns=["<", ">", ">", ">", ">", "<"]))
            if report.current_era_is_thin:
                current = report.eras[-1]
                lines.append("")
                lines.append(
                    "_Too few games to judge %s yet: %d played, about %d needed "
                    "for a one-tier call._" % (current.tier, current.games,
                                               ONE_TIER_GAMES))
```

- [ ] **Step 4: Run and watch them pass**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gibhub/render.py tests/test_render.py
git commit -m "feat(render): show the record split by tier held"
```

---

## Task 9: Scan mirrors the report

**Files:** Modify `gibhub/scan.py`, `tests/test_scan.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_scan.py
from gibhub.history import TierChange, TierHistory


def _changed_index(overrides):
    return TierIndex(holdings={}, bands=BANDS, utro={}, overrides=overrides,
                     history=TierHistory.build(
                         [TierChange("2026-09-19", "x", "D", "S", "")]))


def _on(date):
    m = _match(["x", "y", "z"], ["q", "r", "s"], "alpha")
    m["start_time"] = date + "T20:00:00+02:00"
    return m


def test_a_scan_row_scores_each_match_at_its_own_date():
    index = _changed_index({p: "B" for p in SIX} | {"x": "S"})
    early = [_on("2026-01-%02d" % (i % 28 + 1)) for i in range(60)]
    late = [_on("2026-10-%02d" % (i % 28 + 1)) for i in range(60)]
    assert _row(scan(early, index, COEFFICIENTS, SCALE, min_games=50), "x").expected \
        != _row(scan(late, index, COEFFICIENTS, SCALE, min_games=50), "x").expected


def test_a_player_whose_tier_changed_in_window_is_flagged():
    index = _changed_index({p: "B" for p in SIX} | {"x": "S"})
    matches = [_on("2026-09-%02d" % (i % 28 + 1)) for i in range(60)]
    assert "tier changed 2026-09-19" in _row(
        scan(matches, index, COEFFICIENTS, SCALE, min_games=50), "x").caution


def test_an_unchanged_player_carries_no_change_caution():
    index = _changed_index({p: "B" for p in SIX} | {"x": "S"})
    matches = [_on("2026-09-%02d" % (i % 28 + 1)) for i in range(60)]
    assert "tier changed" not in _row(
        scan(matches, index, COEFFICIENTS, SCALE, min_games=50), "y").caution
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_scan.py -k "own_date or changed" -v`
Expected: FAIL, expectations equal and no caution text

- [ ] **Step 3: Implement**

In `scan()`, resolve at the match date:

```python
        on_date = (match.get("start_time") or "")[:10] or None
        alpha_r = index.resolve_all(alpha, channel, on_date)
        beta_r = index.resolve_all(beta, channel, on_date)
```

Track `changed_on: Dict[str, str]` from `index.history` for players whose change
date falls inside the window, add `changed_on: str = ""` and `games_at_tier: int
= 0` to `ScanRow`, and put the change first in `caution`:

```python
        if self.changed_on:
            return "tier changed %s; %d games at %s" % (
                self.changed_on, self.games_at_tier, self.tier)
```

Restrict the verdict to current-era games when a change falls in the window, the
same rule the report uses.

- [ ] **Step 4: Run the suite**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gibhub/scan.py tests/test_scan.py
git commit -m "feat(scan): score at as-of tiers and flag in-window changes"
```

---

## Task 10: Validate the log against the tier list

**Files:** Create `tools/check_tier_history.py`, `tests/test_check_tier_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_check_tier_history.py
import pytest

from tools.check_tier_history import Problem, check


def test_a_clean_log_has_no_problems():
    assert check({"p1": "S"}, [("2026-09-19", "p1", "E", "S")]) == []


def test_a_logged_destination_must_match_the_current_list():
    problems = check({"p1": "A"}, [("2026-09-19", "p1", "E", "S")])
    assert problems == [Problem("p1", "list says A, log's last entry says S")]


def test_dates_must_not_go_backwards_for_one_player():
    problems = check({"p1": "S"},
                     [("2026-10-01", "p1", "E", "A"), ("2026-09-19", "p1", "A", "S")])
    assert "out of order" in problems[0].detail


def test_two_entries_on_one_date_for_one_player_are_rejected():
    problems = check({"p1": "S"},
                     [("2026-09-19", "p1", "E", "A"), ("2026-09-19", "p1", "A", "S")])
    assert "same date" in problems[0].detail


def test_a_chain_must_join_up():
    problems = check({"p1": "S"},
                     [("2026-09-19", "p1", "E", "A"), ("2026-10-01", "p1", "B", "S")])
    assert "leaves A but next entry starts from B" in problems[0].detail
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m pytest tests/test_check_tier_history.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tools.check_tier_history'`

- [ ] **Step 3: Implement**

`check(current, entries) -> List[Problem]` applying the four rules above, plus a
`main()` that loads `overrides.txt` and `tier-history.txt`, prints each problem,
and exits 1 if any. Add `tools/__init__.py` if absent so the test can import it.

- [ ] **Step 4: Run and watch them pass**

Run: `python3 -m pytest tests/test_check_tier_history.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add tools/check_tier_history.py tests/test_check_tier_history.py
git commit -m "test(tools): fail when the change log and tier list disagree"
```

---

## Task 11: Prove the past stops moving

No tier is changed here. This is the acceptance test for everything above, run
against a throwaway log entry and a scratch bundle, committing nothing to
`data/`.

- [ ] **Step 1: Record the current scan**

```bash
python3 -m gibhub.cli scan --range 4m --min-games 50 --all --out /tmp/before.csv
```

- [ ] **Step 2: Build a scratch bundle with one invented change**

Pick the player the scan currently ranks first and the tier it recommends. At
the time of writing that is `jussi8030`, E, recommended `MOVE UP: E -> S`; use
whoever it actually is when you run it.

```bash
python3 - <<'EOF'
import json
b = json.load(open("coefficients.json"))
pid = "76903d56-f455-5be9-8c7f-b8d4c11c5b97"   # jussi8030
was = b["overrides"][pid]
b["overrides"][pid] = "S"
b["history"] = [{"date": "2026-09-19", "player": pid,
                 "previous": was, "tier": "S", "note": "acceptance test"}]
json.dump(b, open("/tmp/scratch.json", "w"))
EOF
```

- [ ] **Step 3: Scan against it**

```bash
python3 -m gibhub.cli --bundle /tmp/scratch.json scan \
    --range 4m --min-games 50 --all --out /tmp/after.csv
```

- [ ] **Step 4: Assert only the changed player moved**

```bash
diff <(cut -d, -f2,14,17 /tmp/before.csv) <(cut -d, -f2,14,17 /tmp/after.csv)
```

Expected: **exactly one differing row, the promoted player's.** Every other
player must be byte-identical.

Without as-of resolution this diff shows 17 of 18 rows changing and three
verdicts flipping, which is the behaviour the whole feature exists to remove. If
anything other than the one row moves, the match date is not reaching
`resolve()` somewhere - check `dataset.match_to_sample`, `report.build_report`
and `scan.scan` in that order.

- [ ] **Step 5: Clean up**

```bash
rm -f /tmp/scratch.json /tmp/before.csv /tmp/after.csv
```

Nothing to commit. `data/tier-changes.tsv` stays empty.

---

## Task 11b: Runbook for a real decision

Not part of this build. This is the procedure to follow **when a tier actually changes**,
recorded here so it is not reinvented.

1. Edit `data/tierlist-events-3v3.txt` to the new tier.
2. Append one line to `data/tier-changes.tsv` with the decision date, the player
   token as the tier list spells it, the old tier, the new tier, and a note
   carrying the evidence.
3. Resolve and validate:

```bash
python3 tools/resolve_tierlist.py data/tierlist-events-3v3.txt overrides.txt \
    data/tier-changes.tsv tier-history.txt
python3 tools/check_tier_history.py
```

4. Refit and sanity-check:

```bash
python3 -m gibhub.cli fit --refit --tier-channel Events --points \
    --impute-max A --overrides overrides.txt --tier-history tier-history.txt
python3 tools/check_fit.py
```

5. Commit as `data(tierlist): <what changed>`, with before/after fit metrics in
   the body per the `conventional-commits` skill.

---

## Task 12: Documentation

- [ ] Update `README.md`: the change log, the era table, `--tier-history`, and
  the limitation that history begins at the first logged decision, so until one
  is logged nothing behaves differently.
- [ ] Update `CLAUDE.md`: replace the "Tiers have no history" domain fact with
  how as-of resolution works, and note that the 4-month default can now be
  widened.
- [ ] Commit as `docs: describe tier history`.
