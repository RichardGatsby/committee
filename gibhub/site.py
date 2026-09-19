"""The published site: report and scan objects in, {path: bytes} out.

Pure. No network, no filesystem, no clock -- the build time and the window are
passed in, so two builds of the same inputs produce identical bytes.
"""

import html as html_module
import json
import re
from typing import Dict, Sequence, Tuple

from .render import strip_colors
from .report import PlayerReport, guess_warning
from .scan import Coverage, ScanRow, UntieredRow

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


def player_options(players: Sequence[Tuple[str, str]]) -> str:
    """The <option> list for the header picker, from (nick, slug) pairs.

    Alphabetical by nick, case-insensitively: the index is ranked by effect
    size, which is no way to find somebody you already have in mind.
    """
    if not players:
        return ""
    options = ['<option value="">Jump to a player…</option>']
    for nick, slug in sorted(players, key=lambda p: p[0].lower()):
        options.append('<option value="/players/%s/">%s</option>'
                       % (escape(slug), escape(nick)))
    return "".join(options)


def page(title: str, body: str, players: Sequence[Tuple[str, str]] = ()) -> str:
    """One self-contained document. Nothing is fetched at view time."""
    options = player_options(players)
    picker = ""
    if options:
        # Inline, because the whole point of the site is that a page needs no
        # second request to work. location.assign keeps the back button honest.
        picker = (
            '<select aria-label="Jump to a player"'
            ' onchange="if(this.value)location.assign(this.value)">%s</select>'
            % options
        )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>%s</title>\n"
        "<style>%s</style>\n"
        '<nav><a href="/">Scan</a>'
        '<a href="/players/">Players</a>'
        '<a href="/gaps/">Missing tiers</a>'
        '<a href="/about/">How this works</a>%s</nav>\n'
        "%s\n"
        "</html>\n"
    ) % (escape(title), STYLE, picker, body)


def caveat_block(
    coverage: Coverage,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
    scope: str = "table",
) -> str:
    """What a stranger has to know before reading a verdict as a fact."""
    parts = ['<section class="caveats">']
    if coverage.warning:
        parts.append("<p><strong>%s</strong> %d of the %d players in this window "
                     "had no committee tier.</p>"
                     % (escape(coverage.warning), coverage.players_guessed,
                        coverage.players_seen))
    if scope == "player":
        parts.append(
            "<p>A verdict is only as good as the number of matches behind it. "
            "Few games and a big gap still reads as <code>KEEP</code>, because "
            "the evidence is thin - not because the tier is right.</p>")
        parts.append(
            "<p>Tiers have no history here. Every match above is scored "
            "against the tier held today, so someone promoted recently looks "
            "like they were beating the new tier all year.</p>")
    else:
        parts.append(
            "<p><code>KEEP</code> means too few games to call, not correctly "
            "tiered. A row with few games and a large effect reads as "
            "<code>KEEP</code> because the evidence is thin, not because the "
            "tier is right.</p>")
        parts.append(
            "<p>Some committee names still have no account mapped, mostly C "
            "and D, so a player missing from this table has not been cleared - "
            "they have not been checked.</p>")
    parts.append(
        '<p class="stamp">Window %s. Built %s from a model fitted %s on %d '
        "matches.</p>" % (escape(window), escape(built_at), escape(fitted_at),
                          sample_size))
    parts.append("</section>")
    return "\n".join(parts)


# What each verdict means, and which way it points. OVER means the tier is too
# low, which reads backwards to anyone meeting the table for the first time.
LABELS = (
    ("CLEARLY OVER", "wins <strong>more</strong> than the tier predicts; luck "
                     "explains it less than 1 time in 100", "MOVE UP"),
    ("OVER", "same, less than 1 time in 20", "CONSIDER MOVING UP"),
    ("ON TIER", "within what luck produces", "KEEP"),
    ("UNDER", "wins <strong>fewer</strong>, less than 1 time in 20",
     "CONSIDER MOVING DOWN"),
    ("CLEARLY UNDER", "wins fewer, less than 1 time in 100", "MOVE DOWN"),
)


