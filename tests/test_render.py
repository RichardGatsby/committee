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
    luck=0.34,
    per_100=7.1,
    decided=3,
    current_tier="A",
    recommendation="KEEP at A",
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


def test_the_headline_is_one_compact_line():
    text = to_markdown(REPORT)
    headline = [l for l in text.splitlines() if l.startswith("**Expected")]
    assert len(headline) == 1
    assert "Expected 1.73 wins, actual 2 — +0.27 → ON TIER" in headline[0]
    # No z-scores or p-values in the committee-facing text.
    assert "z-score" not in text and "p =" not in text


def test_the_headline_carries_nothing_but_the_verdict():
    """The per-100 and odds figures were not understood; the label carries them."""
    headline = [l for l in to_markdown(REPORT).splitlines()
                if l.startswith("**Expected")][0]
    assert headline == "**Expected 1.73 wins, actual 2 — +0.27 → ON TIER**"


def test_a_strong_result_reads_as_clearly_over():
    strong = dataclasses.replace(
        REPORT, label="CLEARLY OVER", luck=0.0006, delta=24.7, per_100=10.3,
        decided=240, actual_wins=143, expected_wins=118.3)
    headline = [l for l in to_markdown(strong).splitlines()
                if l.startswith("**Expected")][0]
    assert headline.endswith("→ CLEARLY OVER**")


def test_the_per_match_table_is_not_printed():
    """336 rows is unpastable; the verdict is still computed from all of them."""
    text = to_markdown(REPORT)
    assert "2026-09-16" not in text
    assert "Expected 1.73 wins" in text


def test_the_extremes_tables_still_render_their_rows():
    text = to_markdown(REPORT, extremes=5)
    assert "2026-09-16" in text
    assert "n/a" in text
    assert "Win chance" in text and "His team" in text


def test_tables_are_plain_monospace_not_markdown():
    """Read in a terminal and screenshotted; pipes and backticks are just noise."""
    text = to_markdown(REPORT, extremes=5)
    assert "```" not in text
    assert not any(l.startswith("| ") for l in text.splitlines())


def test_table_columns_line_up():
    from gibhub.render import table

    lines = table(["Name", "N"], [["a", 1], ["bbbb", 22]], ["<", ">"])
    assert lines[0] == "  Name    N"
    assert lines[2] == "  a       1"
    assert lines[3] == "  bbbb   22"
    # Every row is the same width, so the columns read straight down.
    assert len({len(l.rstrip()) for l in [lines[0], lines[2], lines[3]]}) <= 2


def test_an_empty_table_renders_nothing():
    from gibhub.render import table

    assert table(["A"], []) == []


def test_markdown_footer_reports_provenance_and_sources():
    text = to_markdown(REPORT)
    assert "1 of 24 tier inputs imputed" in text
    assert "2026-09-18T10:00:00+00:00" in text
    assert "4200" in text


def test_markdown_notes_draws_are_excluded():
    assert "1 draw excluded" in to_markdown(REPORT)


def test_markdown_handles_an_empty_report():
    empty = dataclasses.replace(REPORT, rows=[], draws=0, decided=0)
    assert "no 3v3 matches in this window" in to_markdown(empty)


def test_markdown_flags_a_genuinely_untiered_player():
    assert "no 3v3 tier held" in to_markdown(
        dataclasses.replace(REPORT, tiers=[], current_tier=None))


