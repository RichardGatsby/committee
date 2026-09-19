import json
import re

from gibhub.scan import Coverage, ScanRow
from gibhub.report import PlayerReport
from gibhub.site import (about_page, assign_slugs, build_site, caveat_block,
                         index_json, index_page, model_json, page, player_json,
                         player_page,
                         redirects, scan_json, slugify)

CLEAN = Coverage(players_seen=100, players_guessed=2, guessed_share=0.02)
HEAVY = Coverage(players_seen=100, players_guessed=46, guessed_share=0.46)


def _row(player_id, nick, **kwargs):
    fields = dict(
        player_id=player_id, nick=nick, tier="A", games=100, expected=50.0,
        actual=60, per_100=10.0, tiers_off=0.5, luck=0.01, label="OVER",
        recommendation="CONSIDER MOVING UP: A → E", top_mate="", top_mate_share=0.0,
        guessed_share=0.0,
    )
    fields.update(kwargs)
    return ScanRow(**fields)


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Lepari") == "lepari"
    assert slugify("unbiased moderator") == "unbiased-moderator"


def test_slugify_collapses_runs_and_trims_edges():
    assert slugify("!!! h2o !!!") == "h2o"
    assert slugify("a___b") == "a-b"


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!!") == "player"


def test_assign_slugs_disambiguates_a_collision_with_the_uuid():
    rows = [_row("3f2a1b9c-0000-0000-0000-000000000000", "chuCk"),
            _row("aa11bb22-0000-0000-0000-000000000000", "CHUCK")]
    slugs = assign_slugs(rows)
    assert slugs["3f2a1b9c-0000-0000-0000-000000000000"] == "chuck"
    assert slugs["aa11bb22-0000-0000-0000-000000000000"] == "chuck-aa11bb"


def test_assign_slugs_is_stable_regardless_of_row_order():
    a = _row("3f2a1b9c-0000-0000-0000-000000000000", "chuCk")
    b = _row("aa11bb22-0000-0000-0000-000000000000", "CHUCK")
    assert assign_slugs([a, b]) == assign_slugs([b, a])


def test_page_is_a_complete_document():
    html = page("Scan", "<p>body</p>")
    assert html.startswith("<!doctype html>")
    assert "<title>Scan</title>" in html
    assert "<p>body</p>" in html
    assert html.rstrip().endswith("</html>")


def test_page_escapes_the_title():
    assert "<title>a &lt;b&gt;</title>" in page("a <b>", "")


def test_page_loads_nothing_from_the_network():
    html = page("Scan", "")
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html


STAMP = dict(window="last 1y", built_at="2026-09-19T05:00:00+00:00",
             fitted_at="2026-09-18T00:00:00+00:00", sample_size=6382)


def test_caveat_block_always_explains_keep():
    block = caveat_block(CLEAN, **STAMP)
    assert "too few games to call" in block
    assert "correctly tiered" in block


def test_caveat_block_always_warns_about_unmapped_names():
    assert "no account mapped" in caveat_block(CLEAN, **STAMP)


def test_caveat_block_carries_the_build_stamp():
    block = caveat_block(CLEAN, **STAMP)
    assert "2026-09-19T05:00:00+00:00" in block
    assert "last 1y" in block
    assert "6382" in block


def test_caveat_block_raises_the_coverage_warning_when_tiers_were_guessed():
    block = caveat_block(HEAVY, **STAMP)
    assert "UNRELIABLE" in block
    assert "46 of the 100 players" in block


def test_caveat_block_omits_the_coverage_warning_when_coverage_is_clean():
    block = caveat_block(CLEAN, **STAMP)
    assert "UNRELIABLE" not in block and "CAUTION" not in block


def test_index_page_lists_a_mis_tiered_player():
    rows = [_row("p1", "Lepari", tier="A", games=120, per_100=12.5, tiers_off=0.8,
                 recommendation="CONSIDER MOVING UP: A → E", luck=0.01)]
    html = index_page(rows, CLEAN, {}, **STAMP)
    assert "Lepari" in html
    assert "+12.5" in html
    assert "CONSIDER MOVING UP: A → E" in html
    assert "1 in 100" in html


