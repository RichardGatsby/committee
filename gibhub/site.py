"""The published site: report and scan objects in, {path: bytes} out.

Pure. No network, no filesystem, no clock -- the build time and the window are
passed in, so two builds of the same inputs produce identical bytes.
"""

import html as html_module
import json
import re
from typing import Dict, Sequence

from .report import PlayerReport, guess_warning
from .scan import Coverage, ScanRow

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
                     "had no committee tier.</p>"
                     % (escape(coverage.warning), coverage.players_guessed,
                        coverage.players_seen))
    parts.append(
        "<p><code>KEEP</code> means too few games to call, not correctly "
        "tiered. A row with few games and a large effect reads as "
        "<code>KEEP</code> because the evidence is thin, not because the tier "
        "is right.</p>")
    parts.append(
        "<p>Some committee names still have no account mapped, mostly C and D, "
        "so a player missing from this table has not been cleared - they have "
        "not been checked.</p>")
    parts.append(
        '<p class="stamp">Window %s. Built %s from a model fitted %s on %d '
        "matches.</p>" % (escape(window), escape(built_at), escape(fitted_at),
                          sample_size))
    parts.append("</section>")
    return "\n".join(parts)


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


TIER_ORDER = ("S", "E", "A", "B", "C", "D")

LIMITATIONS = (
    "The approach is partly circular by design: it asks whether a record is "
    "consistent with the tier held, not what tier a player deserves in the "
    "absolute.",
    "Tiers have no history, so past matches are scored against today's tiers. "
    "A recently promoted player looks like they were overperforming all year.",
    "The alpha side wins 52.5% of matches and the model cannot express that.",
    "A player with no committee tier gets one imputed from their shrunken "
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
        "<p>Each tier is worth fixed points set by the committee. A team's "
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


def _dump(payload) -> str:
    """Stable bytes: an unchanged scan must not churn the deploy."""
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


# Cloudflare Pages sends no CORS header unless told. Without this the published
# JSON is readable in a browser tab and unusable from anyone else's page.
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


def player_page(
    report: PlayerReport,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
) -> str:
    body = ["<h1>%s</h1>" % escape(report.nick)]

    # Above the headline, where a cropped screenshot still catches it.
    warning = guess_warning(report.source_counts)
    if warning:
        body.append(
            '<p class="caveats"><strong>%s</strong> %d of the %d players in '
            "this window had no committee tier.</p>"
            % (escape(warning), report.players_guessed, report.players_seen))

    body.append(
        "<p><strong>Expected %.2f wins, actual %d &mdash; %+.2f &rarr; %s"
        "</strong></p>" % (report.expected_wins, report.actual_wins,
                           report.delta, escape(report.label)))
    body.append("<h2>%s</h2>" % escape(report.recommendation))
    body.append(
        "<p>Tier %s over %d decided matches. Won %d while favoured, lost %d as "
        "the underdog: a record built entirely on stacked teams reads the same "
        "as one built against the odds unless you look here.</p>"
        % (escape(report.current_tier or "none"), report.decided,
           report.stack_wins, report.underdog_losses))
    body.append(
        "<p>Won %d as the underdog, lost %d while favoured.</p>"
        % (report.upset_wins, report.upset_losses))
    body.append(caveat_block(
        Coverage(report.players_seen, report.players_guessed,
                 (report.players_guessed / report.players_seen)
                 if report.players_seen else 0.0),
        window=window, built_at=built_at, fitted_at=fitted_at,
        sample_size=sample_size))
    return page("%s - 3v3 tiering evidence" % report.nick, "\n".join(body))


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
        "per_100": round(report.per_100, 2),
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
