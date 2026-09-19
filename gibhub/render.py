"""Pure rendering of a PlayerReport. No I/O, no fetching."""

import csv
import dataclasses
import io
import json
import re
from typing import Any, List, Optional, Sequence

from .categories import LABELS
from .report import ONE_TIER_GAMES, PlayerReport, guess_warning
from .scan import ScanRow

# Quake 3 colour codes: a caret followed by any single character.
_COLOR = re.compile(r"\^.")

CSV_COLUMNS = (
    "player_id", "nick", "discord_nick", "tier", "tier_channel", "tier_updated_at",
    "matches", "wins", "losses", "draws", "win_rate", "expected_wins", "actual_wins",
    "delta", "per_100", "luck_1_in", "label", "recommendation", "decided", "stack_wins", "stack_losses", "underdog_wins", "underdog_losses",
    "upset_wins", "upset_losses", "utro", "utro_percentile", "kdr",
    "exact_tiers", "crosschannel_tiers", "imputed_tiers", "override_tiers",
)


def strip_colors(nick: Optional[str]) -> str:
    if not nick:
        return ""
    return _COLOR.sub("", nick)


def _pct(value: float) -> str:
    return "%d%%" % round(value * 100)


def _utro(value: Optional[float], delta: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if delta is None:
        return "%.2f" % value
    return "%.2f (%+.2f)" % (value, delta)


MARK = {"override": "", "exact": "", "cross_channel": "*", "imputed": "?"}


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    aligns: Optional[Sequence[str]] = None,
) -> List[str]:
    """An aligned plain-text table.

    Plain monospace rather than a markdown table: this is read in a terminal and
    screenshotted, where alignment carries the shape and pipes are just noise.
    """
    if not rows:
        return []
    columns = list(zip(*([headers] + [[str(c) for c in r] for r in rows])))
    widths = [max(len(str(c)) for c in col) for col in columns]
    aligns = aligns or ["<"] * len(headers)

    def line(cells: Sequence[Any]) -> str:
        return ("  " + "   ".join(
            format(str(cell), "%s%d" % (align, width))
            for cell, width, align in zip(cells, widths, aligns)
        )).rstrip()

    return [line(headers), "  " + "-" * (sum(widths) + 3 * (len(widths) - 1))] + [
        line(r) for r in rows]


def _lineup(players) -> str:
    return " ".join(
        "%s %s%s" % (strip_colors(nick)[:12] or "?", tier, MARK.get(source, "?"))
        for nick, tier, source in players
    )


def _extremes_table(title, rows, limit) -> list:
    if not rows:
        return []
    body = [
        [row.date,
         "%+g" % row.points if row.points is not None else "-",
         _pct(row.expected),
         row.score or "-",
         _lineup(row.team),
         _lineup(row.opponents),
         _utro(row.utro, row.utro_delta)]
        for row in rows[:limit]
    ]
    return ["", "**%s**" % title] + table(
        ["Date", "Tier lead", "Win chance", "Score", "His team", "Opponents",
         "His rating"],
        body,
        ["<", ">", ">", ">", "<", "<", ">"],
    )


