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
