"""The header player picker: choose a nick, land on their page."""

from gibhub.site import build_site, page, player_options
from tests.test_site import CLEAN, METRICS, POINTS, STAMP, _report, _row

PLAYERS = [("h2o", "h2o"), ("Damon", "damon"), ("czkk_", "czkk")]


def test_options_are_rendered_one_per_player():
    markup = player_options(PLAYERS)
    assert markup.count("<option") == len(PLAYERS) + 1  # plus the placeholder


def test_the_option_value_is_the_player_page_path():
    assert '<option value="/players/damon/">Damon</option>' in player_options(PLAYERS)


def test_players_are_listed_alphabetically_ignoring_case():
    markup = player_options(PLAYERS)
    order = [markup.index(nick) for nick in ("czkk_", "Damon", "h2o")]
    assert order == sorted(order)


def test_the_placeholder_comes_first_and_selects_nothing():
    markup = player_options(PLAYERS)
    assert markup.index('value=""') < markup.index('value="/players/')


def test_a_nick_with_markup_in_it_is_escaped():
    markup = player_options([("<script>alert(1)</script>", "x")])
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


def test_a_quote_in_a_slug_cannot_break_out_of_the_attribute():
    markup = player_options([("q", 'a"b')])
    assert 'value="/players/a&quot;b/"' in markup


def test_no_players_means_no_picker_markup():
    assert player_options([]) == ""


def test_the_page_carries_the_picker_when_given_players():
    assert "<select" in page("t", "<p>x</p>", players=PLAYERS)


def test_the_page_omits_the_picker_when_given_none():
    assert "<select" not in page("t", "<p>x</p>")


def test_the_picker_sits_in_the_nav_with_the_other_links():
    markup = page("t", "<p>x</p>", players=PLAYERS)
    assert markup.index("<select") > markup.index("<nav>")
    assert markup.index("<select") < markup.index("</nav>")


def test_the_picker_navigates_on_change():
    assert "onchange" in page("t", "<p>x</p>", players=PLAYERS)


def test_the_picker_is_labelled_for_screen_readers():
    assert "aria-label" in page("t", "<p>x</p>", players=PLAYERS)


def test_the_page_is_still_self_contained():
    """No external script or stylesheet: the site fetches nothing at view time."""
    markup = page("t", "<p>x</p>", players=PLAYERS)
    assert "src=" not in markup
    assert "http://" not in markup and "https://" not in markup


# --- wired into the build ---------------------------------------------------


def _site(rows, reports=None):
    return build_site(list(rows), CLEAN, POINTS, 0.4385, METRICS,
                      reports=reports or {}, **STAMP)


def test_the_picker_is_absent_when_no_player_pages_are_written():
    """Nothing to jump to: the scan ran without --players."""
    site = _site([_row("p1", "Lepari")])
    assert "<select" not in site["index.html"].decode("utf-8")


def test_the_picker_lists_players_whose_pages_exist():
    site = _site([_row("p1", "Lepari")], {"p1": _report(nick="Lepari")})
    assert ('<option value="/players/lepari/">Lepari</option>'
            in site["index.html"].decode("utf-8"))


def test_the_picker_appears_on_every_page():
    site = _site([_row("p1", "Lepari")], {"p1": _report(nick="Lepari")})
    for path in ("index.html", "about/index.html", "gaps/index.html",
                 "players/lepari/index.html"):
        assert "<select" in site[path].decode("utf-8"), path


def test_the_build_stays_byte_identical_for_identical_input():
    rows = [_row("p1", "Lepari"), _row("p2", "h2o", tier="B")]
    reports = {"p1": _report(nick="Lepari")}
    assert _site(rows, reports) == _site(rows, reports)