def test_csv_header_matches_the_spec():
    assert CSV_COLUMNS == [
        "player_id", "nick", "discord_nick", "tier", "tier_channel", "tier_updated_at",
        "matches", "wins", "losses", "draws", "win_rate", "expected_wins", "actual_wins",
        "delta", "per_100", "luck_1_in", "label", "recommendation", "decided",
        "stack_wins",
        "stack_losses", "underdog_wins", "underdog_losses",
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


def test_csv_falls_back_to_the_committee_tier_when_the_api_has_none():
    rows = list(csv.DictReader(io.StringIO(
        to_csv([dataclasses.replace(REPORT, tiers=[], current_tier="A")]))))
    assert rows[0]["tier"] == "A"
    assert rows[0]["tier_channel"] == ""


def test_csv_leaves_tier_columns_blank_for_a_genuinely_untiered_player():
    rows = list(csv.DictReader(io.StringIO(
        to_csv([dataclasses.replace(REPORT, tiers=[], current_tier=None)]))))
    assert rows[0]["tier"] == ""
    assert rows[0]["tier_channel"] == ""


def test_csv_carries_the_recommendation():
    rows = list(csv.DictReader(io.StringIO(to_csv([REPORT]))))
    assert rows[0]["recommendation"] == "KEEP at A"


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


def test_markdown_warns_when_the_window_was_truncated():
    """Silently reading the most recent N can flip the verdict."""
    truncated = dataclasses.replace(
        REPORT, provenance=dict(REPORT.provenance, available=483, fetched=50))
    text = to_markdown(truncated)
    assert "Only the most recent 50 of 483 matches" in text
    assert "--matches" in text


def test_markdown_does_not_warn_when_the_window_was_fully_read():
    full = dataclasses.replace(
        REPORT, provenance=dict(REPORT.provenance, available=4, fetched=4))
    assert "Only the most recent" not in to_markdown(full)


def test_the_by_type_table_shows_a_verdict_without_odds():
    two = dataclasses.replace(REPORT, categories=[
        ("legacy", 180, 96.0, 94, 0.5, "ON TIER"),
        ("cup", 17, 10.5, 6, 0.018, "UNDER"),
    ])
    text = to_markdown(two)
    assert "Type of game" in text and "Expected wins" in text
    rows = [l for l in text.splitlines() if "gathers" in l or "team games" in l]
    assert any("180" in r and "96.0" in r and "-2.0" in r and "ON TIER" in r for r in rows)
    assert any("10.5" in r and "-4.5" in r and "UNDER" in r for r in rows)
    assert "1 in " not in text


def test_the_recommendation_is_its_own_heading():
    text = to_markdown(REPORT)
    assert "### → KEEP at A" in text


def test_a_committee_tier_shows_in_the_header_when_the_api_has_none():
    """Overrides live only in the tier list, so the API reports no tier at all."""
    only_override = dataclasses.replace(REPORT, tiers=[], current_tier="A")
    text = to_markdown(only_override)
    assert "current tier: **A**  _(committee list)_" in text
    assert "no 3v3 tier held" not in text


def test_no_tier_anywhere_still_says_so():
    assert "no 3v3 tier held" in to_markdown(
        dataclasses.replace(REPORT, tiers=[], current_tier=None))


def _scan_row(**kw):
    from gibhub.scan import ScanRow

    base = dict(player_id="p1", nick="Baczo", tier="B", games=427, expected=181.6,
                actual=249, per_100=15.8, tiers_off=1.8, luck=3.4e-12,
                label="CLEARLY OVER", recommendation="MOVE UP: B → A",
                top_mate="SkyLine", top_mate_share=0.29, guessed_share=0.05)
    base.update(kw)
    return ScanRow(**base)


def test_the_scan_table_leads_with_effect_size_and_the_decision():
    from gibhub.render import to_scan_table

    text = to_scan_table([_scan_row()])
    assert "Player" in text and "Per 100" in text and "Tiers off" in text
    assert "Decision" in text and "Read with care because" in text
    assert "Baczo" in text and "+15.8" in text and "MOVE UP: B → A" in text
    assert "29% of games with SkyLine" in text


def test_the_scan_table_caps_the_confidence_it_shows():
    from gibhub.render import to_scan_table

    text = to_scan_table([_scan_row()])
    assert "1 in 10000+" in text
    assert "2.9" not in text  # no absurd 1-in-billions figure


def test_the_scan_table_hides_on_tier_players_unless_asked():
    from gibhub.render import to_scan_table

    rows = [_scan_row(), _scan_row(player_id="p2", nick="devix", label="ON TIER",
                                   recommendation="KEEP at E", per_100=1.0)]
    assert "devix" not in to_scan_table(rows)
    assert "devix" in to_scan_table(rows, show_all=True)
    assert "Showing 1 of 2 players scanned" in to_scan_table(rows)


def test_an_all_on_tier_scan_says_so():
    from gibhub.render import to_scan_table

    text = to_scan_table([_scan_row(label="ON TIER")])
    assert "No player's record differs from their tier by more than luck" in text


def test_the_scan_csv_carries_the_raw_numbers():
    import csv as _csv
    from gibhub.render import to_scan_csv

    rows = list(_csv.DictReader(io.StringIO(to_scan_csv([_scan_row()]))))
    assert rows[0]["nick"] == "Baczo"
    assert rows[0]["tiers_off"] == "1.80"
    assert rows[0]["top_mate"] == "SkyLine"
    assert rows[0]["caution"].startswith("29%")
