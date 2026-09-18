"""Record live API responses into tests/fixtures/. Run manually, commit the output.

    python3 tools/record_fixtures.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gibhub.api import Client  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures")


def write(name, payload):
    path = os.path.join(FIXTURES, name + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
    print("wrote", os.path.normpath(path))


def main():
    client = Client()
    os.makedirs(FIXTURES, exist_ok=True)

    matches = client.get("/matches", {"size": "3v3", "state": "finished", "pageSize": 5})
    write("matches_3v3_finished", matches)

    match_id = matches["items"][0]["match_id"]
    write("match_detail", client.get("/matches/" + match_id))

    player_id = matches["items"][0]["teams"]["alpha"][0]["player_id"]
    write("player_profile", client.get("/players/" + player_id, {"size": "3v3"}))
    write("player_spider", client.get("/players/" + player_id + "/spider", {"size": "3v3"}))
    write("player_search", client.get("/players/search", {"q": "Kredenc", "limit": 5}))
    write("tier_roster_a", client.get("/players", {"size": "3v3", "tier": "A", "pageSize": 100}))
    write(
        "utro_leaderboard",
        client.get(
            "/leaderboards",
            {"metric": "utro_shrunken", "size": "3v3", "minGames": 1, "pageSize": 100},
        ),
    )


if __name__ == "__main__":
    main()
