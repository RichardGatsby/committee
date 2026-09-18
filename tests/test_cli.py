import csv
import io
import json

import pytest

from gibhub.bundle import Bundle, save
from gibhub.cli import build_parser, main
from gibhub.tiers import Holding


class _Client:
    def __init__(self, search):
        self.search = search

    def get(self, path, params=None):
        if path == "/players/search":
            return {"data": self.search}
        if path == "/players/p1":
            return {"player_id": "p1", "nick": "Me", "discord_nick": "me", "tiers": [],
                    "lifetime": {"matches": 10, "match_wins": 6, "match_losses": 4,
                                 "match_draws": 0, "utro": 1.1, "kdr": 1.0}}
        if path == "/players/p1/spider":
            return {"metrics": [{"key": "utro", "value": 1.1, "avg": 1.0, "percentile": 70}]}
        if path.startswith("/matches/"):
            return {
                "match_id": "m1", "state": "finished", "winner": "alpha",
                "channel_id": "poland", "start_time": "2026-09-01T20:00:00+02:00",
                "maps": [{"map": "supply"}],
                "teams": {
                    "alpha": [{"player_id": "p1"}, {"player_id": "a2"}, {"player_id": "a3"}],
                    "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
                },
                "rounds": [{"alpha": [{"player_id": "p1", "utro": 1.2,
                                       "playtime_percent": 100}], "beta": []}],
            }
        raise AssertionError("unexpected path " + path)

    def paginate(self, path, params=None, page_size=100, limit=None):
        return iter([{"match_id": "m1"}])


FAKE_CLIENT = _Client([{"player_id": "p1", "nick": "Me", "discord_nick": "me"}])
AMBIGUOUS_CLIENT = _Client([
    {"player_id": "p1", "nick": "kiz", "discord_nick": "kizA"},
    {"player_id": "p2", "nick": "kiz2", "discord_nick": "kizB"},
])


@pytest.fixture
def fake_bundle_path(tmp_path):
    path = tmp_path / "coefficients.json"
    save(
        Bundle(
            fitted_at="2026-09-18T00:00:00+00:00",
            data_cutoff="2026-09-18",
            sample_size=100,
            coefficients=[0.9, 0.6, 0.3, 0.0, -0.4, -0.8],
            fit_metrics={"log_loss": 0.6, "brier": 0.2, "accuracy": 0.7, "samples": 100},
            bands={"S": 1.3, "A": 1.15, "B": 1.0, "C": 0.9, "D": 0.8, "E": 0.7},
            utro={},
            holdings={"p1": (Holding("poland", "A", "2026-09-01"),)},
            channel_names={"poland": "Poland"},
        ),
        path,
    )
    return str(path)


def test_parser_defaults_match_the_spec():
    args = build_parser().parse_args(["player", "Kredenc"])
    assert args.command == "player"
    assert args.player == "Kredenc"
    assert args.matches == 50
    # Defaults to the 2026 season rather than a rolling window.
    assert args.from_ == "2026-01-01"
    assert args.range is None
    assert args.extremes == 3
    assert args.format == "md"


def test_parser_accepts_the_documented_flags():
    args = build_parser().parse_args(
        ["player", "p1", "--matches", "5", "--channel", "Poland", "--range", "1y",
         "--from", "none", "--to", "2026-01-01", "--format", "json"]
    )
    assert args.matches == 5
    assert args.channel == "Poland"
    assert args.range == "1y"
    assert args.to == "2026-01-01"
    assert args.format == "json"


def test_bulk_requires_a_selector():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["bulk"])


def test_bulk_accepts_repeated_tiers():
    args = build_parser().parse_args(["bulk", "--tier", "A", "--tier", "B", "--out", "x.csv"])
    assert args.tier == ["A", "B"]
    assert args.out == "x.csv"


def test_missing_bundle_exits_non_zero_with_guidance(tmp_path, capsys):
    code = main(["--bundle", str(tmp_path / "nope.json"), "player", "someone"])
    assert code != 0
    assert "fit --refit" in capsys.readouterr().err