def legend() -> str:
    rows = "".join(
        "<tr><td><code>%s</code><td>%s<td><code>%s</code>"
        % (escape(label), meaning, escape(decision))
        for label, meaning, decision in LABELS)
    return (
        "<table><thead><tr><th>Label<th>Meaning<th>Decision</thead>"
        "<tbody>%s</tbody></table>\n"
        "<p><code>OVER</code> means the tier is too <strong>low</strong> - they "
        "beat it. <code>UNDER</code> means it is too <strong>high</strong>. The "
        "target tier comes off the points scale rather than the alphabet, so "
        '"up" from A is E, not S.</p>' % rows)


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
    players: Sequence[Tuple[str, str]] = ()) -> str:
    shown = [r for r in rows if r.label != "ON TIER"]
    body = ["<h1>Where a record and a tier disagree</h1>"]
    body.append(caveat_block(coverage, window=window, built_at=built_at,
                             fitted_at=fitted_at, sample_size=sample_size))
    if not shown:
        body.append("<p>No player's record differs from their tier by more "
                    "than luck.</p>")
    else:
        body.append(legend())
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
    return page("3v3 tiering evidence", "\n".join(body), players)


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
    players: Sequence[Tuple[str, str]] = ()) -> str:
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
    return page("How this works", "\n".join(body), players)


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
    reports=None,
    previous_index=None,
    untiered_rows=(),
) -> Dict[str, bytes]:
    """Every file the published site is made of. Paths are relative, no leading slash."""
    stamp = dict(window=window, built_at=built_at, fitted_at=fitted_at,
                 sample_size=sample_size)
    slugs = assign_slugs(rows)
    reports = reports or {}
    # Only link a player whose page this build actually writes.
    linked = {pid: slug for pid, slug in slugs.items() if pid in reports}
    # The header picker offers the same set: a dead option is worse than none.
    picker = sorted((row.nick, linked[row.player_id]) for row in rows
                    if row.player_id in linked)

    files = {
        "index.html": index_page(rows, coverage, linked, players=picker,
                                 **stamp),
        "about/index.html": about_page(tier_points, scale, fit_metrics,
                                       players=picker, **stamp),
        "_headers": headers(),
        "api/scan.json": scan_json(rows, coverage, slugs, **stamp),
        "api/model.json": model_json(tier_points, scale, fit_metrics,
                                     fitted_at=fitted_at, sample_size=sample_size),
        "api/index.json": index_json(rows, slugs, **stamp),
        # Always published, even when empty: the nav links to it, and "nothing
        # is missing" is itself worth stating.
        "gaps/index.html": gaps_page(untiered_rows, coverage,
                                     players=picker, **stamp),
        # Always published, like gaps: the nav links to it, and a build with no
        # player pages should say so rather than 404.
        "players/index.html": players_page(rows, linked, coverage,
                                           players=picker, **stamp),
        "api/gaps.json": gaps_json(untiered_rows, coverage, **stamp),
    }
    for player_id, report in reports.items():
        slug = slugs.get(player_id) or slugify(report.nick)
        files["players/%s/index.html" % slug] = player_page(
            report, players=picker, **stamp)
        files["api/players/%s.json" % slug] = player_json(report, slug=slug, **stamp)

    moved = redirects(previous_index, slugs)
    if moved:
        files["_redirects"] = moved

    return {path: text.encode("utf-8") for path, text in files.items()}


def _display_nick(report: PlayerReport) -> str:
    """The name to show. Same rule to_markdown uses, so the two agree."""
    return strip_colors(report.nick) or report.discord_nick


def player_page(
    report: PlayerReport,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
    players: Sequence[Tuple[str, str]] = ()) -> str:
    nick = _display_nick(report)
    tier = report.current_tier or "none"
    body = ["<h1>%s</h1>" % escape(nick)]

    # Above everything, where a cropped screenshot still catches it.
    warning = guess_warning(report.source_counts)
    if warning:
        body.append(
            '<p class="caveats"><strong>%s</strong> %d of the %d players in '
            "these matches had no committee tier.</p>"
            % (escape(warning), report.players_guessed, report.players_seen))

    body.append(
        "<p><strong>Won %d of %d matches</strong> in this window, holding "
        "tier %s. Weighing the tiers on both sides of each of those matches, "
        "the model expected about %.0f wins - so %s is %+.1f against what the "
        "tiers predicted.</p>"
        % (report.actual_wins, report.decided, escape(tier),
           report.expected_wins, escape(nick), report.delta))

    if report.label == "ON TIER":
        body.append("<h2>%s</h2>" % escape(report.recommendation))
        body.append("<p>The record is what tier %s predicts, within what luck "
                    "alone produces over %d matches.</p>"
                    % (escape(tier), report.decided))
    else:
        over = report.label.endswith("OVER")
        body.append(
            "<h2>The tier looks too %s</h2>" % ("low" if over else "high"))
        body.append(
            "<p>%s wins <strong>%s</strong> than tier %s predicts, so the tier "
            "is too %s. %s</p>"
            % (escape(nick), "more" if over else "fewer", escape(tier),
               "low" if over else "high",
               "Luck alone explains a gap this big less than 1 time in 100."
               if report.label.startswith("CLEARLY")
               else "Luck alone explains a gap this big less than 1 time in "
                    "20."))
        body.append("<p><strong>%s</strong></p>" % escape(report.recommendation))

    favoured = report.stack_wins + report.upset_losses
    underdog = report.upset_wins + report.underdog_losses
    other = report.decided - favoured - underdog
    body.append("<h2>How those %d matches went</h2>" % report.decided)
    body.append(
        '<table><thead><tr><th>Going in<th class="num">Matches'
        '<th class="num">Won<th class="num">Lost</thead><tbody>'
        '<tr><td>Favoured<td class="num">%d<td class="num">%d<td class="num">%d'
        '<tr><td>Underdog<td class="num">%d<td class="num">%d<td class="num">%d'
        '<tr><td>Evenly matched<td class="num">%d<td class="num">-'
        '<td class="num">-'
        "</tbody></table>"
        % (favoured, report.stack_wins, report.upset_losses,
           underdog, report.upset_wins, report.underdog_losses, other))
    body.append(
        "<p>Favoured means the model gave their team better than an even "
        "chance before the match. Evenly matched games are not split here "
        "because neither side was favoured. This split is worth reading "
        "alongside the verdict: a record built on favoured games is not the "
        "same as one built against the odds, and the totals above hide the "
        "difference.</p>")

    body.append(caveat_block(
        Coverage(report.players_seen, report.players_guessed,
                 (report.players_guessed / report.players_seen)
                 if report.players_seen else 0.0),
        window=window, built_at=built_at, fitted_at=fitted_at,
        sample_size=sample_size, scope="player"))
    return page("%s - 3v3 tiering evidence" % nick, "\n".join(body), players)


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
        "nick": _display_nick(report),
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