def test_index_page_hides_players_whose_record_matches_their_tier():
    rows = [_row("p1", "Lepari", label="ON TIER", recommendation="KEEP")]
    html = index_page(rows, CLEAN, {}, **STAMP)
    assert "Lepari" not in html
    assert "No player" in html


def test_index_page_caps_the_odds_it_prints():
    rows = [_row("p1", "Lepari", luck=0.0)]
    assert "1 in 10000+" in index_page(rows, CLEAN, {}, **STAMP)


def test_index_page_escapes_a_nick_that_looks_like_markup():
    rows = [_row("p1", "<script>x</script>")]
    html = index_page(rows, CLEAN, {}, **STAMP)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_index_page_carries_the_caveats():
    html = index_page([_row("p1", "Lepari")], CLEAN, {}, **STAMP)
    assert "too few games to call" in html


def test_index_page_links_a_player_when_a_slug_is_given():
    rows = [_row("p1", "Lepari")]
    html = index_page(rows, CLEAN, {"p1": "lepari"}, **STAMP)
    assert '<a href="/players/lepari/">Lepari</a>' in html


POINTS = {"S": 5.0, "E": 4.0, "A": 3.0, "B": 2.0, "C": 1.0, "D": 0.0}
METRICS = {"accuracy": 0.6393, "brier": 0.2204, "log_loss": 0.6304, "samples": 6382}


def test_about_page_states_the_tier_order():
    html = about_page(POINTS, 0.4385, METRICS, **STAMP)
    assert "S &gt; E &gt; A &gt; B &gt; C &gt; D" in html


def test_about_page_prints_the_fit_metrics():
    html = about_page(POINTS, 0.4385, METRICS, **STAMP)
    assert "63.9%" in html and "0.2204" in html and "0.6304" in html
    assert "6382" in html


def test_about_page_says_there_is_no_intercept():
    assert "no intercept" in about_page(POINTS, 0.4385, METRICS, **STAMP)


def test_about_page_lists_the_known_limitations():
    html = about_page(POINTS, 0.4385, METRICS, **STAMP)
    assert "circular" in html
    assert "52.5%" in html
    assert "no history" in html


def test_about_page_carries_the_caveats_too():
    assert "too few games to call" in about_page(POINTS, 0.4385, METRICS, **STAMP)


def test_scan_json_carries_every_row_including_on_tier_ones():
    rows = [_row("p1", "Lepari"), _row("p2", "Jassi", label="ON TIER",
                                       recommendation="KEEP")]
    payload = json.loads(scan_json(rows, CLEAN, {"p1": "lepari", "p2": "jassi"},
                                   **STAMP))
    assert [r["nick"] for r in payload["rows"]] == ["Lepari", "Jassi"]
    assert payload["rows"][0]["slug"] == "lepari"
    assert payload["rows"][0]["odds_1_in"] == 100


def test_scan_json_reports_the_coverage():
    payload = json.loads(scan_json([], HEAVY, {}, **STAMP))
    assert payload["coverage"]["players_guessed"] == 46
    assert payload["coverage"]["players_seen"] == 100


def test_scan_json_stamps_the_build():
    payload = json.loads(scan_json([], CLEAN, {}, **STAMP))
    assert payload["built_at"] == "2026-09-19T05:00:00+00:00"
    assert payload["window"] == "last 1y"


def test_model_json_carries_the_points_and_the_scale():
    payload = json.loads(model_json(POINTS, 0.4385, METRICS,
                                    fitted_at="2026-09-18T00:00:00+00:00",
                                    sample_size=6382))
    assert payload["tier_points"]["E"] == 4.0
    assert payload["scale"] == 0.4385
    assert payload["fit_metrics"]["accuracy"] == 0.6393
    assert payload["tier_order"] == ["S", "E", "A", "B", "C", "D"]