def test_player_command_prints_markdown(monkeypatch, tmp_path, capsys, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    code = main(["--bundle", fake_bundle_path, "--cache", str(tmp_path), "player", "p1"])
    assert code == 0
    assert "## Me" in capsys.readouterr().out


def test_player_command_prints_json(monkeypatch, tmp_path, capsys, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    main(["--bundle", fake_bundle_path, "--cache", str(tmp_path), "player", "p1",
          "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["player_id"] == "p1"


def test_an_ambiguous_name_exits_non_zero_and_lists_candidates(
    monkeypatch, tmp_path, capsys, fake_bundle_path
):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: AMBIGUOUS_CLIENT)
    code = main(["--bundle", fake_bundle_path, "--cache", str(tmp_path), "player", "kiz"])
    assert code != 0
    assert "matches several players" in capsys.readouterr().err


def test_bulk_writes_csv_to_stdout(monkeypatch, tmp_path, capsys, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    monkeypatch.setattr("gibhub.cli.select_players", lambda client, args: ["p1", "p1"])
    code = main(["--bundle", fake_bundle_path, "--cache", str(tmp_path), "bulk", "--tier", "A"])
    assert code == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 2
    assert rows[0]["player_id"] == "p1"


def test_bulk_writes_csv_to_a_file(monkeypatch, tmp_path, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    monkeypatch.setattr("gibhub.cli.select_players", lambda client, args: ["p1"])
    out = tmp_path / "out.csv"
    code = main(["--bundle", fake_bundle_path, "--cache", str(tmp_path), "bulk",
                 "--tier", "A", "--out", str(out)])
    assert code == 0
    assert "player_id" in out.read_text(encoding="utf-8")


def test_select_players_reads_a_players_file(tmp_path):
    from gibhub.cli import select_players

    listing = tmp_path / "players.txt"
    listing.write_text("Kredenc\n\n# a comment\np1\n", encoding="utf-8")
    args = build_parser().parse_args(["bulk", "--players", str(listing)])

    class C:
        def get(self, path, params=None):
            return {"data": [{"player_id": "resolved-" + params["q"]}]}

    assert select_players(C(), args) == ["resolved-Kredenc", "resolved-p1"]


def test_select_players_reads_tier_rosters():
    from gibhub.cli import select_players

    args = build_parser().parse_args(["bulk", "--tier", "A", "--tier", "S"])

    class C:
        def paginate(self, path, params=None, page_size=100, limit=None):
            return iter([{"player_id": params["tier"] + "-1"}])

    assert select_players(C(), args) == ["A-1", "S-1"]


def test_fit_without_refit_prints_the_stored_metadata(capsys, fake_bundle_path):
    code = main(["--bundle", fake_bundle_path, "fit"])
    assert code == 0
    output = capsys.readouterr().out
    assert "2026-09-18T00:00:00+00:00" in output
    assert "accuracy" in output
    assert "S" in output


def test_fit_with_refit_writes_a_bundle(monkeypatch, tmp_path, capsys):
    from gibhub.bundle import load

    fake = Bundle(
        fitted_at="2026-09-19T00:00:00+00:00", data_cutoff="2026-09-19", sample_size=7,
        coefficients=[1.0, 0.5, 0.2, 0.0, -0.3, -0.7],
        fit_metrics={"log_loss": 0.5, "brier": 0.2, "accuracy": 0.8, "samples": 7},
        bands={"S": 1.3}, utro={}, holdings={"p1": (Holding("c", "S", "2026-01-01"),)},
        channel_names={},
    )
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    monkeypatch.setattr("gibhub.cli.build_bundle",
                        lambda client, to=None, limit=None, tier_channels=None,
                               points=None, impute_max=None,
                               overrides=None: fake)

    path = tmp_path / "coefficients.json"
    code = main(["--bundle", str(path), "fit", "--refit"])
    assert code == 0
    assert load(path).sample_size == 7
    assert "7" in capsys.readouterr().out


def test_fit_accepts_repeated_tier_channel_filters():
    args = build_parser().parse_args(
        ["fit", "--refit", "--tier-channel", "Events", "--tier-channel", "Poland"]
    )
    assert args.tier_channel == ["Events", "Poland"]


def test_tier_channel_defaults_to_none_meaning_all_channels():
    assert build_parser().parse_args(["fit", "--refit"]).tier_channel is None


def test_parse_points_bare_flag_uses_the_default_scale():
    from gibhub.cli import parse_points
    from gibhub.model import TIER_POINTS

    assert parse_points("default") == TIER_POINTS
    assert parse_points(None) is None


def test_parse_points_reads_an_explicit_scale():
    from gibhub.cli import parse_points

    assert parse_points("S=5,E=4,A=3,B=2,C=1,D=0") == {
        "S": 5.0, "E": 4.0, "A": 3.0, "B": 2.0, "C": 1.0, "D": 0.0}


def test_parse_points_rejects_an_unknown_tier():
    from gibhub.cli import parse_points

    with pytest.raises(ValueError, match="unknown tier 'Z'"):
        parse_points("Z=5,S=5,E=4,A=3,B=2,C=1,D=0")


def test_parse_points_rejects_an_incomplete_scale():
    from gibhub.cli import parse_points

    with pytest.raises(ValueError, match="missing a value for: C, D"):
        parse_points("S=5,E=4,A=3,B=2")


def test_points_flag_is_optional_and_takes_an_optional_value():
    assert build_parser().parse_args(["fit", "--refit"]).points is None
    assert build_parser().parse_args(["fit", "--refit", "--points"]).points == "default"
    assert build_parser().parse_args(
        ["fit", "--refit", "--points", "S=9,E=4,A=3,B=2,C=1,D=0"]).points == "S=9,E=4,A=3,B=2,C=1,D=0"


def test_impute_max_defaults_to_a():
    assert build_parser().parse_args(["fit", "--refit"]).impute_max == "A"


def test_impute_max_accepts_a_tier_or_none():
    from gibhub.cli import parse_impute_max

    assert parse_impute_max("A") == "A"
    assert parse_impute_max("b") == "B"
    assert parse_impute_max("none") is None
    assert parse_impute_max(None) is None


def test_impute_max_rejects_an_unknown_tier():
    from gibhub.cli import parse_impute_max

    with pytest.raises(ValueError, match="unknown tier 'Q'"):
        parse_impute_max("Q")


def test_load_overrides_reads_names_and_tiers(tmp_path):
    from gibhub.cli import load_overrides

    path = tmp_path / "overrides.txt"
    path.write_text("# committee knowledge\nJassi = A\n\nroltzz=B  # a comment\n",
                    encoding="utf-8")

    class C:
        def get(self, path_, params=None):
            return {"data": [{"player_id": "id-" + params["q"]}]}

    assert load_overrides(C(), str(path)) == {"id-Jassi": "A", "id-roltzz": "B"}


def test_load_overrides_rejects_a_malformed_line(tmp_path):
    from gibhub.cli import load_overrides

    path = tmp_path / "bad.txt"
    path.write_text("Jassi = Z\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_overrides(object(), str(path))


def test_no_overrides_file_means_no_overrides():
    from gibhub.cli import load_overrides

    assert load_overrides(object(), None) == {}


def test_window_label_describes_the_slice_covered():
    from gibhub.cli import window_label

    p = build_parser()
    assert window_label(p.parse_args(["player", "x"])) == "2026-01-01 onwards"
    assert window_label(p.parse_args(
        ["player", "x", "--to", "2026-06-01"])) == "2026-01-01 to 2026-06-01"
    assert window_label(p.parse_args(
        ["player", "x", "--from", "none", "--range", "6m"])) == "last 6m"
    assert window_label(p.parse_args(["player", "x", "--from", "none"])) == "all time"


def test_extremes_can_be_switched_off():
    assert build_parser().parse_args(["player", "x", "--extremes", "0"]).extremes == 0
