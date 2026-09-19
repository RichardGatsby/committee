"""The published site: report and scan objects in, {path: bytes} out.

Pure. No network, no filesystem, no clock -- the build time and the window are
passed in, so two builds of the same inputs produce identical bytes.
"""

import html as html_module
import re
from typing import Dict, Sequence

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
