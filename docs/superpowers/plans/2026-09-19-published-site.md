# Published Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the scan, the model and (in phase 2) per-player verdicts as a
static site and a static JSON API on Cloudflare Pages, rebuilt daily by GitHub
Actions.

**Architecture:** One new pure module, `gibhub/site.py`, turns the objects
`scan.py` and `report.py` already produce into a `{path: bytes}` dict. `cli.py`
gains a `site` subcommand that fetches, calls `build_site`, and writes the dict
to disk. No network, no filesystem and no clock in `site.py` — the build time
and window are passed in, the same way `report.py` takes its provenance.

**Tech Stack:** Python 3.9, standard library only (`html`, `json`, `csv`,
`dataclasses`). No template engine, no CSS framework, no JavaScript. GitHub
Actions for the build, `wrangler` for the deploy, Cloudflare Pages for hosting.

**Spec:** `docs/superpowers/specs/2026-09-19-published-site-design.md`

---

## File Structure

| File | Responsibility |
| --- | --- |
| `gibhub/site.py` | Create. Pure. Report/scan objects to `{path: bytes}`. Slugs, HTML pages, JSON, `_headers`, `_redirects`. |
| `tests/test_site.py` | Create. Unit tests for every function in `site.py`, plus the three guard tests. |
| `gibhub/cli.py` | Modify. Add the `site` subparser and `cmd_site`; add `site` to the dispatch in `main`. |
| `tests/test_cli.py` | Modify. End-to-end tests for `site`, using the existing `_ScanClient` and `scan_bundle_path` fixtures. |
| `.github/workflows/site.yml` | Create. Daily cron plus manual dispatch: restore cache, build, deploy, save cache. |
| `README.md` | Modify. A "Published site" section and the `site` command in the options table. |

`site.py` holds page rendering and serialisation together because they change
together: adding a column to the index table means adding a field to
`scan.json`. It does not hold fetching or writing, which belong to `cli.py`.

### Conventions this plan assumes

- Python 3.9. `typing.Dict` / `typing.List`, never `dict[str, str]`.
- Tests touch no network. Every test here builds its inputs in memory.
- Commit after every task, Conventional Commits, scope `site`.
- Run `python3 -m pytest` before each commit, as its own command — never piped
  into `tail`, which swallows the exit status.

---

# Phase 1 — the scan index, the about page, the JSON API

At the end of phase 1 there is a working public site with one table on
it. No player pages.

## Task 1: Slugs

**Files:**
- Create: `gibhub/site.py`
- Create: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_site.py
from gibhub.scan import ScanRow
from gibhub.site import assign_slugs, slugify


def _row(player_id, nick, **kwargs):
    fields = dict(
        player_id=player_id, nick=nick, tier="A", games=100, expected=50.0,
        actual=60, per_100=10.0, tiers_off=0.5, luck=0.01, label="OVER",
        recommendation="CONSIDER MOVING UP: A → E", top_mate="", top_mate_share=0.0,
        guessed_share=0.0,
    )
    fields.update(kwargs)
    return ScanRow(**fields)


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Lepari") == "lepari"
    assert slugify("unbiased moderator") == "unbiased-moderator"


def test_slugify_collapses_runs_and_trims_edges():
    assert slugify("!!! h2o !!!") == "h2o"
    assert slugify("a___b") == "a-b"


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!!") == "player"


def test_assign_slugs_disambiguates_a_collision_with_the_uuid():
    # Both nicks slugify to "chuck": differing case is the common way this
    # happens, since slugify lowercases.
    rows = [_row("3f2a1b9c-0000-0000-0000-000000000000", "chuCk"),
            _row("aa11bb22-0000-0000-0000-000000000000", "CHUCK")]
    slugs = assign_slugs(rows)
    assert slugs["3f2a1b9c-0000-0000-0000-000000000000"] == "chuck"
    assert slugs["aa11bb22-0000-0000-0000-000000000000"] == "chuck-aa11bb"


def test_assign_slugs_is_stable_regardless_of_row_order():
    a = _row("3f2a1b9c-0000-0000-0000-000000000000", "chuCk")
    b = _row("aa11bb22-0000-0000-0000-000000000000", "CHUCK")
    assert assign_slugs([a, b]) == assign_slugs([b, a])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'gibhub.site'`

- [ ] **Step 3: Write the minimal implementation**

```python
# gibhub/site.py
"""The published site: report and scan objects in, {path: bytes} out.

Pure. No network, no filesystem, no clock -- the build time and the window are
passed in, so two builds of the same inputs produce identical bytes.
"""

import re
from typing import Dict, Sequence

from .scan import ScanRow

_UNSAFE = re.compile(r"[^a-z0-9]+")


def slugify(nick: str) -> str:
    """A nick as a URL path segment. Never empty."""
    slug = _UNSAFE.sub("-", (nick or "").lower()).strip("-")
    return slug or "player"


def assign_slugs(rows: Sequence[ScanRow]) -> Dict[str, str]:
    """player_id -> slug, with collisions broken by the player id.

    Sorted by player id first so the result does not depend on row order: the
    index is ranked by effect size, which moves every build.
    """
    slugs: Dict[str, str] = {}
    taken = set()
    for row in sorted(rows, key=lambda r: r.player_id):
        slug = slugify(row.nick)
        if slug in taken:
            slug = "%s-%s" % (slug, row.player_id[:6])
        taken.add(slug)
        slugs[row.player_id] = slug
    return slugs
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): slug player nicks for URLs"
```

---

## Task 2: The page shell

Every page is one self-contained HTML file: no external stylesheet, no font
request, no script. `color-scheme` gives light and dark for free.

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.site import page


def test_page_is_a_complete_document():
    html = page("Scan", "<p>body</p>")
    assert html.startswith("<!doctype html>")
    assert "<title>Scan</title>" in html
    assert "<p>body</p>" in html
    assert html.rstrip().endswith("</html>")


def test_page_escapes_the_title():
    assert "<title>a &lt;b&gt;</title>" in page("a <b>", "")


def test_page_loads_nothing_from_the_network():
    html = page("Scan", "")
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k page -v`
Expected: FAIL, `ImportError: cannot import name 'page'`

- [ ] **Step 3: Write the minimal implementation**

