import csv
import dataclasses
import io
import json

from gibhub.render import CSV_COLUMNS, strip_colors, to_csv, to_json, to_markdown
from gibhub.report import MatchRow, PlayerReport

REPORT = PlayerReport(
    player_id="p1",
    nick="^6K^5R^3E^2D^EY",
    discord_nick="Kredenc",
    tiers=[{"channel_id": "poland", "channel_name": "Poland ET:Legacy: #3v3", "tier": "A",
            "size": 6, "updated_at": "2026-09-18T08:37:09+02:00"}],
    lifetime={"matches": 635, "wins": 314, "losses": 280, "draws": 41,
              "win_rate": 0.5286, "utro": 1.1011, "kdr": 1.1245},
    percentiles=[("utro", 87.5), ("acc", 62.0)],
    rows=[
        MatchRow("m1", "2026-09-18", ["supply", "adlernest"], "alpha", 0.62, "W",
                 1.25, 0.15, ["exact"] * 6, False),
        MatchRow("m2", "2026-09-17", ["erdenberg_t2"], "beta", 0.41, "W",
                 1.40, 0.30, ["exact"] * 5 + ["imputed"], True),
        MatchRow("m3", "2026-09-16", ["supply"], "alpha", 0.70, "L",
                 None, None, ["exact"] * 6, True),
        MatchRow("m4", "2026-09-15", ["supply"], "alpha", 0.50, "D",
                 1.0, -0.10, ["exact"] * 6, False),
    ],
    expected_wins=1.73,
    actual_wins=2,
    delta=0.27,
    label="ON TIER",
    upset_wins=1,
    upset_losses=1,
    stack_wins=1,
    underdog_losses=0,
    even_matches=0,
    draws=1,
    skipped=0,
    source_counts={"exact": 23, "cross_channel": 0, "imputed": 1, "override": 0},
    provenance={"fitted_at": "2026-09-18T10:00:00+00:00", "data_cutoff": "2026-09-18",
                "sample_size": 4200, "window": "last 6m"},
)


def test_strip_colors_removes_quake_codes():
    assert strip_colors("^6K^5R^3E^2D^EY") == "KREDY"
    assert strip_colors("^1L^Ae^Lg^3i^Oo^7n") == "Legion"
    assert strip_colors("plain") == "plain"
    assert strip_colors(None) == ""


def test_markdown_leads_with_the_nick_and_tier():
    text = to_markdown(REPORT)
    assert text.startswith("## KREDY (Kredenc)")
    assert "Poland ET:Legacy: #3v3: **A**" in text


def test_markdown_shows_the_headline_comparison():
    text = to_markdown(REPORT)
    assert "expected 1.73" in text.lower()
    assert "actual 2" in text
    assert "ON TIER" in text


def test_markdown_marks_upsets():
    text = to_markdown(REPORT)
    lines = [line for line in text.splitlines() if line.startswith("| 2026-09-17")]
    assert "upset" in lines[0]


def test_markdown_renders_a_missing_utro_without_crashing():
    text = to_markdown(REPORT)
    assert "| 2026-09-16" in text
    assert "n/a" in text


def test_markdown_footer_reports_provenance_and_sources():
    text = to_markdown(REPORT)
    assert "1 of 24 tier inputs imputed" in text
    assert "2026-09-18T10:00:00+00:00" in text
    assert "4200" in text


def test_markdown_notes_draws_are_excluded():
    assert "1 draw excluded" in to_markdown(REPORT)


def test_markdown_handles_an_empty_report():
    empty = dataclasses.replace(REPORT, rows=[], draws=0)
    assert "no 3v3 matches in this window" in to_markdown(empty)


def test_markdown_flags_an_untiered_player():
    assert "no 3v3 tier held" in to_markdown(dataclasses.replace(REPORT, tiers=[]))


def test_csv_header_matches_the_spec():
    assert CSV_COLUMNS == [
        "player_id", "nick", "discord_nick", "tier", "tier_channel", "tier_updated_at",
        "matches", "wins", "losses", "draws", "win_rate", "expected_wins", "actual_wins",
        "delta", "label", "stack_wins", "stack_losses", "underdog_wins", "underdog_losses",
        "upset_wins", "upset_losses", "utro", "utro_percentile", "kdr",
        "exact_tiers", "crosschannel_tiers", "imputed_tiers", "override_tiers",
    ]


def test_markdown_splits_results_into_favoured_and_underdog():
    text = to_markdown(REPORT)
    assert "When favoured (stacked): **1W-1L** (50%)" in text
    assert "As underdog: **1W-0L** (100%)" in text


def test_csv_carries_the_stack_and_underdog_columns():
    rows = list(csv.DictReader(io.StringIO(to_csv([REPORT]))))
    assert rows[0]["stack_wins"] == "1"
    assert rows[0]["stack_losses"] == "1"
    assert rows[0]["underdog_wins"] == "1"
    assert rows[0]["underdog_losses"] == "0"


def test_csv_writes_one_row_per_report():
    rows = list(csv.DictReader(io.StringIO(to_csv([REPORT, REPORT]))))
    assert len(rows) == 2
    assert rows[0]["nick"] == "KREDY"
    assert rows[0]["tier"] == "A"
    assert rows[0]["tier_channel"] == "Poland ET:Legacy: #3v3"
    assert rows[0]["label"] == "ON TIER"
    assert rows[0]["imputed_tiers"] == "1"


def test_csv_reads_the_utro_percentile_from_the_spider_metrics():
    rows = list(csv.DictReader(io.StringIO(to_csv([REPORT]))))
    assert rows[0]["utro_percentile"] == "87.5"


def test_csv_leaves_tier_columns_blank_for_an_untiered_player():
    rows = list(csv.DictReader(io.StringIO(to_csv([dataclasses.replace(REPORT, tiers=[])]))))
    assert rows[0]["tier"] == ""
    assert rows[0]["tier_channel"] == ""


def test_csv_joins_multiple_tiers():
    two = dataclasses.replace(REPORT, tiers=REPORT.tiers + [
        {"channel_id": "events", "channel_name": "Events", "tier": "S", "size": 6,
         "updated_at": "2026-09-01T00:00:00+02:00"}])
    rows = list(csv.DictReader(io.StringIO(to_csv([two]))))
    assert rows[0]["tier"] == "A|S"
    assert rows[0]["tier_channel"] == "Poland ET:Legacy: #3v3|Events"


def test_json_round_trips_and_includes_the_rows():
    payload = json.loads(to_json(REPORT))
    assert payload["player_id"] == "p1"
    assert len(payload["rows"]) == 4
    assert payload["rows"][0]["expected"] == 0.62
    assert payload["label"] == "ON TIER"


def test_markdown_labels_the_stats_with_their_window_not_as_lifetime():
    """The profile endpoint scopes these to --range, so calling them lifetime lied."""
    text = to_markdown(REPORT)
    assert "3v3 (last 6m): 635 matches" in text
    assert "lifetime" not in text


def test_markdown_says_all_time_when_there_is_no_window():
    no_window = dataclasses.replace(
        REPORT, provenance=dict(REPORT.provenance, window=None))
    assert "3v3 (all time):" in to_markdown(no_window)
