# Publishing the committee's verdicts — Design

Date: 2026-09-19
Status: Approved, not implemented.

## Purpose

Put the scan and the model where the committee and the wider ET:Legacy 3v3 crowd
can read them without installing anything, at no cost, and publish the same
numbers as machine-readable JSON so anyone can argue with them using their own
tools.

The site is generated ahead of time from a scheduled build. Nobody visiting it
triggers a fetch against gibhub.gg.

## Decisions taken before design

Four questions were settled first, and the rest of this document follows from
them:

- **Pre-generated, not live.** A visitor reads what the last build produced.
  A live "type a name, get a report" service would need a warm 262 MB cache and
  would hit gibhub.gg once per visitor; it buys freshness the committee does not
  need.
- **Fully public.** Indexed, linkable, part of the community record. This raises
  the bar on caveats — see "What every verdict page must carry".
- **GitHub Actions on a cron.** Free minutes are unmetered on public repos, and
  the build does not depend on anyone's laptop being on.
- **Player URLs key off the nick**, with the UUID in the JSON.

## Host: GitHub Pages

Free for public repos, deploys from Actions with no second account and no
deploy token in repo secrets — which matters in a repo whose rule is that no
token belongs in any committed file. HTTPS and a custom domain are included.
Static files are served with `Access-Control-Allow-Origin: *`, so the published
JSON works as a cross-origin API without any further work.

Limits, as advertised at time of writing and worth re-checking before relying on
them: roughly 1 GB of site and a 100 GB/month soft bandwidth cap. A committee-
sized audience is three orders of magnitude short of that.

Cloudflare Pages is the migration if bandwidth ever matters or if the live
report service is ever wanted, since Workers sit next to it. It costs a second
account and an API token in repo secrets, so it is not the starting point.

Netlify offers nothing either of them does not.

## The API is the same build

`/api/*.json` written next to the HTML *is* the read-only public API: CORS-open,
CDN-cached, versioned by git, free, and impossible to knock over. It cannot
answer for a player the build did not cover, which is the whole cost of not
running a server.

## Architecture

A new module, `gibhub/site.py`, sits alongside `render.py` as a second pure
renderer:

    site.py         report/scan objects -> {path: bytes}   -- pure

It takes the objects `report.py` and `scan.py` already produce and returns a
dict mapping output path to file contents. No network, no filesystem, no clock —
the build date is passed in. `cli.py` writes the dict to disk under `--out`.

This keeps the one-direction dependency rule: `site.py` imports from `model`,
`report`, `scan` and `bundle`, and nothing imports `site.py` except `cli.py`.

Rejected: markdown dumped into Jekyll, which Pages renders for free. It drags
Ruby config into a stdlib-only repo and hands committee-facing prose to a theme
nobody chose. Rejected too: a JavaScript app fetching the JSON client-side. The
pages would stop working with JavaScript off, and the HTML would become a second
implementation of the same rendering.

### Output layout

    /                        the scan table, ranked by effect size
    /about/                  the model, the tier order, the limitations
    /api/scan.json           the scan
    /api/model.json          coefficients, fit metrics, fit date
    /api/index.json          manifest: build time, window, players, slug -> UUID
    /players/<slug>/         one player's verdict            (phase 2)
    /api/players/<slug>.json                                 (phase 2)

Slugs are the nick, lowercased, with anything outside `[a-z0-9-]` collapsed to a
hyphen. A rename breaks the old URL; `index.json` carries both slug and UUID, so
redirect stubs for old slugs can be generated later if it becomes a real
problem. Two nicks slugging to the same string is resolved by appending the
first six characters of the UUID, and a test covers it.

## The build

One workflow, `.github/workflows/site.yml`, on a cron and on
`workflow_dispatch`.

    restore cache -> python3 -m gibhub.cli site --out _site -> upload -> deploy

**Cadence: daily, 05:00 UTC.** Not weekly. `actions/cache` evicts an entry after
seven days without a hit, so a weekly cron sits exactly on the eviction line and
would periodically re-fetch every match. Daily keeps it warm and costs little,
since a warm cache means the build reads only new matches.

**The cache key must roll.** Cache entries are immutable once written, so a
fixed key would freeze the cache at its first contents. Write to a key carrying
the run id and restore with a `restore-keys` prefix, which is the standard
pattern for a cache that grows.

262 MB against the 10 GB per-repo allowance leaves room.

### Build cost against gibhub.gg

The scan is one sweep, so phase 1 is cheap. A per-player *report* is not: it
fetches that player's profile, spider and match listing separately. 155 player
pages means roughly 155 times a handful of listing calls per build, even with
every match detail a cache hit. That is the reason player pages are phase 2
rather than phase 1, and the reason the cron is daily rather than hourly.

The existing `User-Agent` already identifies the tool and points at the site it
reads from. Leave it that way.

## What every verdict page must carry

Publishing a table that names people as `MOVE DOWN` changes what the caveats are
for. Three notes from the README stop being footnotes and become part of the
page:

- the guessed-tier alarm, on any page showing a verdict, whether or not that
  particular verdict trips the 20% or 40% threshold
- `KEEP` means "too few games to call", not "correctly tiered" — a stranger
  reading the table has no way to know that
- 15 of 155 committee names have no account mapped, mostly C and D, so absence
  from the table is not a clean bill

Every generated page also carries the fit date, the window and the sample size,
the same stamp the report footer already prints, so two screenshots taken a
month apart can be told apart.

## Testing

`site.py` is pure, so it tests like `render.py`: golden files, no network, no
clock. Beyond the golden files, three assertions earn their place:

1. Every generated HTML page contains the caveat block. This is the same shape
   of guard as the fixture test that fails if `ip` or `pw` reappears.
2. Every internal link resolves to a path the build actually emitted.
3. Every JSON file parses, and `index.json` lists exactly the player files
   written.

## Phasing

**Phase 1** — the scan index, the about page, `scan.json`, `model.json`,
`index.json`, and the workflow. No player pages. This is the smallest thing that
is useful to the committee and to anyone arguing with it.

**Phase 2** — per-player pages and their JSON, once the build cost and the URL
scheme have been watched working for a while.

## Known limitations of the published form

- A verdict on the site is as old as the last build. The build stamp says how
  old; nothing else prevents someone screenshotting a stale row.
- The site inherits every limitation of the tool, including that the approach is
  partly circular by design and that the alpha side wins 52.5% of matches with
  no way for the model to say so.
- A player who changes nick gets a new URL and the old one 404s until a redirect
  stub is generated.