```python
# add to gibhub/site.py, after the imports
import html as html_module

STYLE = """\
:root { color-scheme: light dark; }
body { font: 16px/1.55 system-ui, sans-serif; max-width: 64rem;
       margin: 0 auto; padding: 1.5rem 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .95rem; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #8884; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.caveats { border-left: 3px solid #c80; padding: .1rem 0 .1rem 1rem; margin: 1.5rem 0; }
.caveats p { margin: .5rem 0; }
.stamp { opacity: .7; font-size: .85rem; }
nav a { margin-right: 1rem; }
"""


def escape(value) -> str:
    return html_module.escape(str(value), quote=True)


def page(title: str, body: str) -> str:
    """One self-contained document. Nothing is fetched at view time."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>%s</title>\n"
        "<style>%s</style>\n"
        '<nav><a href="/">Scan</a><a href="/about/">How this works</a></nav>\n'
        "%s\n"
        "</html>\n"
    ) % (escape(title), STYLE, body)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): a self-contained page shell"
```

---

## Task 3: The caveat block

This is the task the spec cares most about. A public table naming players as
`MOVE DOWN` needs its three caveats on the page, not in a README.

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.scan import Coverage
from gibhub.site import caveat_block

CLEAN = Coverage(players_seen=100, players_guessed=2, guessed_share=0.02)
HEAVY = Coverage(players_seen=100, players_guessed=46, guessed_share=0.46)


def test_caveat_block_always_explains_keep():
    block = caveat_block(CLEAN, window="last 1y", built_at="2026-09-19T05:00:00+00:00",
                         fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)
    assert "too few games to call" in block
    assert "correctly tiered" in block


def test_caveat_block_always_warns_about_unmapped_names():
    block = caveat_block(CLEAN, window="last 1y", built_at="2026-09-19T05:00:00+00:00",
                         fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)
    assert "no account mapped" in block


def test_caveat_block_carries_the_build_stamp():
    block = caveat_block(CLEAN, window="last 1y", built_at="2026-09-19T05:00:00+00:00",
                         fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)
    assert "2026-09-19T05:00:00+00:00" in block
    assert "last 1y" in block
    assert "6382" in block


def test_caveat_block_raises_the_coverage_warning_when_tiers_were_guessed():
    block = caveat_block(HEAVY, window="last 1y", built_at="2026-09-19T05:00:00+00:00",
                         fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)
    assert "UNRELIABLE" in block
    assert "46 of the 100 players" in block


def test_caveat_block_omits_the_coverage_warning_when_coverage_is_clean():
    block = caveat_block(CLEAN, window="last 1y", built_at="2026-09-19T05:00:00+00:00",
                         fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)
    assert "UNRELIABLE" not in block and "CAUTION" not in block
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k caveat -v`
Expected: FAIL, `ImportError: cannot import name 'caveat_block'`

- [ ] **Step 3: Write the minimal implementation**

`Coverage.warning` already returns the `CAUTION`/`UNRELIABLE` sentence, or an
empty string when coverage is clean. Reuse it rather than re-deriving the
thresholds.

```python
# add to gibhub/site.py
from .scan import Coverage, ScanRow  # replace the existing ScanRow import


def caveat_block(
    coverage: Coverage,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    """What a stranger has to know before reading a verdict as a fact."""
    parts = ['<section class="caveats">']
    if coverage.warning:
        parts.append("<p><strong>%s</strong> %d of the %d players in this window "
                     "had no assigned tier.</p>"
                     % (escape(coverage.warning), coverage.players_guessed,
                        coverage.players_seen))
    parts.append(
        "<p><code>KEEP</code> means too few games to call, not correctly "
        "tiered. A row with few games and a large effect reads as "
        "<code>KEEP</code> because the evidence is thin, not because the tier "
        "is right.</p>")
    parts.append(
        "<p>Some names on the tier list still have no account mapped, mostly C and D, "
        "so a player missing from this table has not been cleared - they have "
        "not been checked.</p>")
    parts.append(
        '<p class="stamp">Window %s. Built %s from a model fitted %s on %d '
        "matches.</p>" % (escape(window), escape(built_at), escape(fitted_at),
                          sample_size))
    parts.append("</section>")
    return "\n".join(parts)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): put the caveats on the page, not in the README"
```

---

## Task 4: The index page

Same columns as `to_scan_table`, same meanings, so a screenshot of either can be
compared with the other.

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.site import index_page

STAMP = dict(window="last 1y", built_at="2026-09-19T05:00:00+00:00",
             fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)


def test_index_page_lists_a_mis_tiered_player():
    rows = [_row("p1", "Lepari", tier="A", games=120, per_100=12.5, tiers_off=0.8,
                 recommendation="CONSIDER MOVING UP: A → E", luck=0.01)]
    html = index_page(rows, CLEAN, {}, **STAMP)
    assert "Lepari" in html
    assert "+12.5" in html
    assert "CONSIDER MOVING UP: A → E" in html
    assert "1 in 100" in html


def test_index_page_hides_players_whose_record_matches_their_tier():
    rows = [_row("p1", "Lepari", label="ON TIER", recommendation="KEEP")]
    html = index_page(rows, CLEAN, {}, **STAMP)
    assert "Lepari" not in html
    assert "No player" in html


def test_index_page_caps_the_odds_it_prints():
    rows = [_row("p1", "Lepari", luck=0.0)]
    assert "1 in 10000+" in index_page(rows, CLEAN, {}, **STAMP)


def test_index_page_escapes_a_nick_that_looks_like_markup():
    rows = [_row("p1", "<script>x</script>")]
    html = index_page(rows, CLEAN, {}, **STAMP)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_index_page_carries_the_caveats():
    html = index_page([_row("p1", "Lepari")], CLEAN, {}, **STAMP)
    assert "too few games to call" in html


def test_index_page_links_a_player_when_a_slug_is_given():
    rows = [_row("p1", "Lepari")]
    html = index_page(rows, CLEAN, {"p1": "lepari"}, **STAMP)
    assert '<a href="/players/lepari/">Lepari</a>' in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k index_page -v`
Expected: FAIL, `ImportError: cannot import name 'index_page'`

- [ ] **Step 3: Write the minimal implementation**

`slugs` is empty in phase 1, so names render as plain text. Phase 2 passes the
real map and the same code starts linking. That is the whole change.

