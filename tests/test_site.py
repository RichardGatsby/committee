from gibhub.scan import Coverage, ScanRow
from gibhub.site import (about_page, assign_slugs, caveat_block, index_page,
                         page, slugify)

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
