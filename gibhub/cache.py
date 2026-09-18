"""On-disk cache for finished matches, which the API guarantees are immutable."""

import json
import os
from typing import Any, Callable, Dict, Optional

DEFAULT_ROOT = ".cache"


class MatchCache:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = os.path.join(str(root), "matches")

    def _path(self, match_id: str) -> Optional[str]:
        # A match id is a UUID. Anything containing a separator is not one, and
        # would let a caller write outside the cache directory.
        if not match_id or "/" in match_id or "\\" in match_id or match_id.startswith("."):
            return None
        return os.path.join(self.root, match_id + ".json")

    def get(self, match_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(match_id)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (ValueError, OSError):
            # A truncated or corrupt entry is a miss, not a crash.
            return None

    def put(self, match_id: str, payload: Dict[str, Any]) -> bool:
        """Store a finished match. Returns False if it was refused."""
        path = self._path(match_id)
        if not path or payload.get("state") != "finished":
            return False
        os.makedirs(self.root, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, path)
        return True

    def fetch(self, match_id: str, loader: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
        """Return the cached match, else call `loader` and cache what it returns."""
        cached = self.get(match_id)
        if cached is not None:
            return cached
        payload = loader(match_id)
        self.put(match_id, payload)
        return payload
