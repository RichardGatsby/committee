"""Contract checks against the live API.

    GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py -v
"""

import os

import pytest

from gibhub.api import Client

pytestmark = pytest.mark.skipif(
    os.environ.get("GIBHUB_INTEGRATION") != "1",
    reason="set GIBHUB_INTEGRATION=1 to hit the live API",
)


@pytest.fixture(scope="module")
def client():
    return Client()


def test_the_match_list_still_has_rosters_and_channels(client):
    payload = client.get("/matches", {"size": "3v3", "state": "finished", "pageSize": 3})
    item = payload["items"][0]
    assert item["size_label"] == "3v3"
    assert item["channel_id"]
    assert len(item["teams"]["alpha"]) == 3
    assert item["teams"]["alpha"][0]["player_id"]


def test_match_detail_still_reports_utro_and_playtime(client):
    listing = client.get("/matches", {"size": "3v3", "state": "finished", "pageSize": 1})
    detail = client.get("/matches/" + listing["items"][0]["match_id"])
    entry = detail["rounds"][0]["alpha"][0]
    assert "utro" in entry
    assert "playtime_percent" in entry


def test_match_detail_still_carries_no_teams_block(client):
    """The roster fallback in dataset.roster_ids exists because of this."""
    listing = client.get("/matches", {"size": "3v3", "state": "finished", "pageSize": 1})
    detail = client.get("/matches/" + listing["items"][0]["match_id"])
    assert not detail.get("teams")


def test_the_utro_leaderboard_still_serves_every_3v3_player(client):
    payload = client.get(
        "/leaderboards",
        {"metric": "utro_shrunken", "size": "3v3", "minGames": 1, "pageSize": 5},
    )
    assert payload["total"] > 100
    assert payload["items"][0]["player_id"]
    assert "rounds" in payload["items"][0]


def test_the_leaderboard_page_size_cap_is_still_100(client):
    """build.py pages at 100 because 101 is rejected."""
    from gibhub.api import ApiError

    with pytest.raises(ApiError, match="422"):
        client.get(
            "/leaderboards",
            {"metric": "utro_shrunken", "size": "3v3", "minGames": 1, "pageSize": 101},
        )


def test_tier_rosters_are_still_served_per_size(client):
    payload = client.get("/players", {"size": "3v3", "tier": "A", "pageSize": 5})
    assert payload["total"] > 0


def test_a_tiered_profile_still_carries_per_channel_tiers(client):
    roster = client.get("/players", {"size": "3v3", "tier": "A", "pageSize": 1})
    profile = client.get("/players/" + roster["items"][0]["player_id"], {"size": "3v3"})
    tiers = profile.get("tiers") or []
    assert any(entry.get("size") == 6 for entry in tiers)
    assert "lifetime" in profile
