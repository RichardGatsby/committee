# Publishing the verdicts — Design

Date: 2026-09-19
Status: Approved, not implemented.

## Purpose

Put the scan and the model where readers and the wider ET:Legacy 3v3 crowd
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
  would hit gibhub.gg once per visitor; it buys freshness a reader does not
  need.
- **Fully public.** Indexed, linkable, part of the community record. This raises
  the bar on caveats — see "What every verdict page must carry".
- **GitHub Actions on a cron.** Free minutes are unmetered on public repos, and
  the build does not depend on anyone's laptop being on.
- **Player URLs key off the nick**, with the UUID in the JSON.
- **Served from Cloudflare Pages**, built by Actions.

## Host: Cloudflare Pages

The site is served from a `*.pages.dev` subdomain. The free tier covers
unlimited bandwidth and 500 deployments a month against a daily build's 30.
A custom domain can go in front of it later without changing anything else.

Three things decided it over GitHub Pages, which was the other candidate:

- **`_redirects`.** Cloudflare reads one; GitHub Pages has no equivalent. Player
  URLs key off the nick, so a rename needs a redirect or it leaves a dead link.
- **The host does not care whether the repo is public.** GitHub Pages serves
  from a public repo only, unless you pay. Decoupling the two leaves repo
  visibility a free choice rather than a consequence of where the site lives.
- **Workers sit next to it**, which is the cheapest path to a live report
  endpoint if the pre-generated site ever stops being enough.

The repo is public today, which costs nothing either way: Actions minutes are
unmetered on public repos and 2,000 a month free on private ones, and a daily
build uses a fraction of either.

Deployment is `wrangler pages deploy` from the Actions runner, with
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in repo secrets. That does
not bend the repo's rule against committed tokens: a repo secret is not a
committed file. The deploy step runs only on `main` and on manual dispatch,
never on a pull request, so a fork cannot reach the secrets.

Netlify offers nothing Cloudflare does not.

### CORS is not automatic

Cloudflare Pages sends no `Access-Control-Allow-Origin` header unless told, so
the build must emit a `_headers` file:

    /api/*
      Access-Control-Allow-Origin: *

Without it the published JSON is readable in a browser tab but unusable from
anyone else's page, which is most of the point of publishing it. A test asserts
the file is in the build output.

### Redirects for renamed nicks

The build compares the slugs it is emitting against the previous `index.json`
and writes a `_redirects` line for any slug that has gone, rather than leaving a
dead URL behind. Phase 2 work, alongside the player pages that make slugs
matter.

## The API is the same build

`/api/*.json` written next to the HTML *is* the read-only public API: CORS-open
via `_headers`, CDN-cached, versioned by git, free, and impossible to knock
over. It cannot answer for a player the build did not cover, which is the whole
cost of not running a server.

## Architecture

A new module, `gibhub/site.py`, sits alongside `render.py` as a second pure
renderer:

    site.py         report/scan objects -> {path: bytes}   -- pure

It takes the objects `report.py` and `scan.py` already produce and returns a
dict mapping output path to file contents. No network, no filesystem, no clock —
the build date is passed in. `cli.py` writes the dict to disk under `--out`.

This keeps the one-direction dependency rule: `site.py` imports from `model`,
`report`, `scan` and `bundle`, and nothing imports `site.py` except `cli.py`.

Rejected: markdown dumped into a static site generator. It drags a second
language's toolchain into a stdlib-only repo and hands published prose to
a theme nobody chose. Rejected too: a JavaScript app fetching the JSON
client-side. The pages would stop working with JavaScript off, and the HTML
would become a second implementation of the same rendering.

### Output layout

    /                        the scan table, ranked by effect size
    /about/                  the model, the tier order, the limitations
    /_headers                CORS for /api/*
    /api/scan.json           the scan
    /api/model.json          coefficients, fit metrics, fit date
    /api/index.json          manifest: build time, window, players, slug -> UUID
    /players/<slug>/         one player's verdict            (phase 2)
    /api/players/<slug>.json                                 (phase 2)
    /_redirects              retired slugs -> current ones    (phase 2)

Slugs are the nick, lowercased, with anything outside `[a-z0-9-]` collapsed to a
hyphen. Two nicks slugging to the same string is resolved by appending the first
six characters of the UUID, and a test covers it. A rename would otherwise
break the old URL, so in phase 2 the build reads the previous `index.json`,
which carries both slug and UUID, and writes a `_redirects` line for every slug
that has moved.

## The build

One workflow, `.github/workflows/site.yml`, on a cron and on
`workflow_dispatch`.

    restore cache -> python3 -m gibhub.cli site --out _site
                  -> wrangler pages deploy _site -> save cache

Deployment needs `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from repo
secrets, and runs only on `main` and on dispatch.

**Cadence: daily, 05:00 UTC, plus the manual button.** The site shows nothing
that the last build did not produce. Tiers move rarely, but the verdict is
expected wins against actual wins, and matches land every day, so the actual
side drifts whether or not anyone runs the build.

A single day of 3v3 matches against a four-month window moves almost nothing on
its own. The reason the interval has to be short anyway is the cache:
`actions/cache` evicts an entry after seven days without a hit, so anything
looser than about five days means re-fetching all 262 MB every run. Daily keeps
it warm, and a warm cache means each build reads only the new matches.

Manual dispatch stays available and the build is idempotent, so a run between
crons costs nothing.

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
- 15 of 155 names on the tier list have no account mapped, mostly C and D, so absence
  from the table is not a clean bill

Every generated page also carries the fit date, the window and the sample size,
the same stamp the report footer already prints, so two screenshots taken a
month apart can be told apart.

## Testing

`site.py` is pure, so it tests like `render.py`: golden files, no network, no
clock. Beyond the golden files, four assertions earn their place:

1. Every generated HTML page contains the caveat block. This is the same shape
   of guard as the fixture test that fails if `ip` or `pw` reappears.
2. Every internal link resolves to a path the build actually emitted.
3. Every JSON file parses, and `index.json` lists exactly the player files
   written.
4. `_headers` is present and opens `/api/*` to cross-origin reads. It is one
   line of text nobody would notice going missing until someone else's page
   broke.

## Phasing

**Phase 1** — the scan index, the about page, `_headers`, `scan.json`,
`model.json`, `index.json`, and the workflow. No player pages. This is the
smallest thing that is useful to a reader and to anyone arguing with it.

**Phase 2** — per-player pages, their JSON, and `_redirects` for retired slugs,
once the build cost and the URL scheme have been watched working for a while.

## Known limitations of the published form

- A verdict on the site is as old as the last build. The build stamp says how
  old; nothing else prevents someone screenshotting a stale row.
- The site inherits every limitation of the tool, including that the approach is
  partly circular by design and that the alpha side wins 52.5% of matches with
  no way for the model to say so.
- A player who changes nick gets a new URL, and the old one 404s until phase 2
  writes the `_redirects` line.
