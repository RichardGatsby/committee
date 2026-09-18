from gibhub.cache import MatchCache


def test_a_miss_returns_none(tmp_path):
    assert MatchCache(tmp_path).get("abc") is None


def test_a_finished_match_round_trips(tmp_path):
    cache = MatchCache(tmp_path)
    payload = {"match_id": "abc", "state": "finished", "winner": "alpha"}
    assert cache.put("abc", payload) is True
    assert cache.get("abc") == payload


def test_an_unfinished_match_is_refused(tmp_path):
    cache = MatchCache(tmp_path)
    assert cache.put("abc", {"match_id": "abc", "state": "waiting_report"}) is False
    assert cache.get("abc") is None


def test_it_survives_a_new_instance(tmp_path):
    MatchCache(tmp_path).put("abc", {"state": "finished", "n": 1})
    assert MatchCache(tmp_path).get("abc") == {"state": "finished", "n": 1}


def test_a_corrupt_entry_reads_as_a_miss(tmp_path):
    cache = MatchCache(tmp_path)
    cache.put("abc", {"state": "finished"})
    (tmp_path / "matches" / "abc.json").write_text("{not json", encoding="utf-8")
    assert cache.get("abc") is None


def test_a_match_id_with_path_separators_is_rejected(tmp_path):
    cache = MatchCache(tmp_path)
    assert cache.put("../escape", {"state": "finished"}) is False
    assert cache.get("../escape") is None


def test_fetch_uses_the_cache_on_the_second_call(tmp_path):
    calls = []

    def fetch(match_id):
        calls.append(match_id)
        return {"match_id": match_id, "state": "finished"}

    cache = MatchCache(tmp_path)
    first = cache.fetch("abc", fetch)
    second = cache.fetch("abc", fetch)
    assert first == second
    assert calls == ["abc"]


def test_fetch_does_not_cache_an_unfinished_match(tmp_path):
    calls = []

    def fetch(match_id):
        calls.append(match_id)
        return {"match_id": match_id, "state": "waiting_report"}

    cache = MatchCache(tmp_path)
    cache.fetch("abc", fetch)
    cache.fetch("abc", fetch)
    assert calls == ["abc", "abc"]