def to_markdown(report: PlayerReport, extremes: int = 0) -> str:
    lines = []
    name = strip_colors(report.nick) or report.discord_nick
    lines.append("## %s (%s)" % (name, report.discord_nick))
    lines.append("")

    if report.tiers:
        for tier in report.tiers:
            lines.append(
                "- %s: **%s**  _(set %s)_"
                % (tier.get("channel_name", tier.get("channel_id", "?")),
                   tier["tier"], (tier.get("updated_at") or "")[:10])
            )
    elif report.current_tier:
        # Held via the committee tier list, which the API does not carry.
        lines.append("- current tier: **%s**  _(committee list)_" % report.current_tier)
    else:
        lines.append("- no 3v3 tier held")

    life = report.lifetime
    # These stats come back scoped to the same window as the match table, not
    # career-to-date, so the label must say so.
    window = report.provenance.get("window")
    lines.append(
        "- 3v3 (%s): %d matches, %dW-%dL (%s)  UTRO %s  KDR %s"
        % (
            window or "all time",
            life["matches"], life["wins"], life["losses"], _pct(life["win_rate"]),
            "%.2f" % life["utro"] if life["utro"] else "n/a",
            "%.2f" % life["kdr"] if life["kdr"] else "n/a",
        )
    )
    if report.percentiles:
        lines.append(
            "- percentiles: "
            + ", ".join("%s p%d" % (key, round(value)) for key, value in report.percentiles)
        )
    lines.append("")

    if not report.rows:
        lines.append("_no 3v3 matches in this window_")
        lines.append("")
    else:
        # Above the headline on purpose: the committee screenshots the verdict,
        # and a disclaimer in the footer does not make it into the crop.
        alarm = guess_warning(report.source_counts)
        if alarm:
            if report.players_seen:
                alarm += "  %d of the %d players in this window had no committee tier." % (
                    report.players_guessed, report.players_seen)
            lines.append("> **%s**" % alarm)
            lines.append("")

        lines.append(
            "**Expected %.2f wins, actual %d — %+.2f → %s**"
            % (report.expected_wins, report.actual_wins, report.delta, report.label)
        )
        lines.append("")
        lines.append("### → %s" % report.recommendation
        )

        # Only worth a table when the tier actually moved; one era is the
        # ordinary case and the headline already covers it.
        if len(report.eras) > 1:
            lines.append("")
            lines.append("**By tier held**")
            lines.extend(table(
                ["Tier era", "Games", "Expected wins", "Actual wins", "Difference",
                 "Verdict"],
                [["%-3s %s..%s" % (era.tier or "-", era.start or "", era.end or ""),
                  era.games, "%.1f" % era.expected, era.actual,
                  "%+.1f" % ((era.actual - era.expected) or 0.0), era.label]
                 for era in report.eras],
                aligns=["<", ">", ">", ">", ">", "<"]))
            if report.current_era_is_thin:
                current = report.eras[-1]
                lines.append("")
                lines.append(
                    "_Too few games to judge %s yet: %d played, about %d needed "
                    "for a one-tier call._"
                    % (current.tier or "the current tier", current.games,
                       ONE_TIER_GAMES))
        lines.append("")
        favoured = report.stack_wins + report.upset_losses
        underdog = report.upset_wins + report.underdog_losses
        lines.append(
            "When favoured (stacked): **%dW-%dL**%s. As underdog: **%dW-%dL**%s.%s"
            % (
                report.stack_wins, report.upset_losses,
                " (%d%%)" % round(100 * report.stack_wins / favoured) if favoured else "",
                report.upset_wins, report.underdog_losses,
                " (%d%%)" % round(100 * report.upset_wins / underdog) if underdog else "",
                " %d even game(s)." % report.even_matches if report.even_matches else "",
            )
        )
        lines.append(
            "Upsets: %d win%s against the odds, %d loss%s while favoured."
            % (
                report.upset_wins, "" if report.upset_wins == 1 else "s",
                report.upset_losses, "" if report.upset_losses == 1 else "es",
            )
        )

    if report.draws:
        lines.append(
            "%d draw%s excluded from the totals."
            % (report.draws, "" if report.draws == 1 else "s")
        )
    if report.skipped:
        lines.append("%d match(es) skipped: incomplete roster or player absent." % report.skipped)

    available = report.provenance.get("available") or 0
    fetched = report.provenance.get("fetched") or 0
    if available > fetched:
        lines.append(
            "> **Only the most recent %d of %d matches in this window were read.** "
            "Raise `--matches` for the full picture: a truncated sample can change "
            "the verdict." % (fetched, available))

    if len(report.categories) > 1:
        lines.append("**By type of game**")
        lines += table(
            ["Type of game", "Games", "Expected wins", "Actual wins",
             "Difference", "Verdict"],
            [[LABELS.get(key, key), decided, "%.1f" % exp, won,
              "%+.1f" % (won - exp), verdict]
             for key, decided, exp, won, _luck, verdict in report.categories],
            ["<", ">", ">", ">", ">", "<"],
        )
        lines.append("")

    if extremes and report.rows:
        wins = sorted((r for r in report.rows if r.result == "W" and r.expected < 0.5),
                      key=lambda r: r.expected)
        losses = sorted((r for r in report.rows if r.result == "L" and r.expected > 0.5),
                        key=lambda r: -r.expected)
        lines += _extremes_table(
            "Biggest underdog wins (%d in this window)" % len(wins), wins, extremes)
        lines += _extremes_table(
            "Worst losses while favoured (%d in this window)" % len(losses),
            losses, extremes)
        if wins or losses:
            lines.append("")
            lines.append("_Lineups show tier; `*` = tier from another channel, "
                         "`?` = guessed._")

    counts = report.source_counts
    total = sum(counts.values())
    lines.append("")
    lines.append(
        "_%d of %d tier inputs imputed (capped at %s), %d cross-channel, "
        "%d committee override(s). Tiers from: %s. "
        "Model fitted %s on %s matches, cutoff %s, window %s._"
        % (
            counts["imputed"], total, report.provenance.get("impute_max") or "none",
            counts["cross_channel"], counts.get("override", 0),
            report.provenance.get("tier_source", "all channels"),
            report.provenance.get("fitted_at"), report.provenance.get("sample_size"),
            report.provenance.get("data_cutoff"), report.provenance.get("window"),
        )
    )
    return "\n".join(lines) + "\n"


