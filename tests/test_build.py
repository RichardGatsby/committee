from gibhub.build import fetch_tier_holdings, fetch_utro


class FakeClient:
    """Serves canned payloads keyed by (path, a discriminating param)."""

    def __init__(self, pages=None, singles=None):
        self.pages = pages or {}
        self.singles = singles or {}
        self.calls = []

    def paginate(self, path, params=None, page_size=100, limit=None):
        params = params or {}
        key = (path, params.get("tier") or params.get("metric"))
        self.calls.append(key)
        return iter(self.pages.get(key, []))

    def get(self, path, params=None):
        self.calls.append((path, (params or {}).get("size")))
        return self.singles.get(path, {})


def test_fetch_utro_maps_player_ids_to_values():
    client = FakeClient(
        pages={
            ("/leaderboards", "utro_shrunken"): [
                {"player_id": "p1", "value": 1.24, "rounds": 90},
                {"player_id": "p2", "value": 0.81, "rounds": 40},
            ]
        }
    )
    assert fetch_utro(client) == {"p1": 1.24, "p2": 0.81}


def test_fetch_utro_skips_rows_below_the_round_floor():
    client = FakeClient(
        pages={
            ("/leaderboards", "utro_shrunken"): [
                {"player_id": "p1", "value": 1.71, "rounds": 1},
                {"player_id": "p2", "value": 0.95, "rounds": 60},
            ]
        }
    )
    assert fetch_utro(client, min_rounds=10) == {"p2": 0.95}


def _roster_pages(tier_with_player):
    return {
        ("/players", tier): ([{"player_id": "p1"}] if tier == tier_with_player else [])
        for tier in ("S", "A", "B", "C", "D", "E")
    }


def test_fetch_tier_holdings_reads_each_players_channel_tiers():
    client = FakeClient(
        pages=_roster_pages("A"),
        singles={
            "/players/p1": {
                "tiers": [
                    {"channel_id": "poland", "channel_name": "Poland", "tier": "A",
                     "size": 6, "updated_at": "2026-09-18T08:37:09+02:00"},
                    {"channel_id": "events6", "channel_name": "Events 6v6", "tier": "E",
                     "size": 12, "updated_at": "2026-09-18T08:37:09+02:00"},
                ]
            }
        },
    )
    holdings, names = fetch_tier_holdings(client)
    # size 12 is 6v6 and must not leak into a 3v3 index.
    assert [h.tier for h in holdings["p1"]] == ["A"]
    assert holdings["p1"][0].channel_id == "poland"
    assert names == {"poland": "Poland"}


def test_fetch_tier_holdings_returns_holders_per_tier():
    client = FakeClient(
        pages=_roster_pages("S"),
        singles={"/players/p1": {"tiers": [
            {"channel_id": "c", "channel_name": "C", "tier": "S", "size": 6,
             "updated_at": "2026-01-01"}]}},
    )
    holdings, _ = fetch_tier_holdings(client)
    assert set(holdings) == {"p1"}


def test_fetch_tier_holdings_skips_a_player_whose_profile_has_no_3v3_tier():
    client = FakeClient(pages=_roster_pages("A"), singles={"/players/p1": {"tiers": None}})
    holdings, names = fetch_tier_holdings(client)
    assert holdings == {}
    assert names == {}


def test_fetch_tier_holdings_fetches_each_player_once():
    client = FakeClient(
        pages={("/players", tier): [{"player_id": "p1"}] for tier in ("S", "A", "B", "C", "D", "E")},
        singles={"/players/p1": {"tiers": [
            {"channel_id": "c", "channel_name": "C", "tier": "A", "size": 6,
             "updated_at": "2026-01-01"}]}},
    )
    fetch_tier_holdings(client)
    assert client.calls.count(("/players/p1", "3v3")) == 1


import pytest

from gibhub.build import filter_holdings
from gibhub.tiers import Holding

HOLDINGS = {
    "both": (Holding("ev", "E", "2026-09-18"), Holding("pl", "A", "2026-09-18")),
    "poland_only": (Holding("pl", "S", "2026-09-18"),),
    "events_only": (Holding("ev", "B", "2026-09-18"),),
}
NAMES = {"ev": "ET:Legacy Events: #3vs3", "pl": "Poland ET:Legacy: #3v3"}


def test_no_filter_keeps_everything():
    kept, names = filter_holdings(HOLDINGS, NAMES, None)
    assert kept == HOLDINGS
    assert names == NAMES


def test_a_name_substring_selects_one_channel():
    kept, names = filter_holdings(HOLDINGS, NAMES, ["events"])
    assert set(kept) == {"both", "events_only"}
    assert [h.tier for h in kept["both"]] == ["E"]  # the Poland A is dropped
    assert names == {"ev": "ET:Legacy Events: #3vs3"}


def test_matching_is_case_insensitive():
    assert set(filter_holdings(HOLDINGS, NAMES, ["EVENTS"])[0]) == {"both", "events_only"}


def test_a_channel_id_matches_exactly():
    assert set(filter_holdings(HOLDINGS, NAMES, ["pl"])[0]) == {"both", "poland_only"}


def test_several_tokens_are_ored():
    assert set(filter_holdings(HOLDINGS, NAMES, ["events", "poland"])[0]) == set(HOLDINGS)


def test_a_filter_matching_nothing_raises_and_lists_the_channels():
    with pytest.raises(ValueError, match="Poland ET:Legacy"):
        filter_holdings(HOLDINGS, NAMES, ["nonsense"])
