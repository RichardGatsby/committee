from gibhub.scan import ScanRow
from gibhub.site import assign_slugs, page, slugify


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