```python
# add to gibhub/site.py
COLUMNS = ("Player", "Tier", "Games", "Per 100", "Tiers off", "Decision",
           "Confidence", "Read with care because")
NUMERIC = frozenset(("Games", "Per 100", "Tiers off", "Confidence"))


def _odds(row: ScanRow) -> str:
    return "1 in %d%s" % (row.odds, "+" if row.odds >= 10000 else "")


def _name_cell(row: ScanRow, slugs: Dict[str, str]) -> str:
    slug = slugs.get(row.player_id)
    if not slug:
        return escape(row.nick)
    return '<a href="/players/%s/">%s</a>' % (escape(slug), escape(row.nick))


def _row_html(row: ScanRow, slugs: Dict[str, str]) -> str:
    cells = [
        _name_cell(row, slugs),
        escape(row.tier),
        '<td class="num">%d' % row.games,
        '<td class="num">%+.1f' % row.per_100,
        '<td class="num">%+.1f' % row.tiers_off,
        escape(row.recommendation),
        '<td class="num">%s' % escape(_odds(row)),
        escape(row.caution),
    ]
    out = ["<tr>"]
    for cell in cells:
        out.append(cell if cell.startswith("<td") else "<td>" + cell)
    return "".join(out)


def index_page(
    rows: Sequence[ScanRow],
    coverage: Coverage,
    slugs: Dict[str, str],
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    shown = [r for r in rows if r.label != "ON TIER"]
    body = ["<h1>Where a record and a tier disagree</h1>"]
    body.append(caveat_block(coverage, window=window, built_at=built_at,
                             fitted_at=fitted_at, sample_size=sample_size))
    if not shown:
        body.append("<p>No player's record differs from their tier by more "
                    "than luck.</p>")
    else:
        head = "".join(
            '<th class="num">%s' % escape(c) if c in NUMERIC else "<th>" + escape(c)
            for c in COLUMNS)
        body.append("<table><thead><tr>%s</thead><tbody>%s</tbody></table>"
                    % (head, "".join(_row_html(r, slugs) for r in shown)))
        body.append(
            "<p><strong>Per 100</strong> is wins per 100 games above or below "
            "what the tier predicts, and is the number to argue over. "
            "<strong>Tiers off</strong> is how many tier steps that gap is "
            "worth. <strong>Confidence</strong> assumes games are independent, "
            "which they are not when one teammate fills much of a sample, so it "
            "is capped at 1 in 10000. Showing %d of %d players scanned.</p>"
            % (len(shown), len(rows)))
    return page("3v3 tiering evidence", "\n".join(body))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 19 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): render the scan as the index page"
```

---

## Task 5: The about page

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.site import about_page

POINTS = {"S": 5.0, "E": 4.0, "A": 3.0, "B": 2.0, "C": 1.0, "D": 0.0}
METRICS = {"accuracy": 0.6393, "brier": 0.2204, "log_loss": 0.6304, "samples": 6382}


def test_about_page_states_the_tier_order():
    html = about_page(POINTS, 0.4385, METRICS, **STAMP)
    assert "S &gt; E &gt; A &gt; B &gt; C &gt; D" in html


def test_about_page_prints_the_fit_metrics():
    html = about_page(POINTS, 0.4385, METRICS, **STAMP)
    assert "63.9%" in html and "0.2204" in html and "0.6304" in html
    assert "6382" in html


def test_about_page_says_there_is_no_intercept():
    assert "no intercept" in about_page(POINTS, 0.4385, METRICS, **STAMP)


def test_about_page_lists_the_known_limitations():
    html = about_page(POINTS, 0.4385, METRICS, **STAMP)
    assert "circular" in html
    assert "52.5%" in html
    assert "no history" in html


def test_about_page_carries_the_caveats_too():
    assert "too few games to call" in about_page(POINTS, 0.4385, METRICS, **STAMP)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k about -v`
Expected: FAIL, `ImportError: cannot import name 'about_page'`

- [ ] **Step 3: Write the minimal implementation**

`about_page` takes the coverage-free stamp, so it passes a clean `Coverage` to
`caveat_block`: the about page is not a verdict, but it carries the same footer
so a reader landing there first sees the same rules.

```python
# add to gibhub/site.py
TIER_ORDER = ("S", "E", "A", "B", "C", "D")

LIMITATIONS = (
    "The approach is partly circular by design: it asks whether a record is "
    "consistent with the tier held, not what tier a player deserves in the "
    "absolute.",
    "Tiers have no history, so past matches are scored against today's tiers. "
    "A recently promoted player looks like they were overperforming all year.",
    "The alpha side wins 52.5% of matches and the model cannot express that.",
    "A player with no assigned tier gets one imputed from their shrunken "
    "UTRO, capped at A. Imputation error, not luck, is the largest source of "
    "false signal here.",
)


def about_page(
    tier_points: Dict[str, float],
    scale: float,
    fit_metrics: Dict[str, float],
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    rows = "".join(
        '<tr><td>%s<td class="num">%g<td class="num">%+.2f'
        % (escape(tier), tier_points.get(tier, 0.0),
           scale * tier_points.get(tier, 0.0))
        for tier in TIER_ORDER)
    body = [
        "<h1>How this works</h1>",
        "<p>Each tier is worth a fixed number of points. A team's "
        "strength is the sum of its three players' points, and the only fitted "
        "parameter is what one point of advantage is worth:</p>",
        "<p><code>P(win) = sigmoid(%.2f &times; (my team's points &minus; "
        "theirs))</code></p>" % scale,
        "<p>There is <strong>no intercept</strong>, by design: two mirrored "
        "rosters score exactly 0.5.</p>",
        "<h2>The tier letters are not an A-to-E ladder</h2>",
        "<p>The strength order is <strong>S &gt; E &gt; A &gt; B &gt; C &gt; "
        "D</strong>. Tier E is the second strongest, not the weakest. Every "
        'place that needs "the next tier up" reads it off the points, never '
        "the alphabet.</p>",
        '<table><thead><tr><th>Tier<th class="num">Points'
        '<th class="num">Log-odds</thead><tbody>%s</tbody></table>' % rows,
        "<h2>The fit</h2>",
        "<p>Fitted on %d decided 3v3 matches: %.1f%% accuracy, %.4f Brier, "
        "%.4f log loss.</p>" % (
            int(fit_metrics.get("samples", 0)),
            100 * fit_metrics.get("accuracy", 0.0),
            fit_metrics.get("brier", 0.0),
            fit_metrics.get("log_loss", 0.0)),
        "<h2>Known limitations</h2>",
        "<ul>%s</ul>" % "".join("<li>%s" % escape(t) for t in LIMITATIONS),
        caveat_block(Coverage(0, 0, 0.0), window=window, built_at=built_at,
                     fitted_at=fitted_at, sample_size=sample_size),
    ]
    return page("How this works", "\n".join(body))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 24 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): an about page carrying the model and its limits"