def gaps_page(
    rows: Sequence[UntieredRow],
    coverage: Coverage,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
    players: Sequence[Tuple[str, str]] = ()) -> str:
    """The work list: who has no committee tier, busiest first."""
    body = ["<h1>Players with no committee tier</h1>"]
    body.append(
        "<p>Every one of these had a tier guessed for them from their shrunken "
        "UTRO, capped at A. A guess is not a committee decision, and guesses "
        "are the largest source of false signal in the scan - so the players "
        "at the top of this list are the ones whose tiers would improve the "
        "verdicts most.</p>")
    body.append(caveat_block(coverage, window=window, built_at=built_at,
                             fitted_at=fitted_at, sample_size=sample_size))

    if not rows:
        body.append("<p>Every player in this window holds a committee tier. "
                    "Nothing to fill in.</p>")
    else:
        cells = []
        for row in rows:
            cells.append(
                '<tr><td>%s<td class="num">%d<td class="num">%s<td class="num">%s'
                % (escape(row.nick), row.games, escape(row.guessed_tier),
                   ("%.3f" % row.utro) if row.utro is not None else "-"))
        body.append(
            '<table><thead><tr><th>Player<th class="num">Games'
            '<th class="num">Guessed as<th class="num">UTRO</thead>'
            "<tbody>%s</tbody></table>" % "".join(cells))
        body.append(
            "<p><strong>Guessed as</strong> is the tier the model used for "
            "them anyway - a guess is not a blank, it counts toward their "
            "team's points in every match they played. <strong>Games</strong> "
            "is matches in this window, so the top of the list is where a "
            "guess does the most damage. <strong>UTRO</strong> is what the "
            "guess was made from; a blank one means the player was below the "
            "leaderboard's round floor and got the median band instead.</p>\n"
            '<p class="stamp">Account ids for recording a decision are in '
            '<a href="/api/gaps.json">gaps.json</a>.</p>')
    return page("Players with no committee tier", "\n".join(body), players)


def gaps_json(
    rows: Sequence[UntieredRow],
    coverage: Coverage,
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
        },
        "untiered": [{
            "player_id": r.player_id,
            "nick": r.nick,
            "games": r.games,
            "guessed_tier": r.guessed_tier,
            "utro": round(r.utro, 4) if r.utro is not None else None,
        } for r in rows],
    })


def players_page(
    rows: Sequence[ScanRow],
    slugs: Dict[str, str],
    coverage: Coverage,
    *,
    window: str,
    built_at: str,
    fitted_at: str,
    sample_size: int,
    players: Sequence[Tuple[str, str]] = (),
) -> str:
    """Every player with a page of their own.

    The scan index lists only the players whose record disagrees with their
    tier, so without this one a player drops out of reach the moment their
    verdict settles to ON TIER.
    """
    listed = sorted((r for r in rows if r.player_id in slugs),
                    key=lambda r: slugs[r.player_id])
    body = ["<h1>Every player scored</h1>"]
    body.append(
        "<p>The scan lists only the records that disagree with the tier held. "
        "This is all of them, agreeing or not.</p>")
    body.append(caveat_block(coverage, window=window, built_at=built_at,
                             fitted_at=fitted_at, sample_size=sample_size))

    if not listed:
        body.append("<p>This site was built without player pages. Run the "
                    "build with <code>--players</code> to publish them.</p>")
    else:
        cells = "".join(
            '<tr><td><a href="/players/%s/">%s</a><td>%s'
            '<td class="num">%d<td class="num">%+.1f<td>%s'
            % (escape(slugs[r.player_id]), escape(r.nick), escape(r.tier),
               r.games, r.per_100, escape(r.recommendation))
            for r in listed)
        body.append(
            '<table><thead><tr><th>Player<th>Tier<th class="num">Games'
            '<th class="num">Per 100<th>Decision</thead><tbody>%s</tbody>'
            "</table>" % cells)
        body.append("<p>%d players, alphabetically.</p>" % len(listed))
    return page("Every player scored", "\n".join(body), players)
