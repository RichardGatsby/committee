"""Command line entry point."""

import argparse
import os
import sys

from .api import ApiError, Client
from .build import build_bundle
from .bundle import DEFAULT_PATH, BundleMissing, load, save
from .cache import MatchCache
from .categories import POLAND, REPORT_DEFAULT, parse_selection
from .fetch import AmbiguousPlayer, PlayerNotFound, fetch_player_data, resolve_player
from .model import TIERS, TIER_POINTS
from .render import strip_colors, to_csv, to_json, to_markdown, to_scan_csv, to_scan_table
from .report import build_report
from .scan import scan

PAGE_SIZE = 100


def make_client(args) -> Client:
    return Client(token=os.environ.get("GIBHUB_TOKEN"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="committee", description="Tiering evidence for 3v3 gathers."
    )
    parser.add_argument("--bundle", default=DEFAULT_PATH, help="path to coefficients.json")
    parser.add_argument("--cache", default=".cache", help="match cache directory")
    sub = parser.add_subparsers(dest="command", required=True)

    player = sub.add_parser("player", help="report on one player")
    player.add_argument("player", help="name, discord nick, or player UUID")
    player.add_argument(
        "--matches", type=int, default=0, metavar="N",
        help="cap how many matches to read (default: 0 = every match in the "
             "window). A cap takes the most recent N, which can change the verdict.")
    player.add_argument("--channel")
    player.add_argument(
        "--range", default="4m",
        help="rolling window like 4m or 1y (default: 4m). Ignored when --from is set.")
    player.add_argument(
        "--from", dest="from_", metavar="YYYY-MM-DD",
        help="inclusive start date, instead of the rolling --range window.")
    player.add_argument("--to", metavar="YYYY-MM-DD")
    player.add_argument(
        "--only", action="append", metavar="TYPE",
        help="restrict to a kind of game; repeat for several. legacy, poland, "
             "other, gathers (all three), cup, team. Omit for everything.")
    player.add_argument(
        "--with-poland", action="store_true", dest="with_poland",
        help="also count Poland gathers, which are left out by default")
    player.add_argument(
        "--extremes", type=int, default=3, metavar="N",
        help="also table the N biggest underdog wins and worst losses while "
             "favoured, with both lineups (default: 3; 0 to hide)")
    player.add_argument("--format", choices=["md", "json", "csv"], default="md")

    bulk = sub.add_parser("bulk", help="report on many players as CSV")
    selector = bulk.add_mutually_exclusive_group(required=True)
    selector.add_argument("--tier", action="append")
    selector.add_argument("--players", help="file with one name or UUID per line")
    bulk.add_argument("--matches", type=int, default=0)
    bulk.add_argument("--range", default="4m")
    bulk.add_argument("--from", dest="from_")
    bulk.add_argument("--only", action="append")
    bulk.add_argument("--with-poland", action="store_true", dest="with_poland")
    bulk.add_argument("--to")
    bulk.add_argument("--out")

    scan_cmd = sub.add_parser(
        "scan", help="score every tiered player at once and rank the mis-tiered")
    scan_cmd.add_argument("--range", default="1y")
    scan_cmd.add_argument("--from", dest="from_", metavar="YYYY-MM-DD")
    scan_cmd.add_argument("--to", metavar="YYYY-MM-DD")
    scan_cmd.add_argument(
        "--min-games", type=int, default=50, dest="min_games",
        help="ignore players with fewer games in the window (default: 50)")
    scan_cmd.add_argument("--only", action="append", metavar="TYPE")
    scan_cmd.add_argument(
        "--with-poland", action="store_true", dest="with_poland",
        help="also count Poland gathers, which are left out by default")
    scan_cmd.add_argument(
        "--all", action="store_true",
        help="list every player, not only those whose record differs from their tier")
    scan_cmd.add_argument("--out", metavar="FILE", help="write the full table as CSV")

    fit = sub.add_parser("fit", help="show or refit the model")
    fit.add_argument("--refit", action="store_true")
    fit.add_argument(
        "--tier-channel", action="append", dest="tier_channel",
        help="restrict the tier index to these channels; repeat for multiple "
             "(e.g. --tier-channel Events). Matches a channel id or a substring "
             "of its name. Omit to use every channel's tiers.",
    )
    fit.add_argument("--to")
    fit.add_argument("--limit", type=int)
    fit.add_argument(
        "--overrides", metavar="FILE",
        help="committee-supplied tiers the API does not have, one 'name = TIER' "
             "per line (# comments allowed). Names are resolved through player "
             "search; UUIDs are used as-is. Overrides beat every other source and "
             "are never capped.",
    )
    fit.add_argument(
        "--impute-max", dest="impute_max", default="A", metavar="TIER",
        help="strongest tier an untiered player may be imputed as (default: A). "
             "Applied by measured strength, so capping at A also excludes E. "
             "Pass 'none' to leave imputation uncapped.",
    )
    fit.add_argument(
        "--points", nargs="?", const="default", metavar="S=5,E=4,...",
        help="fix the tier values instead of fitting six free coefficients; the "
             "only fitted parameter is then the log-odds per point of team "
             "advantage. Bare --points uses %s."
             % ",".join("%s=%g" % (t, TIER_POINTS[t]) for t in ("S", "E", "A", "B", "C", "D")),
    )

    return parser


def categories_for(args):
    """The categories a command counts, honouring --only and --with-poland."""
    chosen = list(parse_selection(getattr(args, "only", None)))
    if getattr(args, "with_poland", False):
        if not chosen:
            chosen = list(REPORT_DEFAULT)
        if POLAND not in chosen:
            chosen.append(POLAND)
    return chosen


def window_label(args):
    """How the report should describe the slice of history it covers."""
    start = None if (getattr(args, "from_", None) or "none").lower() == "none" else args.from_
    end = getattr(args, "to", None)
    if start and end:
        return "%s to %s" % (start, end)
    if start:
        return "%s onwards" % start
    if end:
        return "up to %s" % end
    return "last %s" % args.range if args.range else "all time"


def _report_for(client, bundle, player_id, args, cache):
    start = None if (getattr(args, "from_", None) or "none").lower() == "none" else args.from_
    profile, spider, details, available = fetch_player_data(
        client,
        player_id,
        matches=args.matches or None,
        range_=args.range if not start else None,
        from_=start,
        to=getattr(args, "to", None),
        channel=getattr(args, "channel", None),
        cache=cache,
    )
    provenance = {
        "fitted_at": bundle.fitted_at,
        "data_cutoff": bundle.data_cutoff,
        "sample_size": bundle.sample_size,
        "window": window_label(args),
        "tier_channels": bundle.tier_channels,
        "tier_source": (", ".join(sorted(bundle.channel_names.values()))
                        if bundle.tier_channels else "all channels"),
        "impute_max": bundle.impute_max,
        "available": available,
        "fetched": len(details),
    }
    return build_report(
        profile, spider, details, bundle.index(), bundle.coefficients, provenance,
        tier_points=bundle.tier_points or None,
        only=categories_for(args),
        tier_channel_ids=set(bundle.channel_names) if bundle.tier_channels else None,
    )


def cmd_player(args) -> int:
    bundle = load(args.bundle)
    client = make_client(args)
    cache = MatchCache(args.cache)

    player_id = resolve_player(client, args.player, exact=True)
    report = _report_for(client, bundle, player_id, args, cache)

    if args.format == "json":
        print(to_json(report))
    elif args.format == "csv":
        print(to_csv([report]), end="")
    else:
        print(to_markdown(report, extremes=args.extremes), end="")
    return 0


def select_players(client, args):
    """The players a bulk run covers: a tier roster, or a file of names."""
    if args.players:
        player_ids = []
        with open(args.players, "r", encoding="utf-8") as handle:
            for line in handle:
                term = line.strip()
                if not term or term.startswith("#"):
                    continue
                player_ids.append(resolve_player(client, term, exact=True))
        return player_ids

    player_ids = []
    for tier in args.tier:
        for row in client.paginate(
            "/players", {"size": "3v3", "tier": tier}, page_size=PAGE_SIZE
        ):
            if row["player_id"] not in player_ids:
                player_ids.append(row["player_id"])
    return player_ids


def cmd_bulk(args) -> int:
    bundle = load(args.bundle)
    client = make_client(args)
    cache = MatchCache(args.cache)

    args.channel = None

    reports = [
        _report_for(client, bundle, player_id, args, cache)
        for player_id in select_players(client, args)
    ]

    text = to_csv(reports)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("wrote %d rows to %s" % (len(reports), args.out))
    else:
        print(text, end="")
    return 0


def load_overrides(client, path):
    """Read a 'name = TIER' file into {player_id: tier}, resolving names."""
    if not path:
        return {}
    overrides = {}
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            term, sep, tier = line.partition("=")
            tier = tier.strip().upper()
            if not sep or tier not in TIERS:
                raise ValueError(
                    "%s line %d: expected 'name = TIER' with TIER one of %s, got %r"
                    % (path, number, ", ".join(TIERS), line))
            overrides[resolve_player(client, term.strip(), exact=True)] = tier
    return overrides


def parse_impute_max(spec):
    """A tier name, or None when uncapped."""
    if not spec or spec.lower() == "none":
        return None
    tier = spec.strip().upper()
    if tier not in TIERS:
        raise ValueError("unknown tier %r for --impute-max (expected one of %s, or none)"
                         % (tier, ", ".join(TIERS)))
    return tier


def parse_points(spec):
    """None, "default", or "S=5,E=4,A=3,B=2,C=1,D=0" into a tier -> points dict."""
    if not spec:
        return None
    if spec == "default":
        return dict(TIER_POINTS)
    points = {}
    for part in spec.split(","):
        tier, _, value = part.partition("=")
        tier = tier.strip().upper()
        if tier not in TIERS:
            raise ValueError("unknown tier %r in --points (expected one of %s)"
                             % (tier, ", ".join(TIERS)))
        points[tier] = float(value)
    missing = [t for t in TIERS if t not in points]
    if missing:
        raise ValueError("--points is missing a value for: %s" % ", ".join(missing))
    return points


def cmd_scan(args) -> int:
    bundle = load(args.bundle)
    # scan() scores only players holding a committee tier. Without one there is
    # nobody to score, and an empty table would read as "everybody is correctly
    # tiered" rather than "nothing was checked".
    if not bundle.overrides:
        sys.stderr.write(
            "this bundle carries no committee tier list, so scan has nobody to "
            "score.\nRefit with --overrides, for example:\n"
            "  python3 tools/resolve_tierlist.py "
            "data/tierlist-events-3v3.txt overrides.txt\n"
            "  python3 -m gibhub.cli fit --refit --tier-channel Events --points "
            "--impute-max A --overrides overrides.txt\n"
        )
        return 1
    client = make_client(args)

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

    rows = scan(matches, bundle.index(), bundle.coefficients, bundle.scale or 1.0,
                min_games=args.min_games, only=categories_for(args), nicks=nicks)

    print(to_scan_table(rows, show_all=args.all), end="")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(to_scan_csv(rows))
        print("\nwrote %d rows to %s" % (len(rows), args.out))
    return 0


def cmd_fit(args) -> int:
    if args.refit:
        bundle = build_bundle(
            make_client(args), to=args.to, limit=args.limit,
            tier_channels=args.tier_channel, points=parse_points(args.points),
            impute_max=parse_impute_max(args.impute_max),
            overrides=load_overrides(make_client(args), args.overrides),
        )
        save(bundle, args.bundle)
        print("wrote %s" % args.bundle)
    else:
        bundle = load(args.bundle)

    print("fitted_at:   %s" % bundle.fitted_at)
    print("data_cutoff: %s" % bundle.data_cutoff)
    print("samples:     %d" % bundle.sample_size)
    print("tier source: %s" % (", ".join(sorted(bundle.channel_names.values()))
                               if bundle.tier_channels else "all channels"))
    print("impute cap:  %s" % (bundle.impute_max or "none"))
    if bundle.overrides:
        print("overrides:   %d committee-supplied tier(s)" % len(bundle.overrides))
    print("metrics:     " + "  ".join(
        "%s=%.4f" % (key, value)
        for key, value in sorted(bundle.fit_metrics.items())
        if key != "samples"
    ))
    print("")
    if bundle.tier_points:
        print("fixed tier points, %.4f log-odds per point:" % bundle.scale)
        header = "  tier  points   log-odds   band utro"
    else:
        print("tier value (log-odds, higher is stronger):")
        header = "  tier           log-odds   band utro"
    print(header)
    for tier in sorted(TIERS, key=lambda t: -bundle.coefficients[TIERS.index(t)]):
        coefficient = bundle.coefficients[TIERS.index(tier)]
        band = bundle.bands.get(tier)
        points = ("%6.1f" % bundle.tier_points[tier]) if bundle.tier_points else "      "
        print("  %-4s %s   %+8.4f   %s"
              % (tier, points, coefficient, "%.3f" % band if band else "n/a"))
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "player":
            return cmd_player(args)
        if args.command == "bulk":
            return cmd_bulk(args)
        if args.command == "scan":
            return cmd_scan(args)
        return cmd_fit(args)
    except (BundleMissing, PlayerNotFound, AmbiguousPlayer, ApiError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