```

---

## Task 6: The JSON API

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
import json

from gibhub.site import index_json, model_json, scan_json


def test_scan_json_carries_every_row_including_on_tier_ones():
    rows = [_row("p1", "Lepari"), _row("p2", "Jassi", label="ON TIER",
                                       recommendation="KEEP")]
    payload = json.loads(scan_json(rows, CLEAN, {"p1": "lepari", "p2": "jassi"},
                                   **STAMP))
    assert [r["nick"] for r in payload["rows"]] == ["Lepari", "Jassi"]
    assert payload["rows"][0]["slug"] == "lepari"
    assert payload["rows"][0]["odds_1_in"] == 100


def test_scan_json_reports_the_coverage():
    payload = json.loads(scan_json([], HEAVY, {}, **STAMP))
    assert payload["coverage"]["players_guessed"] == 46
    assert payload["coverage"]["players_seen"] == 100


def test_scan_json_stamps_the_build():
    payload = json.loads(scan_json([], CLEAN, {}, **STAMP))
    assert payload["built_at"] == "2026-09-19T05:00:00+00:00"
    assert payload["window"] == "last 1y"


def test_model_json_carries_the_points_and_the_scale():
    payload = json.loads(model_json(POINTS, 0.4385, METRICS,
                                    fitted_at="2026-09-18T00:00:00+00:00",
                                    sample_size=6382))
    assert payload["tier_points"]["E"] == 4.0
    assert payload["scale"] == 0.4385
    assert payload["fit_metrics"]["accuracy"] == 0.6393
    assert payload["tier_order"] == ["S", "E", "A", "B", "C", "D"]


def test_index_json_maps_slugs_to_player_ids():
    rows = [_row("3f2a1b9c-0000-0000-0000-000000000000", "Lepari")]
    payload = json.loads(index_json(
        rows, {"3f2a1b9c-0000-0000-0000-000000000000": "lepari"}, **STAMP))
    assert payload["players"] == [
        {"slug": "lepari", "player_id": "3f2a1b9c-0000-0000-0000-000000000000",
         "nick": "Lepari", "tier": "A"}]


def test_index_json_sorts_players_by_slug():
    rows = [_row("p2", "zed", tier="B"), _row("p1", "alf")]
    payload = json.loads(index_json(rows, {"p1": "alf", "p2": "zed"}, **STAMP))
    assert [p["slug"] for p in payload["players"]] == ["alf", "zed"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k json -v`
Expected: FAIL, `ImportError: cannot import name 'scan_json'`

- [ ] **Step 3: Write the minimal implementation**

`sort_keys=True` and a fixed separator keep the bytes stable between builds, so
an unchanged scan produces an unchanged file.

```python
# add to gibhub/site.py
import json


def _dump(payload) -> str:
    return json.dumps(payload, sort_keys=True, indent=1) + "\n"


def scan_json(
    rows: Sequence[ScanRow],
    coverage: Coverage,
    slugs: Dict[str, str],
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    return _dump({
        "built_at": built_at,
        "window": window,
        "fitted_at": fitted_at,
        "sample_size": sample_size,
        "coverage": {
            "players_seen": coverage.players_seen,
            "players_guessed": coverage.players_guessed,
            "guessed_share": round(coverage.guessed_share, 4),
            "warning": coverage.warning,
        },
        "rows": [{
            "player_id": r.player_id,
            "slug": slugs.get(r.player_id, ""),
            "nick": r.nick,
            "tier": r.tier,
            "games": r.games,
            "expected": round(r.expected, 2),
            "actual": r.actual,
            "per_100": round(r.per_100, 2),
            "tiers_off": round(r.tiers_off, 3),
            "odds_1_in": r.odds,
            "label": r.label,
            "recommendation": r.recommendation,
            "top_mate": r.top_mate,
            "top_mate_share": round(r.top_mate_share, 3),
            "guessed_share": round(r.guessed_share, 3),
            "caution": r.caution,
        } for r in rows],
    })


def model_json(
    tier_points: Dict[str, float],
    scale: float,
    fit_metrics: Dict[str, float],
    *,
    fitted_at: str,
    sample_size: int,
) -> str:
    return _dump({
        "tier_order": list(TIER_ORDER),
        "tier_points": tier_points,
        "scale": scale,
        "intercept": 0.0,
        "fit_metrics": fit_metrics,
        "fitted_at": fitted_at,
        "sample_size": sample_size,
    })


def index_json(
    rows: Sequence[ScanRow],
    slugs: Dict[str, str],
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    players = sorted(
        ({"slug": slugs[r.player_id], "player_id": r.player_id,
          "nick": r.nick, "tier": r.tier}
         for r in rows if r.player_id in slugs),
        key=lambda p: p["slug"])
    return _dump({
        "built_at": built_at,
        "window": window,
        "fitted_at": fitted_at,
        "sample_size": sample_size,
        "players": players,
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 30 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): publish the scan and the model as json"
```

---

## Task 7: `_headers`, and assembling the site

Cloudflare Pages sends no CORS header unless told. Without `_headers` the JSON
is readable in a browser tab and unusable from anyone else's page.

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.site import build_site


def _site(rows=(), coverage=CLEAN):
    return build_site(list(rows), coverage, POINTS, 0.4385, METRICS, **STAMP)


def test_build_site_writes_the_phase_one_paths():
    assert set(_site().keys()) == {
        "index.html", "about/index.html", "_headers",
        "api/scan.json", "api/model.json", "api/index.json"}


def test_build_site_returns_bytes_for_every_path():
    assert all(isinstance(v, bytes) for v in _site().values())


def test_headers_open_the_api_to_cross_origin_reads():
    headers = _site()["_headers"].decode("utf-8")
    assert "/api/*" in headers
    assert "Access-Control-Allow-Origin: *" in headers


def test_build_site_does_not_link_players_in_phase_one():
    site = _site([_row("p1", "Lepari")])
    assert "/players/" not in site["index.html"].decode("utf-8")


def test_build_site_is_byte_identical_for_identical_input():
    rows = [_row("p1", "Lepari")]
    assert _site(rows) == _site(rows)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k build_site -v`
Expected: FAIL, `ImportError: cannot import name 'build_site'`

- [ ] **Step 3: Write the minimal implementation**

`build_site` passes an empty `slugs` to `index_page` in phase 1, so no player
link is emitted, while `index_json` still publishes the slug map for anyone
consuming the API. Task 12 flips the index to linking.

```python
# add to gibhub/site.py
HEADERS = "/api/*\n  Access-Control-Allow-Origin: *\n"


def headers() -> str:
    return HEADERS