def to_scan_table(rows: Sequence[ScanRow], show_all: bool = False) -> str:
    """The population scan as a table, ranked by effect size."""
    shown = [r for r in rows if show_all or r.label != "ON TIER"]
    if not shown:
        return "No player's record differs from their tier by more than luck.\n"

    body = [
        [r.nick, r.tier, r.games, "%+.1f" % r.per_100, "%+.1f" % r.tiers_off,
         r.recommendation, "1 in %d%s" % (r.odds, "+" if r.odds >= 10000 else ""),
         r.caution]
        for r in shown
    ]
    lines = table(
        ["Player", "Tier", "Games", "Per 100", "Tiers off", "Decision", "Confidence",
         "Read with care because"],
        body,
        ["<", "<", ">", ">", ">", "<", ">", "<"],
    )
    lines.append("")
    lines.append(
        "  Per 100 = wins per 100 games above or below what their tier predicts.")
    lines.append(
        "  Tiers off = how many tier steps that gap is worth. This is the number to")
    lines.append(
        "  argue over; Confidence assumes games are independent, which they are not")
    lines.append(
        "  when one teammate fills much of a player's sample, so it is capped at")
    lines.append(
        "  1 in 10000. Showing %d of %d players scanned." % (len(shown), len(rows)))
    return "\n".join(lines) + "\n"


def to_scan_csv(rows: Sequence[ScanRow]) -> str:
    columns = ["player_id", "nick", "tier", "games", "expected", "actual", "per_100",
               "tiers_off", "luck_1_in", "label", "recommendation", "top_mate",
               "top_mate_share", "guessed_share", "caution"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "player_id": r.player_id, "nick": r.nick, "tier": r.tier, "games": r.games,
            "expected": "%.1f" % r.expected, "actual": r.actual,
            "per_100": "%.1f" % r.per_100, "tiers_off": "%.2f" % r.tiers_off,
            "luck_1_in": r.odds, "label": r.label, "recommendation": r.recommendation,
            "top_mate": r.top_mate, "top_mate_share": "%.2f" % r.top_mate_share,
            "guessed_share": "%.2f" % r.guessed_share, "caution": r.caution,
        })
    return buffer.getvalue()


def _percentile(report: PlayerReport, key: str):
    for name, value in report.percentiles:
        if name == key:
            return value
    return ""


def _csv_row(report: PlayerReport):
    life = report.lifetime
    return {
        "player_id": report.player_id,
        "nick": strip_colors(report.nick),
        "discord_nick": report.discord_nick,
        "tier": "|".join(tier["tier"] for tier in report.tiers) or (report.current_tier or ""),
        "tier_channel": "|".join(
            tier.get("channel_name", tier.get("channel_id", "")) for tier in report.tiers
        ),
        "tier_updated_at": "|".join(
            (tier.get("updated_at") or "")[:10] for tier in report.tiers
        ),
        "matches": life["matches"],
        "wins": life["wins"],
        "losses": life["losses"],
        "draws": life["draws"],
        "win_rate": "%.4f" % life["win_rate"],
        "expected_wins": "%.2f" % report.expected_wins,
        "actual_wins": report.actual_wins,
        "delta": "%.2f" % report.delta,
        "per_100": "%.1f" % report.per_100,
        "luck_1_in": int(round(1.0 / report.luck)) if report.luck > 0 else "",
        "label": report.label,
        "recommendation": report.recommendation,
        "decided": report.decided,
        "stack_wins": report.stack_wins,
        "stack_losses": report.upset_losses,
        "underdog_wins": report.upset_wins,
        "underdog_losses": report.underdog_losses,
        "upset_wins": report.upset_wins,
        "upset_losses": report.upset_losses,
        "utro": life["utro"] if life["utro"] is not None else "",
        "utro_percentile": _percentile(report, "utro"),
        "kdr": life["kdr"] if life["kdr"] is not None else "",
        "exact_tiers": report.source_counts["exact"],
        "crosschannel_tiers": report.source_counts["cross_channel"],
        "imputed_tiers": report.source_counts["imputed"],
        "override_tiers": report.source_counts.get("override", 0),
    }


def to_csv(reports: Sequence[PlayerReport]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for report in reports:
        writer.writerow(_csv_row(report))
    return buffer.getvalue()


def to_json(report: PlayerReport) -> str:
    return json.dumps(dataclasses.asdict(report), indent=1, sort_keys=True)