def test_index_json_maps_slugs_to_player_ids():
    rows = [_row("3f2a1b9c-0000-0000-0000-000000000000", "Lepari")]
    payload = json.loads(index_json(
        rows, {"3f2a1b9c-0000-0000-0000-000000000000": "lepari"}, **STAMP))
    assert payload["players"] == [
        {"slug": "lepari", "player_id": "3f2a1b9c-0000-0000-0000-000000000000",
         "nick": "Lepari", "tier": "A"}]


def test_index_json_sorts_players_by_slug():
    rows = [_row("p2", "zed", tier="B"), _row("p1", "alf")]
    payload = json.loads(index_json(rows, {"p1": "alf", "p2": "zed"}, **STAMP))
    assert [p["slug"] for p in payload["players"]] == ["alf", "zed"]


def _site(rows=(), coverage=CLEAN):
    return build_site(list(rows), coverage, POINTS, 0.4385, METRICS, **STAMP)


def test_build_site_writes_the_phase_one_paths():
    assert set(_site().keys()) == {
        "index.html", "about/index.html", "_headers",
        "api/scan.json", "api/model.json", "api/index.json"}


def test_build_site_returns_bytes_for_every_path():
    assert all(isinstance(v, bytes) for v in _site().values())


def test_headers_open_the_api_to_cross_origin_reads():
    headers = _site()["_headers"].decode("utf-8")
    assert "/api/*" in headers
    assert "Access-Control-Allow-Origin: *" in headers


def test_build_site_does_not_link_players_in_phase_one():
    site = _site([_row("p1", "Lepari")])
    assert "/players/" not in site["index.html"].decode("utf-8")


def test_build_site_is_byte_identical_for_identical_input():
    rows = [_row("p1", "Lepari")]
    assert _site(rows) == _site(rows)


def _html_pages(site):
    return {p: b.decode("utf-8") for p, b in site.items() if p.endswith(".html")}


def test_every_html_page_carries_the_caveats():
    site = _site([_row("p1", "Lepari")])
    missing = [p for p, html in _html_pages(site).items()
               if "too few games to call" not in html]
    assert missing == [], "pages published without the caveat block: %s" % missing


def test_every_internal_link_resolves_to_a_published_path():
    site = _site([_row("p1", "Lepari")])
    broken = []
    for path, html in _html_pages(site).items():
        for href in re.findall(r'href="([^"]+)"', html):
            target = href.lstrip("/") or "index.html"
            if target.endswith("/"):
                target += "index.html"
            if target not in site:
                broken.append((path, href))
    assert broken == [], "links to nothing: %s" % broken


def test_every_published_json_file_parses():
    site = _site([_row("p1", "Lepari")])
    for path, blob in site.items():
        if path.endswith(".json"):
            json.loads(blob.decode("utf-8"))


def _report(**kwargs):
    fields = dict(
        player_id="p1", nick="Lepari", discord_nick="lepari", tiers=[],
        lifetime={}, percentiles=[], rows=[], expected_wins=13.33, actual_wins=7,
        delta=-6.33, label="CLEARLY UNDER", luck=0.004, per_100=-31.7, decided=20,
        current_tier="A", recommendation="MOVE DOWN: A → B", upset_wins=1,
        upset_losses=2, stack_wins=5, underdog_losses=4, even_matches=0, draws=0,
        skipped=0, source_counts={"override": 80, "imputed": 40},
        provenance={}, categories=[], players_seen=39, players_guessed=18,
    )
    fields.update(kwargs)
    return PlayerReport(**fields)


def test_player_page_leads_with_the_verdict():
    html = player_page(_report(), **STAMP)
    assert "Lepari" in html
    assert "CLEARLY UNDER" in html
    assert "MOVE DOWN: A → B" in html
    assert "13.33" in html


def test_player_page_raises_the_guessed_tier_alarm_above_the_headline():
    html = player_page(_report(), **STAMP)
    assert html.index("guessed") < html.index("CLEARLY UNDER"), \
        "the alarm must survive a cropped screenshot"


def test_player_page_carries_the_caveats():
    assert "too few games to call" in player_page(_report(), **STAMP)