def build_site(
    rows: Sequence[ScanRow],
    coverage: Coverage,
    tier_points: Dict[str, float],
    scale: float,
    fit_metrics: Dict[str, float],
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> Dict[str, bytes]:
    """Every file the published site is made of. Paths are relative, no leading slash."""
    stamp = dict(window=window, built_at=built_at, fitted_at=fitted_at,
                 sample_size=sample_size)
    slugs = assign_slugs(rows)
    files = {
        "index.html": index_page(rows, coverage, {}, **stamp),
        "about/index.html": about_page(tier_points, scale, fit_metrics, **stamp),
        "_headers": headers(),
        "api/scan.json": scan_json(rows, coverage, slugs, **stamp),
        "api/model.json": model_json(tier_points, scale, fit_metrics,
                                     fitted_at=fitted_at, sample_size=sample_size),
        "api/index.json": index_json(rows, slugs, **stamp),
    }
    return {path: text.encode("utf-8") for path, text in files.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, 35 tests

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): assemble the site and open the api to cors"
```

---

## Task 8: The guard tests

Three assertions from the spec that are not about any single function: they are
about what the build as a whole must never stop doing.

**Files:**
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
import re


def _html_pages(site):
    return {p: b.decode("utf-8") for p, b in site.items() if p.endswith(".html")}


def test_every_html_page_carries_the_caveats():
    site = _site([_row("p1", "Lepari")])
    missing = [p for p, html in _html_pages(site).items()
               if "too few games to call" not in html]
    assert missing == [], "pages published without the caveat block: %s" % missing


def test_every_internal_link_resolves_to_a_published_path():
    site = _site([_row("p1", "Lepari")])
    broken = []
    for path, html in _html_pages(site).items():
        for href in re.findall(r'href="([^"]+)"', html):
            target = href.lstrip("/") or "index.html"
            if target.endswith("/"):
                target += "index.html"
            if target not in site:
                broken.append((path, href))
    assert broken == [], "links to nothing: %s" % broken


def test_every_published_json_file_parses():
    site = _site([_row("p1", "Lepari")])
    for path, blob in site.items():
        if path.endswith(".json"):
            json.loads(blob.decode("utf-8"))
```

- [ ] **Step 2: Run the tests to verify they fail or pass honestly**

Run: `python3 -m pytest tests/test_site.py -k "carries_the_caveats or resolves or parses" -v`
Expected: PASS. These guard existing behaviour rather than driving new code. If
any fails, the bug is in Tasks 2-7 and belongs fixed there, not worked around
here.

- [ ] **Step 3: Commit**

```bash
git add tests/test_site.py
git commit -m "test(site): guard the caveats, the links and the json"
```

---

## Task 9: The `site` command

**Files:**
- Modify: `gibhub/cli.py` — import block at the top, `build_parser`, a new
  `cmd_site`, and the dispatch in `main` around `gibhub/cli.py:386-394`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_cli.py
def test_site_command_writes_the_files(monkeypatch, tmp_path, capsys,
                                       scan_bundle_path):
    client = _ScanClient([_scan_match(i) for i in range(60)])
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: client)
    out = tmp_path / "_site"

    code = main(["--bundle", scan_bundle_path, "site", "--out", str(out),
                 "--min-games", "50"])

    assert code == 0
    assert (out / "index.html").exists()
    assert (out / "about" / "index.html").exists()
    assert (out / "_headers").exists()
    assert (out / "api" / "scan.json").exists()
    assert "Me" in (out / "index.html").read_text(encoding="utf-8")


def test_site_command_refuses_a_bundle_with_no_tier_list(
    monkeypatch, tmp_path, capsys, fake_bundle_path
):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    code = main(["--bundle", fake_bundle_path, "site",
                 "--out", str(tmp_path / "_site")])
    assert code == 1
    assert "no tier list" in capsys.readouterr().err


def test_site_command_clears_stale_files_from_a_previous_build(
    monkeypatch, tmp_path, scan_bundle_path
):
    client = _ScanClient([_scan_match(i) for i in range(60)])
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: client)
    out = tmp_path / "_site"
    out.mkdir()
    (out / "gone.html").write_text("stale", encoding="utf-8")

    main(["--bundle", scan_bundle_path, "site", "--out", str(out),
          "--min-games", "50"])

    assert not (out / "gone.html").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_cli.py -k site -v`
Expected: FAIL, `argparse` exits 2 on the unknown command `site`

- [ ] **Step 3: Write the minimal implementation**

The fetch half is `cmd_scan`'s, which already sweeps matches and collects nicks.
Pull that sweep into a helper both commands call, so the site and the terminal
table can never disagree about what was counted.

```python
# in gibhub/cli.py, add to the render import line:
from .site import build_site

# add after cmd_scan
def _sweep(client, args):
    """Every match in the window, plus a nick for every player seen.

    Shared by scan and site so the two can never count different matches.
    """
    start = None if (getattr(args, "from_", None) or "none").lower() == "none" else args.from_
    params = {"size": "3v3", "state": "finished",
              "range": args.range if not start else None,
              "from": start, "to": args.to}
    matches = []
    nicks = {}
    for match in client.paginate("/matches", params, page_size=PAGE_SIZE):
        matches.append(match)
        for side in ("alpha", "beta"):
            for player in (match.get("teams") or {}).get(side) or []:
                nicks.setdefault(
                    player["player_id"],
                    strip_colors(player.get("discord_nick") or player.get("nick"))[:14])
    return matches, nicks


def cmd_site(args) -> int:
    bundle = load(args.bundle)
    if not bundle.overrides:
        sys.stderr.write(
            "this bundle carries no tier list, so the site would have "
            "nobody to score.\nRefit with --overrides first.\n")
        return 1

    client = make_client(args)
    matches, nicks = _sweep(client, args)
    only = categories_for(args)
    rows = scan(matches, bundle.index(), bundle.coefficients, bundle.scale or 1.0,
                min_games=args.min_games, only=only, nicks=nicks)
    coverage = tier_coverage(matches, bundle.index(), only=only)

    files = build_site(
        rows, coverage,
        bundle.tier_points or dict(TIER_POINTS),
        bundle.scale or 1.0,
        bundle.fit_metrics,
        window=window_label(args),
        built_at=args.built_at or datetime.datetime.now(
            datetime.timezone.utc).replace(microsecond=0).isoformat(),
        fitted_at=bundle.fitted_at,
        sample_size=bundle.sample_size,
    )
    written = write_site(files, args.out)
    print("wrote %d files to %s" % (written, args.out))
    return 0


def write_site(files, out) -> int:
    """Replace `out` with exactly `files`. A stale page must not outlive a build."""
    if os.path.isdir(out):
        shutil.rmtree(out)
    for path, blob in sorted(files.items()):
        destination = os.path.join(out, path)
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        with open(destination, "wb") as handle:
            handle.write(blob)
    return len(files)
