"""The only module in this package that performs network I/O."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, Optional

BASE_URL = "https://gibhub.gg/api"
USER_AGENT = "truetier/1.0 (+https://truetier.pages.dev)"
RETRIES = 3
BACKOFF_SECONDS = 1.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class ApiError(Exception):
    """A request failed after exhausting retries, or failed unrecoverably."""


def _encode(params: Optional[Dict[str, Any]]) -> str:
    """Query string builder. Sequence values repeat the key; None values are dropped."""
    if not params:
        return ""
    pairs = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((key, str(item)) for item in value if item is not None)
        else:
            pairs.append((key, str(value)))
    if not pairs:
        return ""
    return "?" + urllib.parse.urlencode(pairs)


class Client:
    def __init__(self, base_url=BASE_URL, token=None, opener=None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.base_url + path + _encode(params)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # The token authorises the _internal endpoints only. Public endpoints must
        # not see it.
        if self.token and path.startswith("/_internal/"):
            request.add_header("Authorization", "Bearer " + self.token)

        last = None
        for attempt in range(RETRIES + 1):
            try:
                with self._opener(request) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                last = error
                if error.code not in RETRY_STATUSES or attempt == RETRIES:
                    raise ApiError(
                        "GET %s failed with HTTP %d" % (path, error.code)
                    ) from error
                self._sleep(self._delay(error, attempt))
            except urllib.error.URLError as error:
                last = error
                if attempt == RETRIES:
                    raise ApiError("GET %s failed: %s" % (path, error.reason)) from error
                self._sleep(BACKOFF_SECONDS * (2 ** attempt))

        raise ApiError("GET %s failed: %s" % (path, last))

    @staticmethod
    def _delay(error: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = None
        if error.headers:
            retry_after = error.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return BACKOFF_SECONDS * (2 ** attempt)

    def paginate(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        page_size: int = 100,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield items across every page of a paginated endpoint.

        Stops at `total_pages`, at an empty page, or once `limit` items are yielded.
        """
        page = 1
        yielded = 0
        while True:
            query = dict(params or {})
            query["page"] = page
            query["pageSize"] = page_size
            payload = self.get(path, query)

            items = payload.get("items") or []
            if not items:
                return

            for item in items:
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

            total_pages = payload.get("total_pages") or 1
            if page >= total_pages:
                return
            page += 1
