import pytest

from gibhub.fetch import AmbiguousPlayer, PlayerNotFound, fetch_player_data, resolve_player


class FakeClient:
    def __init__(self, singles=None, pages=None):
        self.singles = singles or {}
        self.pages = pages or {}
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(path)
        return self.singles[path]

    def paginate(self, path, params=None, page_size=100, limit=None):
        self.calls.append(path)
        items = self.pages.get(path, [])
        return iter(items if limit is None else items[:limit])


def test_a_uuid_is_used_directly_without_searching():
    client = FakeClient()
    uuid = "b04c4850-29c9-52a9-babe-f1feadbeb206"
    assert resolve_player(client, uuid) == uuid
    assert client.calls == []


def test_a_name_is_resolved_through_search():
    client = FakeClient(singles={"/players/search": {"data": [{"player_id": "p1", "nick": "x"}]}})
    assert resolve_player(client, "Kredenc") == "p1"


def test_an_unknown_name_raises():
    client = FakeClient(singles={"/players/search": {"data": []}})
    with pytest.raises(PlayerNotFound, match="Ghost"):
        resolve_player(client, "Ghost")


def test_an_ambiguous_name_lists_the_candidates():
    client = FakeClient(
        singles={"/players/search": {"data": [
            {"player_id": "p1", "nick": "^1kiz", "discord_nick": "kizA"},
            {"player_id": "p2", "nick": "kiz2", "discord_nick": "kizB"},
        ]}}
    )
    with pytest.raises(AmbiguousPlayer) as excinfo:
        resolve_player(client, "kiz")
    assert "p1" in str(excinfo.value)
    assert "p2" in str(excinfo.value)


def test_an_exact_discord_nick_match_wins_over_ambiguity():
    client = FakeClient(
        singles={"/players/search": {"data": [
            {"player_id": "p1", "nick": "^1kiz", "discord_nick": "kiz"},
            {"player_id": "p2", "nick": "kiz2", "discord_nick": "kiz2"},
        ]}}
    )
    assert resolve_player(client, "kiz", exact=True) == "p1"


def test_fetch_player_data_pulls_profile_spider_and_match_details():
    client = FakeClient(
        singles={
            "/players/p1": {"player_id": "p1"},
            "/players/p1/spider": {"metrics": []},
            "/matches/m1": {"match_id": "m1", "state": "finished"},
            "/matches/m2": {"match_id": "m2", "state": "finished"},
        },
        pages={"/players/p1/matches": [{"match_id": "m1"}, {"match_id": "m2"}]},
    )
    profile, spider, details = fetch_player_data(client, "p1", matches=5, range_="6m")
    assert profile["player_id"] == "p1"
    assert spider == {"metrics": []}
    assert [d["match_id"] for d in details] == ["m1", "m2"]


def test_fetch_player_data_honours_the_match_limit():
    client = FakeClient(
        singles={
            "/players/p1": {"player_id": "p1"},
            "/players/p1/spider": {"metrics": []},
            "/matches/m1": {"match_id": "m1", "state": "finished"},
        },
        pages={"/players/p1/matches": [{"match_id": "m1"}, {"match_id": "m2"}]},
    )
    _, _, details = fetch_player_data(client, "p1", matches=1, range_="6m")
    assert len(details) == 1


def test_fetch_player_data_uses_the_cache_when_given_one(tmp_path):
    from gibhub.cache import MatchCache

    client = FakeClient(
        singles={
            "/players/p1": {"player_id": "p1"},
            "/players/p1/spider": {"metrics": []},
            "/matches/m1": {"match_id": "m1", "state": "finished"},
        },
        pages={"/players/p1/matches": [{"match_id": "m1"}]},
    )
    cache = MatchCache(tmp_path)
    fetch_player_data(client, "p1", matches=5, range_="6m", cache=cache)
    fetch_player_data(client, "p1", matches=5, range_="6m", cache=cache)
    assert client.calls.count("/matches/m1") == 1