```

Add `import datetime`, `import shutil` to the top of `gibhub/cli.py` if either
is absent, and the subparser:

```python
    site_cmd = sub.add_parser("site", help="render the published site")
    site_cmd.add_argument("--out", default="_site", metavar="DIR",
                          help="directory to write the site into (default: _site)")
    site_cmd.add_argument("--range", default="1y")
    site_cmd.add_argument("--from", dest="from_", metavar="YYYY-MM-DD")
    site_cmd.add_argument("--to", metavar="YYYY-MM-DD")
    site_cmd.add_argument("--min-games", type=int, default=50, dest="min_games")
    site_cmd.add_argument("--only", action="append", metavar="TYPE")
    site_cmd.add_argument("--with-poland", action="store_true", dest="with_poland")
    site_cmd.add_argument(
        "--built-at", dest="built_at", metavar="ISO8601",
        help="stamp the build with this time instead of now; for reproducible "
             "output in tests")
```

and the dispatch, next to the existing `scan` line:

```python
        if args.command == "site":
            return cmd_site(args)
```

Then replace the sweep inside `cmd_scan` with a call to the new helper, so the
two commands cannot drift. The block in `cmd_scan` that reads:

```python
    start = None if (getattr(args, "from_", None) or "none").lower() == "none" else args.from_
    params = {"size": "3v3", "state": "finished",
              "range": args.range if not start else None,
              "from": start, "to": args.to}

    matches = []
    nicks = {}
    for match in client.paginate("/matches", params, page_size=100):
        matches.append(match)
        for side in ("alpha", "beta"):
            for player in (match.get("teams") or {}).get(side) or []:
                nicks.setdefault(
                    player["player_id"],
                    strip_colors(player.get("discord_nick") or player.get("nick"))[:14])
```

becomes:

```python
    matches, nicks = _sweep(client, args)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_cli.py -k site -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Verify the whole suite is still green**

Run: `python3 -m pytest`
Expected: PASS, no failures. `cmd_scan` now calls `_sweep`; if any scan test
broke, the extraction changed behaviour and must be fixed rather than the test.

- [ ] **Step 6: Commit**

```bash
git add gibhub/cli.py tests/test_cli.py
git commit -m "feat(cli): add the site command"
```

---

## Task 10: The build workflow

**Files:**
- Create: `.github/workflows/site.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: site

on:
  schedule:
    - cron: "0 5 * * *"
  workflow_dispatch:

concurrency:
  group: site
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.9"

      # The cache holds finished matches, which the API guarantees immutable.
      # Entries are immutable once written, so the key carries the run id and
      # restore falls back to the newest entry with the same prefix. Entries
      # are evicted after seven days unused, which is why this runs daily.
      - uses: actions/cache@v4
        with:
          path: .cache
          key: matches-${{ github.run_id }}
          restore-keys: matches-

      - run: python3 -m pytest

      - run: python3 -m gibhub.cli site --out _site --range 1y

      - uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy _site --project-name=truetier
```

- [ ] **Step 2: Check no secret was inlined**

Run:

```bash
grep -nE "CLOUDFLARE_(API_TOKEN|ACCOUNT_ID)" .github/workflows/site.yml
```

Expected: both lines appear, and both read `${{ secrets.… }}`. A literal value
on either line is a leaked token — stop and rotate it.

There is no YAML parser in the standard library and this repo adds no
dependency to lint one file, so the workflow's syntax is checked by GitHub on
push. Read it once against the `actions/cache` and `wrangler-action` READMEs,
then confirm the first manual run goes green.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/site.yml
git commit -m "ci: build and deploy the site daily"
```

- [ ] **Step 4: Set the two secrets**

In the repo settings, add `CLOUDFLARE_API_TOKEN` (a token scoped to
**Cloudflare Pages: Edit** and nothing else) and `CLOUDFLARE_ACCOUNT_ID`.
Create the Pages project named `truetier` first, from the Cloudflare
dashboard, choosing direct upload rather than a Git connection.

These are repo secrets, not committed files. Nothing here goes in git.

- [ ] **Step 5: Trigger the first run by hand and watch it**

Run the workflow from the Actions tab. Expect the first run to be slow: the
cache is empty, so it reads every match in the window. Confirm the site loads
and that `curl -sI https://truetier.pages.dev/api/scan.json` shows
`access-control-allow-origin: *`.

---

## Task 11: Document it

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Published site" section after "Reading the output"**

```markdown
## The published site

The scan is published at <https://truetier.pages.dev>, rebuilt daily at 05:00
UTC and on demand from the Actions tab. The same build writes a JSON API:

| path | holds |
| --- | --- |
| `/api/scan.json` | every scanned player, including the ones reading `ON TIER` |
| `/api/model.json` | tier points, the fitted scale, the fit metrics |
| `/api/index.json` | the build stamp and the slug-to-UUID map |

It is CORS-open, so anything can read it from a browser. It is also only as
fresh as the last build, which every page stamps.

Render it locally with:

    python3 -m gibhub.cli site --out _site
```

- [ ] **Step 2: Add `site` to the commands near the top of the README**

Under the `scan` examples, add:

```markdown
Render the published site:

    python3 -m gibhub.cli site --out _site
```

- [ ] **Step 3: Read it back against the unslop skill**

Run: `python3 -m pytest`
Expected: PASS. Then reread the new prose: no "seamlessly", no "comprehensive",
no rule-of-three padding.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: describe the published site and its json api"
```

**Phase 1 is done.** The site has an index, an about page and three JSON files,
rebuilt daily. Stop here and watch a few builds before starting phase 2.

---

# Phase 2 — per-player pages

Per-player pages cost real requests: a report fetches that player's profile,
spider and match listing separately, so 155 pages is 155 sets of listing calls
per build. Do not start this until phase 1 has run daily for a week and the
cache is warm.

## Task 12: The player page

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.report import PlayerReport
from gibhub.site import player_page


def _report(**kwargs):
    fields = dict(
        player_id="p1", nick="Lepari", discord_nick="lepari", tiers=[],
        lifetime={}, percentiles=[], rows=[], expected_wins=13.33, actual_wins=7,
        delta=-6.33, label="CLEARLY UNDER", luck=0.004, decided=20,
        current_tier="A", recommendation="MOVE DOWN: A → B", upset_wins=1,
        upset_losses=2, stack_wins=5, underdog_losses=4, even_matches=0, draws=0,
        skipped=0, source_counts={"override": 80, "imputed": 40},
        provenance={}, categories=[], players_seen=39, players_guessed=18,
    )
    fields.update(kwargs)
    return PlayerReport(**fields)


def test_player_page_leads_with_the_verdict():
    html = player_page(_report(), **STAMP)
    assert "Lepari" in html
    assert "CLEARLY UNDER" in html
    assert "MOVE DOWN: A → B" in html
    assert "13.33" in html and "7" in html


def test_player_page_raises_the_guessed_tier_alarm_above_the_headline():
    html = player_page(_report(), **STAMP)
    alarm = html.index("guessed")
    headline = html.index("CLEARLY UNDER")
    assert alarm < headline, "the alarm must survive a cropped screenshot"


def test_player_page_carries_the_caveats():
    assert "too few games to call" in player_page(_report(), **STAMP)


def test_player_page_escapes_the_nick():
    html = player_page(_report(nick="<b>x</b>"), **STAMP)
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_player_page_shows_the_stacked_and_underdog_split():
    html = player_page(_report(), **STAMP)
    assert "stacked" in html.lower() and "underdog" in html.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k player_page -v`
