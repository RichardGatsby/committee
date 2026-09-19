import io
import json
import urllib.error

import pytest

from gibhub.api import ApiError, Client


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _json_response(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def test_get_returns_decoded_json():
    seen = []

    def opener(request):
        seen.append(request.full_url)
        return _json_response({"ok": True})

    client = Client(opener=opener)
    assert client.get("/players/search", {"q": "Oksii"}) == {"ok": True}
    assert seen == ["https://gibhub.gg/api/players/search?q=Oksii"]


def test_get_sends_a_user_agent_because_the_api_403s_without_one():
    captured = {}

    def opener(request):
        captured["ua"] = request.get_header("User-agent")
        return _json_response({})

    Client(opener=opener).get("/maps")
    assert captured["ua"]


def test_get_repeats_array_parameters():
    seen = []

    def opener(request):
        seen.append(request.full_url)
        return _json_response({})

    Client(opener=opener).get("/players", {"tier": ["A", "B"], "size": "3v3"})
    assert seen == ["https://gibhub.gg/api/players?tier=A&tier=B&size=3v3"]


def test_get_omits_none_parameters():
    seen = []

    def opener(request):
        seen.append(request.full_url)
        return _json_response({})

    Client(opener=opener).get("/matches", {"size": "3v3", "to": None})
    assert seen == ["https://gibhub.gg/api/matches?size=3v3"]


def test_bearer_token_is_sent_only_to_internal_paths():
    headers = []

    def opener(request):
        headers.append(request.get_header("Authorization"))
        return _json_response({})

    client = Client(token="secret", opener=opener)
    client.get("/players/search", {"q": "x"})
    client.get("/_internal/resolve-discord-ids", {"playerID": "x"})
    assert headers == [None, "Bearer secret"]


def test_server_errors_are_retried_then_raise():
    attempts = []

    def opener(request):
        attempts.append(1)
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    with pytest.raises(ApiError, match="503"):
        Client(opener=opener, sleep=lambda _: None).get("/maps")
    assert len(attempts) == 4


def test_not_found_is_not_retried():
    attempts = []

    def opener(request):
        attempts.append(1)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    with pytest.raises(ApiError, match="404"):
        Client(opener=opener, sleep=lambda _: None).get("/players/nope")
    assert len(attempts) == 1


def test_a_retry_that_succeeds_returns_the_payload():
    state = {"calls": 0}

    def opener(request):
        state["calls"] += 1
        if state["calls"] == 1:
            raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)
        return _json_response({"recovered": True})

    client = Client(opener=opener, sleep=lambda _: None)
    assert client.get("/maps") == {"recovered": True}


def test_rate_limit_honours_retry_after():
    waits = []
    state = {"calls": 0}

    def opener(request):
        state["calls"] += 1
        if state["calls"] == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many", {"Retry-After": "7"}, None
            )
        return _json_response({})

    Client(opener=opener, sleep=waits.append).get("/maps")
    assert waits == [7.0]


def test_the_error_message_names_the_endpoint():
    def opener(request):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    with pytest.raises(ApiError, match="/players/nope"):
        Client(opener=opener, sleep=lambda _: None).get("/players/nope")


def _paged_opener(pages):
    seen = []

    def opener(request):
        seen.append(request.full_url)
        return _json_response(pages[len(seen) - 1])

    return opener, seen


def test_paginate_walks_every_page():
    pages = [
        {"page": 1, "total_pages": 3, "items": [{"id": 1}, {"id": 2}]},
        {"page": 2, "total_pages": 3, "items": [{"id": 3}]},
        {"page": 3, "total_pages": 3, "items": [{"id": 4}]},
    ]
    opener, seen = _paged_opener(pages)
    items = list(Client(opener=opener).paginate("/matches", {"size": "3v3"}, page_size=2))
    assert [item["id"] for item in items] == [1, 2, 3, 4]
    assert len(seen) == 3
    assert "page=1" in seen[0] and "pageSize=2" in seen[0]
    assert "page=3" in seen[2]


def test_paginate_stops_on_a_single_page():
    opener, seen = _paged_opener([{"page": 1, "total_pages": 1, "items": [{"id": 1}]}])
    assert len(list(Client(opener=opener).paginate("/matches"))) == 1
    assert len(seen) == 1


def test_paginate_stops_on_an_empty_page():
    opener, seen = _paged_opener([{"page": 1, "total_pages": 9, "items": []}])
    assert list(Client(opener=opener).paginate("/matches")) == []
    assert len(seen) == 1


def test_paginate_tolerates_a_null_items_field():
    opener, _ = _paged_opener([{"page": 1, "total_pages": 1, "items": None}])
    assert list(Client(opener=opener).paginate("/matches")) == []


def test_paginate_respects_a_limit():
    pages = [
        {"page": 1, "total_pages": 5, "items": [{"id": 1}, {"id": 2}]},
        {"page": 2, "total_pages": 5, "items": [{"id": 3}, {"id": 4}]},
    ]
    opener, seen = _paged_opener(pages)
    items = list(Client(opener=opener).paginate("/matches", page_size=2, limit=3))
    assert [item["id"] for item in items] == [1, 2, 3]
    assert len(seen) == 2


def test_the_user_agent_names_the_site_rather_than_the_api_it_calls():
    """It goes to someone else's server, so it should say who is calling."""
    from gibhub.api import USER_AGENT

    assert "committee" not in USER_AGENT.lower()
    assert "truetier" in USER_AGENT
    assert "truetier.pages.dev" in USER_AGENT