def test_player_page_escapes_the_nick():
    html = player_page(_report(nick="<b>x</b>"), **STAMP)
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_player_page_shows_the_stacked_and_underdog_split():
    html = player_page(_report(), **STAMP)
    assert "favoured" in html.lower() and "underdog" in html.lower()


def test_player_json_carries_the_verdict_and_its_provenance():
    payload = json.loads(player_json(_report(), slug="lepari", **STAMP))
    assert payload["slug"] == "lepari"
    assert payload["nick"] == "Lepari"
    assert payload["label"] == "CLEARLY UNDER"
    assert payload["expected_wins"] == 13.33
    assert payload["source_counts"]["imputed"] == 40


def test_player_json_stamps_the_build():
    payload = json.loads(player_json(_report(), slug="lepari", **STAMP))
    assert payload["built_at"] == "2026-09-19T05:00:00+00:00"


PREVIOUS = {"players": [
    {"slug": "chuck", "player_id": "p1", "nick": "chuCk", "tier": "A"},
    {"slug": "jassi", "player_id": "p2", "nick": "Jassi", "tier": "A"},
]}


def test_redirects_point_a_retired_slug_at_the_current_one():
    lines = redirects(PREVIOUS, {"p1": "czkk", "p2": "jassi"})
    assert "/players/chuck/ /players/czkk/ 301" in lines


def test_redirects_leave_unchanged_slugs_alone():
    assert redirects(PREVIOUS, {"p1": "chuck", "p2": "jassi"}) == ""


def test_redirects_ignore_a_player_who_has_left_the_scan():
    assert redirects(PREVIOUS, {"p2": "jassi"}) == ""


def test_redirects_survive_a_missing_previous_build():
    assert redirects(None, {"p1": "chuck"}) == ""
    assert redirects({}, {"p1": "chuck"}) == ""


def test_build_site_writes_a_page_and_json_per_report():
    site = build_site([_row("p1", "Lepari")], CLEAN, POINTS, 0.4385, METRICS,
                      reports={"p1": _report()}, previous_index=None, **STAMP)
    assert "players/lepari/index.html" in site
    assert "api/players/lepari.json" in site


def test_build_site_links_players_once_pages_exist():
    site = build_site([_row("p1", "Lepari")], CLEAN, POINTS, 0.4385, METRICS,
                      reports={"p1": _report()}, previous_index=None, **STAMP)
    assert '<a href="/players/lepari/">' in site["index.html"].decode("utf-8")


def test_build_site_writes_redirects_only_when_a_slug_moved():
    rows = [_row("p1", "Lepari")]
    without = build_site(rows, CLEAN, POINTS, 0.4385, METRICS,
                         reports={"p1": _report()},
                         previous_index={"players": [
                             {"slug": "lepari", "player_id": "p1"}]}, **STAMP)
    assert "_redirects" not in without

    moved = build_site(rows, CLEAN, POINTS, 0.4385, METRICS,
                       reports={"p1": _report()},
                       previous_index={"players": [
                           {"slug": "old-name", "player_id": "p1"}]}, **STAMP)
    assert "/players/old-name/ /players/lepari/ 301" in \
        moved["_redirects"].decode("utf-8")


def test_every_html_page_still_carries_the_caveats_with_player_pages():
    site = build_site([_row("p1", "Lepari")], CLEAN, POINTS, 0.4385, METRICS,
                      reports={"p1": _report()}, previous_index=None, **STAMP)
    missing = [p for p, html in _html_pages(site).items()
               if "too few games to call" not in html]
    assert missing == []


def test_player_page_strips_the_colour_codes_from_the_nick():
    html = player_page(_report(nick="^1agsor"), **STAMP)
    assert "^1agsor" not in html
    assert "agsor" in html


def test_player_page_falls_back_to_the_discord_nick_when_the_nick_is_all_colour():
    html = player_page(_report(nick="^1^2", discord_nick="lepari"), **STAMP)
    assert "lepari" in html


def test_player_json_strips_the_colour_codes_too():
    payload = json.loads(player_json(_report(nick="^1agsor"), slug="agsor", **STAMP))
    assert payload["nick"] == "agsor"