Expected: FAIL, `ImportError: cannot import name 'player_page'`

- [ ] **Step 3: Write the minimal implementation**

`report.guess_warning` already produces the alarm sentence from
`source_counts`; reuse it so the site and the markdown report can never drift
apart on the thresholds.

```python
# add to gibhub/site.py
from .report import PlayerReport, guess_warning


def player_page(
    report: PlayerReport,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    body = ["<h1>%s</h1>" % escape(report.nick)]

    warning = guess_warning(report.source_counts)
    if warning:
        body.append(
            '<p class="caveats"><strong>%s</strong> %d of the %d players in '
            "this window had no assigned tier.</p>"
            % (escape(warning), report.players_guessed, report.players_seen))

    body.append(
        "<p><strong>Expected %.2f wins, actual %d &mdash; %+.2f &rarr; %s"
        "</strong></p>" % (report.expected_wins, report.actual_wins,
                           report.delta, escape(report.label)))
    body.append("<h2>%s</h2>" % escape(report.recommendation))
    body.append(
        "<p>Tier %s over %d decided matches in the window. Won %d while "
        "favoured, lost %d as the underdog: a record built entirely on stacked "
        "teams reads the same as one built against the odds unless you look "
        "here.</p>" % (escape(report.current_tier or "none"), report.decided,
                       report.stack_wins, report.underdog_losses))
    body.append(caveat_block(
        Coverage(report.players_seen, report.players_guessed,
                 (report.players_guessed / report.players_seen)
                 if report.players_seen else 0.0),
        window=window, built_at=built_at, fitted_at=fitted_at,
        sample_size=sample_size))
    return page("%s - 3v3 tiering evidence" % report.nick, "\n".join(body))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): a page per player, alarm above the headline"
```

---

## Task 13: Player JSON

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.site import player_json


def test_player_json_carries_the_verdict_and_its_provenance():
    payload = json.loads(player_json(_report(), slug="lepari", **STAMP))
    assert payload["slug"] == "lepari"
    assert payload["nick"] == "Lepari"
    assert payload["label"] == "CLEARLY UNDER"
    assert payload["expected_wins"] == 13.33
    assert payload["source_counts"]["imputed"] == 40


