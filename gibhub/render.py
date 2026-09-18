"""Pure rendering of a PlayerReport. No I/O, no fetching."""

import csv
import dataclasses
import io
import json
import re
from typing import Optional, Sequence

from .report import PlayerReport

# Quake 3 colour codes: a caret followed by any single character.
_COLOR = re.compile(r"\^.")

CSV_COLUMNS = [
    "player_id", "nick", "discord_nick", "tier", "tier_channel", "tier_updated_at",
    "matches", "wins", "losses", "draws", "win_rate", "expected_wins", "actual_wins",
    "delta", "label", "stack_wins", "stack_losses", "underdog_wins", "underdog_losses",
    "upset_wins", "upset_losses", "utro", "utro_percentile", "kdr",
    "exact_tiers", "crosschannel_tiers", "imputed_tiers",
]


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


def to_markdown(report: PlayerReport) -> str:
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
    else:
        lines.append("- no 3v3 tier held")

    life = report.lifetime
    lines.append(
        "- 3v3 lifetime: %d matches, %dW-%dL (%s)  UTRO %s  KDR %s"
        % (
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
        lines.append(
            "**Expected %.2f wins, actual %d — %+.2f → %s**"
            % (report.expected_wins, report.actual_wins, report.delta, report.label)
        )
        lines.append("")
        lines.append("| date | maps | exp | res | utro (vs base) | |")
        lines.append("| --- | --- | ---: | :---: | ---: | --- |")
        for row in report.rows:
            lines.append(
                "| %s | %s | %s | %s | %s | %s |"
                % (
                    row.date,
                    "/".join(row.maps) or "-",
                    _pct(row.expected),
                    row.result,
                    _utro(row.utro, row.utro_delta),
                    "upset" if row.upset else "",
                )
            )
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

    counts = report.source_counts
    total = counts["exact"] + counts["cross_channel"] + counts["imputed"]
    lines.append("")
    lines.append(
        "_%d of %d tier inputs imputed, %d cross-channel. Tiers from: %s. "
        "Model fitted %s on %s matches, cutoff %s, window %s._"
        % (
            counts["imputed"], total, counts["cross_channel"],
            report.provenance.get("tier_source", "all channels"),
            report.provenance.get("fitted_at"), report.provenance.get("sample_size"),
            report.provenance.get("data_cutoff"), report.provenance.get("window"),
        )
    )
    return "\n".join(lines) + "\n"


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
        "tier": "|".join(tier["tier"] for tier in report.tiers),
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
        "label": report.label,
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