def test_player_json_stamps_the_build():
    payload = json.loads(player_json(_report(), slug="lepari", **STAMP))
    assert payload["built_at"] == "2026-09-19T05:00:00+00:00"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k player_json -v`
Expected: FAIL, `ImportError: cannot import name 'player_json'`

- [ ] **Step 3: Write the minimal implementation**

```python
# add to gibhub/site.py
def player_json(
    report: PlayerReport,
    *,
    slug: str,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    return _dump({
        "built_at": built_at,
        "window": window,
        "fitted_at": fitted_at,
        "sample_size": sample_size,
        "slug": slug,
        "player_id": report.player_id,
        "nick": report.nick,
        "tier": report.current_tier,
        "decided": report.decided,
        "expected_wins": round(report.expected_wins, 2),
        "actual_wins": report.actual_wins,
        "delta": round(report.delta, 2),
        "label": report.label,
        "recommendation": report.recommendation,
        "luck": report.luck,
        "stack_wins": report.stack_wins,
        "underdog_losses": report.underdog_losses,
        "upset_wins": report.upset_wins,
        "upset_losses": report.upset_losses,
        "source_counts": report.source_counts,
        "players_seen": report.players_seen,
        "players_guessed": report.players_guessed,
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): publish each player's verdict as json"
```

---

## Task 14: Redirects for renamed nicks

**Files:**
- Modify: `gibhub/site.py`
- Modify: `tests/test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
from gibhub.site import redirects

PREVIOUS = {"players": [
    {"slug": "chuck", "player_id": "p1", "nick": "chuCk", "tier": "A"},
    {"slug": "jassi", "player_id": "p2", "nick": "Jassi", "tier": "A"},
]}


def test_redirects_point_a_retired_slug_at_the_current_one():
    lines = redirects(PREVIOUS, {"p1": "czkk", "p2": "jassi"})
    assert "/players/chuck/ /players/czkk/ 301" in lines


def test_redirects_leave_unchanged_slugs_alone():
    assert redirects(PREVIOUS, {"p1": "chuck", "p2": "jassi"}) == ""


def test_redirects_ignore_a_player_who_has_left_the_scan():
    assert redirects(PREVIOUS, {"p2": "jassi"}) == ""


def test_redirects_survive_a_missing_previous_build():
    assert redirects(None, {"p1": "chuck"}) == ""
    assert redirects({}, {"p1": "chuck"}) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k redirects -v`
Expected: FAIL, `ImportError: cannot import name 'redirects'`

- [ ] **Step 3: Write the minimal implementation**

```python
# add to gibhub/site.py
def redirects(previous, slugs: Dict[str, str]) -> str:
    """_redirects lines for slugs that moved since the last build.

    A player who left the scan gets no line: the old page is gone, and a
    redirect to nothing is worse than a 404.
    """
    lines = []
    for entry in (previous or {}).get("players", []):
        current = slugs.get(entry.get("player_id"))
        if current and current != entry.get("slug"):
            lines.append("/players/%s/ /players/%s/ 301"
                         % (entry["slug"], current))
    return "\n".join(sorted(lines)) + ("\n" if lines else "")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gibhub/site.py tests/test_site.py
git commit -m "feat(site): redirect a renamed player's old url"
```

---

## Task 15: Wire player pages into the build

**Files:**
- Modify: `gibhub/site.py` — `build_site`
- Modify: `tests/test_site.py`
- Modify: `gibhub/cli.py` — `cmd_site`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_site.py
def test_build_site_writes_a_page_and_json_per_report():
    rows = [_row("p1", "Lepari")]
    site = build_site(rows, CLEAN, POINTS, 0.4385, METRICS,
                      reports={"p1": _report()}, previous_index=None, **STAMP)
    assert "players/lepari/index.html" in site
    assert "api/players/lepari.json" in site


def test_build_site_links_players_once_pages_exist():
    rows = [_row("p1", "Lepari")]
    site = build_site(rows, CLEAN, POINTS, 0.4385, METRICS,
                      reports={"p1": _report()}, previous_index=None, **STAMP)
    assert '<a href="/players/lepari/">' in site["index.html"].decode("utf-8")


def test_build_site_writes_redirects_only_when_a_slug_moved():
    rows = [_row("p1", "Lepari")]
    without = build_site(rows, CLEAN, POINTS, 0.4385, METRICS,
                         reports={"p1": _report()},
                         previous_index={"players": [
                             {"slug": "lepari", "player_id": "p1"}]}, **STAMP)
    assert "_redirects" not in without

    moved = build_site(rows, CLEAN, POINTS, 0.4385, METRICS,
                       reports={"p1": _report()},
                       previous_index={"players": [
                           {"slug": "old-name", "player_id": "p1"}]}, **STAMP)
    assert "/players/old-name/ /players/lepari/ 301" in \
        moved["_redirects"].decode("utf-8")


def test_every_html_page_still_carries_the_caveats_with_player_pages():
    site = build_site([_row("p1", "Lepari")], CLEAN, POINTS, 0.4385, METRICS,
                      reports={"p1": _report()}, previous_index=None, **STAMP)
    missing = [p for p, html in _html_pages(site).items()
               if "too few games to call" not in html]
    assert missing == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_site.py -k build_site -v`
Expected: FAIL, `TypeError: build_site() got an unexpected keyword argument 'reports'`

- [ ] **Step 3: Change `build_site`**

Replace the `build_site` written in Task 7 with this. The two new arguments
default to `None`, so every Task 7 test still passes unchanged.

```python
def build_site(
    rows: Sequence[ScanRow],
    coverage: Coverage,
    tier_points: Dict[str, float],
    scale: float,
    fit_metrics: Dict[str, float],
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
    reports=None,
    previous_index=None,
) -> Dict[str, bytes]:
    """Every file the published site is made of. Paths are relative, no leading slash."""
    stamp = dict(window=window, built_at=built_at, fitted_at=fitted_at,
                 sample_size=sample_size)
    slugs = assign_slugs(rows)
    reports = reports or {}
    # Only link a player whose page this build actually writes.
    linked = {pid: slug for pid, slug in slugs.items() if pid in reports}

    files = {
        "index.html": index_page(rows, coverage, linked, **stamp),
        "about/index.html": about_page(tier_points, scale, fit_metrics, **stamp),
        "_headers": headers(),
        "api/scan.json": scan_json(rows, coverage, slugs, **stamp),
        "api/model.json": model_json(tier_points, scale, fit_metrics,
                                     fitted_at=fitted_at, sample_size=sample_size),
        "api/index.json": index_json(rows, slugs, **stamp),
    }
    for player_id, report in reports.items():
        slug = slugs.get(player_id) or slugify(report.nick)
        files["players/%s/index.html" % slug] = player_page(report, **stamp)
        files["api/players/%s.json" % slug] = player_json(report, slug=slug, **stamp)

    moved = redirects(previous_index, slugs)
    if moved:
        files["_redirects"] = moved

    return {path: text.encode("utf-8") for path, text in files.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_site.py -v`
Expected: PASS, including every Task 7 test unchanged

- [ ] **Step 5: Write the failing CLI test**

```python
# add to tests/test_cli.py
def test_site_command_writes_a_player_page_with_players(
    monkeypatch, tmp_path, scan_bundle_path
):
    client = _ScanClient([_scan_match(i) for i in range(60)])
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: client)
    monkeypatch.setattr("gibhub.cli._report_for",
                        lambda client, bundle, player_id, args, cache: None)
    out = tmp_path / "_site"

    code = main(["--bundle", scan_bundle_path, "site", "--out", str(out),
                 "--min-games", "50", "--players"])

    assert code == 0
```

This test asserts only that the flag is accepted and the build completes with
the report fetch stubbed out; the page content is already covered in
`tests/test_site.py`. Replace the stub with a real `PlayerReport` if you want a
stronger assertion, building one the way `_report()` does in `tests/test_site.py`.

- [ ] **Step 6: Wire it into `cmd_site`**

Add the flag to the `site` subparser:

```python
    site_cmd.add_argument(
        "--players", action="store_true",
        help="also render a page per scanned player. Costs one profile, spider "
             "and match listing fetch each, so roughly 155 sets of calls.")
```

and, in `cmd_site`, between the `tier_coverage` call and `build_site`:

```python
    reports = {}
    previous_index = None
    if args.players:
        cache = MatchCache(args.cache)
        for row in rows:
            report = _report_for(client, bundle, row.player_id, args, cache)
            if report is not None:
                reports[row.player_id] = report
        previous_path = os.path.join(args.out, "api", "index.json")
        if os.path.exists(previous_path):
            with open(previous_path, "r", encoding="utf-8") as handle:
                previous_index = json.load(handle)
```

`write_site` deletes `args.out` before writing, so read the previous
`index.json` **before** calling it — which the order above does. Add
`import json` to `gibhub/cli.py` if it is absent, and confirm `MatchCache` and
`_report_for` are already imported there.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add gibhub/site.py gibhub/cli.py tests/test_site.py tests/test_cli.py
git commit -m "feat(site): render a page per player behind --players"
```

---

## Task 16: Turn player pages on in the workflow

**Files:**
- Modify: `.github/workflows/site.yml`
- Modify: `README.md`

- [ ] **Step 1: Add the flag to the build step**

```yaml
      - run: python3 -m gibhub.cli site --out _site --range 1y --players
```

- [ ] **Step 2: Run the workflow by hand and time it**

Trigger from the Actions tab. Note the runtime against the phase 1 baseline. If
it has grown by more than a few minutes, the listing calls are the cause: say
so in the commit message rather than leaving the next person to find it.

- [ ] **Step 3: Update the README's published-site table**

```markdown
| `/api/players/<slug>.json` | one player's verdict |
```

and add to the prose: player pages live at `/players/<slug>/`, keyed off the
nick, and a renamed player's old URL redirects to the new one.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/site.yml README.md
git commit -m "ci: publish player pages, and say so in the README"
```

---

## Notes for whoever runs this

- **Do not add a dependency.** No Jinja, no PyYAML, no `requests`. If a task
  seems to need one, the design is wrong; raise it.
- **`site.py` must stay pure.** If you find yourself importing `os`, `time` or
  `urllib` into it, the I/O belongs in `cli.py`.
- **The caveat guard test is not boilerplate.** It is the one test standing
  between a public table of verdicts and a reader who thinks `KEEP` means
  "correctly tiered". If it fails, fix the page, never the test.
- **The tier order is S > E > A > B > C > D.** Never sort tiers alphabetically.
