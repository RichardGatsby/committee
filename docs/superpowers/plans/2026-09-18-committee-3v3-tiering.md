# 3v3 Committee Tiering Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `committee` CLI that produces reproducible, paste-ready evidence for the 3v3 tiering committee: per player, the win probability their tier composition implied for each match versus what actually happened, alongside their own in-match performance.

**Architecture:** A logistic regression over per-tier headcount differences predicts P(alpha wins) for a 3v3 match. Coefficients, the per-channel tier index, and per-player UTRO are fitted once and frozen into a committed model bundle (`coefficients.json`), so reports are reproducible without re-deriving anything. Only `gibhub/api.py` touches the network; `model.py`, `report.py`, and `render.py` are pure functions over plain data.

**Tech Stack:** Python 3.9+, standard library only at runtime. pytest for tests. No runtime third-party dependencies.

---

## Background for the implementer

You have no context on this domain. Here is what you need.

**The game and the data.** gibhub.gg tracks Wolfenstein: Enemy Territory matches. A *3v3 match* has two sides named `alpha` and `beta`, three players each. A match is played over several *rounds*, each on a *map*. Every player in every round has a **UTRO** score — the site's per-round performance rating, roughly 0.5–1.5, where higher is better. The API describes itself in `openapi.yaml` at the repo root.

**Tiers.** A committee assigns players a *gather tier* from `S, A, B, C, D, E`. **These are not an alphabetical ladder:** measured after implementation, the strength order is S > E > A > B > C > D, so E is the second strongest tier (see README). Nothing in this plan assumes an order. Tiers are assigned **per Discord channel**, so one player can be `A` in one channel and untiered in another. Only 134 players hold a 3v3 tier; most players in any given match do not.

**What we are computing.** If we know each of the six players' tiers, we can predict which side should have won. Comparing that prediction to the actual result over a player's last N matches tells the committee whether that player's record is consistent with the tier they hold. That's the whole product.

**The full design rationale** — including why the API's own `betting.odds` field is unusable — is in `docs/superpowers/specs/2026-09-18-committee-3v3-tiering-design.md`. Read it before starting.

**API access.** Public endpoints need no authentication. Base URL `https://gibhub.gg/api`. Do not send the bearer token to public endpoints; only `/api/_internal/resolve-discord-ids` uses it, and this tool does not call that endpoint. The token lives in the `GIBHUB_TOKEN` environment variable and is never committed.

**Note:** `urllib` requests to this API return **403 Forbidden without a `User-Agent` header**. `api.py` must always set one.

---

## Deviations from the spec

Two refinements discovered while verifying the API. Both are improvements; implement the plan, not the spec, where they differ.

1. **Three modules are added** that the spec's component table does not list, all to keep `model.py`, `tiers.py`, and `report.py` free of I/O as the spec requires:
   - `gibhub/bundle.py` — loading and saving the model bundle. The spec implied this lived in `model.py`, which is specified as pure.
   - `gibhub/build.py` — the fetching that feeds a bundle, kept out of `tiers.py`.
   - `gibhub/fetch.py` — the fetching that feeds a report, kept out of `report.py`.

2. **Imputation uses the leaderboard, not per-player profiles.** The spec implied fetching a profile per untiered player. `GET /api/leaderboards?metric=utro_shrunken&size=3v3&minGames=1` returns all 360 3v3 players with a sample-regularised UTRO in one sweep. `utro_shrunken` is used rather than raw `utro` because the raw board is dominated by tiny samples (its top entry is a 1.71 from a single round). Both are frozen into the bundle at fit time.

---

## File structure

| File | Responsibility | Network I/O |
| --- | --- | --- |
| `gibhub/__init__.py` | package marker | no |
| `gibhub/api.py` | HTTP GET + JSON, retry/backoff, pagination | **yes** |
| `gibhub/cache.py` | disk cache for finished matches | no (disk) |
| `gibhub/model.py` | pure: feature vectors, logistic fit, predict, metrics | no |
| `gibhub/bundle.py` | load/save the model bundle `coefficients.json` | no (disk) |
| `gibhub/tiers.py` | tier index, UTRO bands, three-step tier resolution | no (takes fetched data) |
| `gibhub/build.py` | fetches everything needed to build a bundle | via api |
| `gibhub/dataset.py` | finished matches → training samples | via api |
| `gibhub/fetch.py` | fetches one player's profile, spider and match details | via api |
| `gibhub/report.py` | pure: fetched data + bundle → `PlayerReport` | no |
| `gibhub/render.py` | pure: `PlayerReport` → markdown / CSV / JSON | no |
| `gibhub/cli.py` | argument parsing and wiring | via api |
| `coefficients.json` | committed model bundle | — |

`tiers.py` is deliberately pure over already-fetched data; `build.py` does the fetching. That keeps the resolution rules — the part most likely to need changing — trivially testable.

---

## Task 1: Project scaffold

**Files:**
- Create: `gibhub/__init__.py`
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `README.md`

- [ ] **Step 1: Create the package and test config**

```bash
mkdir -p gibhub tests/fixtures
touch gibhub/__init__.py tests/__init__.py
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
addopts = -q
markers =
    integration: hits the live gibhub API; run with GIBHUB_INTEGRATION=1
```

- [ ] **Step 2: Write a smoke test**

`tests/test_package.py`:

```python
def test_package_imports():
    import gibhub

    assert gibhub is not None
```

- [ ] **Step 3: Run it**

Run: `python3 -m pytest tests/test_package.py -v`
Expected: PASS, 1 test.

- [ ] **Step 4: Write the README stub**

`README.md`:

```markdown
# committee

Evidence generator for the ET:Legacy 3v3 tiering committee.

Requires Python 3.9+. No runtime dependencies.

    python3 -m gibhub.cli player Kredenc
    python3 -m gibhub.cli bulk --tier A --out tier-a.csv
    python3 -m gibhub.cli fit --refit

See `docs/superpowers/specs/2026-09-18-committee-3v3-tiering-design.md` for design.
```

- [ ] **Step 5: Commit**

```bash
git add gibhub tests pytest.ini README.md
git commit -m "chore: scaffold package and pytest config

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Model — sigmoid, feature vectors, predict

**Files:**
- Create: `gibhub/model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_model.py`:

```python
import pytest

from gibhub.model import TIERS, feature_vector, predict, sigmoid


def test_sigmoid_at_zero_is_exactly_half():
    assert sigmoid(0.0) == 0.5


def test_sigmoid_is_monotonic_and_bounded():
    assert 0.0 < sigmoid(-50.0) < sigmoid(0.0) < sigmoid(50.0) < 1.0


def test_sigmoid_does_not_overflow_on_large_negative():
    assert sigmoid(-1000.0) == pytest.approx(0.0, abs=1e-12)


def test_tier_order_is_strongest_first():
    assert TIERS == ("S", "A", "B", "C", "D", "E")


def test_feature_vector_counts_the_difference_per_tier():
    features = feature_vector(["S", "A", "A"], ["B", "C", "E"])
    assert features == [1.0, 2.0, -1.0, -1.0, 0.0, -1.0]


def test_mirrored_rosters_give_a_zero_vector():
    assert feature_vector(["S", "B", "D"], ["D", "S", "B"]) == [0.0] * 6


def test_feature_vector_rejects_an_unknown_tier():
    with pytest.raises(ValueError, match="unknown tier 'Z'"):
        feature_vector(["Z", "A", "A"], ["B", "C", "E"])


def test_predict_on_mirrored_rosters_is_exactly_half():
    coefficients = [0.9, 0.6, 0.3, 0.0, -0.4, -0.8]
    assert predict(coefficients, feature_vector(["S", "B", "D"], ["D", "S", "B"])) == 0.5


def test_predict_favours_the_stronger_side():
    coefficients = [0.9, 0.6, 0.3, 0.0, -0.4, -0.8]
    assert predict(coefficients, feature_vector(["S", "S", "S"], ["E", "E", "E"])) > 0.9
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.model'`

- [ ] **Step 3: Implement**

`gibhub/model.py`:

```python
"""Pure scoring model. No I/O, no API knowledge."""

import math
from typing import Dict, Iterable, List, Sequence, Tuple

TIERS = ("S", "A", "B", "C", "D", "E")

Features = List[float]
# (features, outcome). Named to avoid colliding with dataset.Sample, which is a
# richer record carrying the match id and tier provenance.
TrainingPair = Tuple[Sequence[float], int]


def sigmoid(z: float) -> float:
    """Logistic function, written to avoid overflow at large |z|."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def feature_vector(alpha_tiers: Iterable[str], beta_tiers: Iterable[str]) -> Features:
    """Per-tier headcount difference, alpha minus beta, in TIERS order."""
    counts: Dict[str, float] = {tier: 0.0 for tier in TIERS}
    for tier in alpha_tiers:
        if tier not in counts:
            raise ValueError("unknown tier %r" % tier)
        counts[tier] += 1.0
    for tier in beta_tiers:
        if tier not in counts:
            raise ValueError("unknown tier %r" % tier)
        counts[tier] -= 1.0
    return [counts[tier] for tier in TIERS]


def predict(coefficients: Sequence[float], features: Sequence[float]) -> float:
    """P(alpha wins). A zero feature vector returns exactly 0.5."""
    return sigmoid(sum(c * f for c, f in zip(coefficients, features)))
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_model.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/model.py tests/test_model.py
git commit -m "feat: add tier feature vectors and logistic prediction

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Model — fit and metrics

**Files:**
- Modify: `gibhub/model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_model.py`:

```python
from gibhub.model import fit, metrics


def _separable_samples():
    """Alpha wins whenever it has one extra S; beta wins the mirror image."""
    samples = []
    for _ in range(20):
        samples.append(([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1))
        samples.append(([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0))
    return samples


def test_fit_learns_a_positive_weight_for_the_deciding_tier():
    weights = fit(_separable_samples())
    assert weights[0] > 0.5
    assert all(abs(w) < 1e-9 for w in weights[1:])


def test_fit_is_deterministic():
    assert fit(_separable_samples()) == fit(_separable_samples())


def test_fit_rejects_an_empty_sample_set():
    with pytest.raises(ValueError, match="no samples"):
        fit([])


def test_fit_on_balanced_evidence_stays_near_zero():
    samples = [([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1), ([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0)]
    assert fit(samples)[0] == pytest.approx(0.0, abs=1e-9)


def test_metrics_on_a_perfect_fit():
    samples = _separable_samples()
    result = metrics(fit(samples), samples)
    assert result["accuracy"] == 1.0
    assert result["brier"] < 0.25
    assert result["log_loss"] < 0.7
    assert result["samples"] == 40


def test_metrics_on_a_coin_flip_model():
    samples = _separable_samples()
    result = metrics([0.0] * 6, samples)
    assert result["brier"] == pytest.approx(0.25)
    assert result["log_loss"] == pytest.approx(0.6931471805599453)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'fit'`

- [ ] **Step 3: Implement**

Append to `gibhub/model.py`:

```python
ITERATIONS = 2000
LEARNING_RATE = 0.5
_EPSILON = 1e-12


def fit(
    samples: Sequence[TrainingPair],
    *,
    iterations: int = ITERATIONS,
    learning_rate: float = LEARNING_RATE,
) -> Features:
    """Batch gradient descent on the log-likelihood. No intercept: the sides are
    symmetric, so a mirrored roster must score exactly 0.5.

    Zero-initialised with a fixed step count, so the result is deterministic.
    """
    if not samples:
        raise ValueError("no samples to fit")

    width = len(TIERS)
    weights = [0.0] * width
    count = float(len(samples))

    for _ in range(iterations):
        gradient = [0.0] * width
        for features, outcome in samples:
            error = predict(weights, features) - outcome
            for index in range(width):
                gradient[index] += error * features[index]
        for index in range(width):
            weights[index] -= learning_rate * gradient[index] / count

    return weights


def metrics(coefficients: Sequence[float], samples: Sequence[TrainingPair]) -> Dict[str, float]:
    """Log loss, Brier score, and accuracy of `coefficients` over `samples`."""
    if not samples:
        raise ValueError("no samples to score")

    log_loss = 0.0
    brier = 0.0
    correct = 0

    for features, outcome in samples:
        p = predict(coefficients, features)
        clamped = min(max(p, _EPSILON), 1.0 - _EPSILON)
        log_loss -= outcome * math.log(clamped) + (1 - outcome) * math.log(1.0 - clamped)
        brier += (p - outcome) ** 2
        if (p >= 0.5) == bool(outcome):
            correct += 1

    count = float(len(samples))
    return {
        "log_loss": log_loss / count,
        "brier": brier / count,
        "accuracy": correct / count,
        "samples": len(samples),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_model.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/model.py tests/test_model.py
git commit -m "feat: fit tier coefficients by gradient descent with fit metrics

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: API client — GET with retry

**Files:**
- Create: `gibhub/api.py`
- Test: `tests/test_api.py`

The client takes an `opener` callable so tests never touch the network. The opener
signature is `opener(request) -> file-like with .read() and .status`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`:

```python
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
    assert len(attempts) == 4  # one attempt plus three retries


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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.api'`

- [ ] **Step 3: Implement**

`gibhub/api.py`:

```python
"""The only module in this package that performs network I/O."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, Optional

BASE_URL = "https://gibhub.gg/api"
USER_AGENT = "committee-tiering-tool/1.0 (+https://gibhub.gg)"
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/api.py tests/test_api.py
git commit -m "feat: add gibhub HTTP client with retry and scoped bearer token

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: API client — pagination

**Files:**
- Modify: `gibhub/api.py`
- Test: `tests/test_api.py`

Paginated endpoints return `{"page", "per_page", "total", "total_pages", "items"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def _paged_opener(pages):
    """Serve a canned list of page payloads in order, recording the URLs asked for."""
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
    pages = [{"page": 1, "total_pages": 9, "items": []}]
    opener, seen = _paged_opener(pages)
    assert list(Client(opener=opener).paginate("/matches")) == []
    assert len(seen) == 1


def test_paginate_tolerates_a_null_items_field():
    pages = [{"page": 1, "total_pages": 1, "items": None}]
    opener, _ = _paged_opener(pages)
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: FAIL — `AttributeError: 'Client' object has no attribute 'paginate'`

- [ ] **Step 3: Implement**

Add to `Client` in `gibhub/api.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/api.py tests/test_api.py
git commit -m "feat: add paginated iteration to the gibhub client

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Match cache

**Files:**
- Create: `gibhub/cache.py`
- Test: `tests/test_cache.py`

Only *finished* matches may be cached — they are immutable. Anything else must be
refused by the cache itself so no caller can accidentally freeze a live match.

- [ ] **Step 1: Write the failing tests**

`tests/test_cache.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.cache'`

- [ ] **Step 3: Implement**

`gibhub/cache.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_cache.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/cache.py tests/test_cache.py
git commit -m "feat: cache finished matches on disk

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Tier bands and imputation

**Files:**
- Create: `gibhub/tiers.py`
- Test: `tests/test_tiers.py`

A *band* is the median lifetime 3v3 `utro_shrunken` of the players holding a tier.
An untiered player is assigned the tier whose band is nearest their own UTRO.

- [ ] **Step 1: Write the failing tests**

`tests/test_tiers.py`:

```python
import pytest

from gibhub.tiers import build_bands, nearest_tier

BANDS = {"S": 1.30, "A": 1.15, "B": 1.00, "C": 0.90, "D": 0.80, "E": 0.70}


def test_nearest_tier_picks_the_closest_band():
    assert nearest_tier(BANDS, 1.29) == "S"
    assert nearest_tier(BANDS, 1.01) == "B"
    assert nearest_tier(BANDS, 0.10) == "E"
    assert nearest_tier(BANDS, 9.00) == "S"


def test_nearest_tier_breaks_ties_towards_the_stronger_tier():
    # 1.075 is equidistant from A (1.15) and B (1.00) at 0.075.
    assert nearest_tier(BANDS, 1.075) == "A"


def test_nearest_tier_without_a_utro_falls_back_to_the_median_band():
    # The six band values have a median of (1.00 + 0.90) / 2 = 0.95, nearest to C.
    assert nearest_tier(BANDS, None) == "C"


def test_nearest_tier_rejects_empty_bands():
    with pytest.raises(ValueError, match="no tier bands"):
        nearest_tier({}, 1.0)


def test_build_bands_takes_the_median_utro_per_tier():
    holders = {"S": ["p1", "p2", "p3"], "A": ["p4", "p5"]}
    utro = {"p1": 1.4, "p2": 1.3, "p3": 1.2, "p4": 1.1, "p5": 1.0}
    assert build_bands(holders, utro) == {"S": 1.3, "A": pytest.approx(1.05)}


def test_build_bands_ignores_holders_with_no_utro():
    holders = {"S": ["p1", "ghost"]}
    assert build_bands(holders, {"p1": 1.4}) == {"S": 1.4}


def test_build_bands_drops_a_tier_with_no_usable_holders():
    assert build_bands({"S": ["ghost"], "A": ["p1"]}, {"p1": 1.1}) == {"A": 1.1}
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_tiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.tiers'`

- [ ] **Step 3: Implement**

`gibhub/tiers.py`:

```python
"""Tier resolution. Pure functions over data that build.py has already fetched."""

from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .model import TIERS


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def build_bands(
    holders: Mapping[str, Iterable[str]], utro: Mapping[str, float]
) -> Dict[str, float]:
    """Median UTRO per tier. Tiers whose holders all lack a UTRO are dropped."""
    bands = {}
    for tier, player_ids in holders.items():
        values = [utro[pid] for pid in player_ids if pid in utro]
        if values:
            bands[tier] = _median(values)
    return bands


def nearest_tier(bands: Mapping[str, float], utro: Optional[float]) -> str:
    """The tier whose band is closest to `utro`.

    Ties go to the stronger tier, so the result never depends on dict ordering.
    With no UTRO at all, the median band stands in for the player.
    """
    if not bands:
        raise ValueError("no tier bands available")
    if utro is None:
        utro = _median(list(bands.values()))
    return min(bands, key=lambda tier: (abs(bands[tier] - utro), TIERS.index(tier)))
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_tiers.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/tiers.py tests/test_tiers.py
git commit -m "feat: derive tier bands and impute a tier from UTRO

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Tier resolution — the three paths

**Files:**
- Modify: `gibhub/tiers.py`
- Test: `tests/test_tiers.py`

Resolution order, from the spec: exact channel tier, then most-recent tier from
another channel, then imputed from UTRO.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tiers.py`:

```python
from gibhub.tiers import Holding, ResolvedTier, TierIndex

HOLDINGS = {
    "multi": (
        Holding(channel_id="poland", tier="B", updated_at="2026-01-01T00:00:00+01:00"),
        Holding(channel_id="events", tier="A", updated_at="2026-09-01T00:00:00+02:00"),
    ),
    "single": (Holding(channel_id="poland", tier="S", updated_at="2026-05-01T00:00:00+02:00"),),
}


def _index():
    return TierIndex(holdings=HOLDINGS, bands=BANDS, utro={"nobody": 0.79, "multi": 1.2})


def test_an_exact_channel_tier_wins():
    assert _index().resolve("multi", "poland") == ResolvedTier("B", "exact")
    assert _index().resolve("multi", "events") == ResolvedTier("A", "exact")


def test_another_channels_tier_is_used_when_the_match_channel_has_none():
    # The events holding is the most recently updated of the two.
    assert _index().resolve("multi", "somewhere-else") == ResolvedTier("A", "cross_channel")


def test_a_single_holding_is_used_across_channels():
    assert _index().resolve("single", "events") == ResolvedTier("S", "cross_channel")


def test_an_untiered_player_is_imputed_from_utro():
    assert _index().resolve("nobody", "poland") == ResolvedTier("D", "imputed")


def test_a_player_with_neither_tier_nor_utro_is_imputed_from_the_median_band():
    assert _index().resolve("ghost", "poland") == ResolvedTier("C", "imputed")


def test_resolve_all_returns_one_result_per_player_in_order():
    resolved = _index().resolve_all(["multi", "ghost"], "poland")
    assert resolved == [ResolvedTier("B", "exact"), ResolvedTier("C", "imputed")]


def test_tiers_of_returns_just_the_letters():
    assert _index().tiers_of(["multi", "ghost"], "poland") == ["B", "C"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_tiers.py -v`
Expected: FAIL — `ImportError: cannot import name 'Holding'`

- [ ] **Step 3: Implement**

Append to `gibhub/tiers.py`:

```python
import dataclasses

EXACT = "exact"
CROSS_CHANNEL = "cross_channel"
IMPUTED = "imputed"


@dataclasses.dataclass(frozen=True)
class Holding:
    """A tier a player holds in one channel."""

    channel_id: str
    tier: str
    updated_at: str


@dataclasses.dataclass(frozen=True)
class ResolvedTier:
    tier: str
    source: str  # EXACT, CROSS_CHANNEL or IMPUTED


@dataclasses.dataclass(frozen=True)
class TierIndex:
    """Everything needed to assign a tier to any player in any channel."""

    holdings: Mapping[str, Sequence[Holding]]
    bands: Mapping[str, float]
    utro: Mapping[str, float]

    def resolve(self, player_id: str, channel_id: Optional[str]) -> ResolvedTier:
        held = self.holdings.get(player_id) or ()

        for holding in held:
            if holding.channel_id == channel_id:
                return ResolvedTier(holding.tier, EXACT)

        if held:
            # No tier in this channel: fall back to the most recently updated one.
            newest = max(held, key=lambda holding: holding.updated_at)
            return ResolvedTier(newest.tier, CROSS_CHANNEL)

        return ResolvedTier(nearest_tier(self.bands, self.utro.get(player_id)), IMPUTED)

    def resolve_all(
        self, player_ids: Iterable[str], channel_id: Optional[str]
    ) -> List[ResolvedTier]:
        return [self.resolve(player_id, channel_id) for player_id in player_ids]

    def tiers_of(self, player_ids: Iterable[str], channel_id: Optional[str]) -> List[str]:
        return [resolved.tier for resolved in self.resolve_all(player_ids, channel_id)]
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_tiers.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/tiers.py tests/test_tiers.py
git commit -m "feat: resolve a player's tier by channel, cross-channel, or imputation

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Record API fixtures

**Files:**
- Create: `tools/record_fixtures.py`
- Create: `tests/fixtures/*.json` (generated)

Later tasks parse real API payloads. Record them once so tests assert against
real shapes rather than shapes we imagined.

- [ ] **Step 1: Write the recorder**

`tools/record_fixtures.py`:

```python
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
    print("wrote", path)


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
    write(
        "tier_roster_a",
        client.get("/players", {"size": "3v3", "tier": "A", "pageSize": 200}),
    )
    write(
        "utro_leaderboard",
        client.get(
            "/leaderboards",
            {"metric": "utro_shrunken", "size": "3v3", "minGames": 1, "pageSize": 200},
        ),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the live API**

Run: `python3 tools/record_fixtures.py`
Expected: seven `wrote tests/fixtures/*.json` lines and no traceback.

- [ ] **Step 3: Verify the fixtures have the fields later tasks rely on**

Run:

```bash
python3 - <<'PY'
import json
m = json.load(open("tests/fixtures/match_detail.json"))
assert m["state"] == "finished"
assert m["size_label"] == "3v3"
assert m["winner"] in ("alpha", "beta")
assert m["rounds"], "expected rounds"
assert "utro" in m["rounds"][0]["alpha"][0]
assert "playtime_percent" in m["rounds"][0]["alpha"][0]

lst = json.load(open("tests/fixtures/matches_3v3_finished.json"))
assert lst["items"][0]["teams"]["alpha"]

prof = json.load(open("tests/fixtures/player_profile.json"))
assert "lifetime" in prof and "matches" in prof["lifetime"]

lb = json.load(open("tests/fixtures/utro_leaderboard.json"))
assert lb["items"][0]["player_id"] and lb["items"][0]["value"]
print("fixtures OK")
PY
```

Expected: `fixtures OK`

- [ ] **Step 4: Commit**

```bash
git add tools/record_fixtures.py tests/fixtures
git commit -m "test: record live API fixtures for offline tests

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Dataset — matches to training samples

**Files:**
- Create: `gibhub/dataset.py`
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_dataset.py`:

```python
import json

from gibhub.dataset import match_to_sample, roster_ids
from gibhub.tiers import Holding, TierIndex

BANDS = {"S": 1.30, "A": 1.15, "B": 1.00, "C": 0.90, "D": 0.80, "E": 0.70}


def _index(holdings=None, utro=None):
    return TierIndex(holdings=holdings or {}, bands=BANDS, utro=utro or {})


def _match(**overrides):
    match = {
        "match_id": "m1",
        "channel_id": "poland",
        "winner": "alpha",
        "state": "finished",
        "teams": {
            "alpha": [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}],
            "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
        },
    }
    match.update(overrides)
    return match


def test_roster_ids_reads_both_sides():
    assert roster_ids(_match()) == (["a1", "a2", "a3"], ["b1", "b2", "b3"])


def test_roster_ids_tolerates_a_null_side():
    match = _match(teams={"alpha": None, "beta": None})
    assert roster_ids(match) == ([], [])


def test_an_alpha_win_is_outcome_one():
    sample = match_to_sample(_match(), _index())
    assert sample.outcome == 1
    assert sample.match_id == "m1"


def test_a_beta_win_is_outcome_zero():
    assert match_to_sample(_match(winner="beta"), _index()).outcome == 0


def test_a_draw_is_skipped():
    assert match_to_sample(_match(winner=""), _index()) is None


def test_a_missing_winner_is_skipped():
    assert match_to_sample(_match(winner=None), _index()) is None


def test_an_incomplete_roster_is_skipped():
    match = _match()
    match["teams"]["alpha"] = [{"player_id": "a1"}, {"player_id": "a2"}]
    assert match_to_sample(match, _index()) is None


def test_features_reflect_the_resolved_tiers():
    holdings = {
        "a1": (Holding("poland", "S", "2026-01-01"),),
        "b1": (Holding("poland", "E", "2026-01-01"),),
    }
    # a2, a3, b2, b3 are untiered with no UTRO, so all impute to the median band (C).
    sample = match_to_sample(_match(), _index(holdings=holdings))
    assert sample.features == [1.0, 0.0, 0.0, 0.0, 0.0, -1.0]


def test_sources_are_recorded_for_all_six_players():
    holdings = {"a1": (Holding("poland", "S", "2026-01-01"),)}
    sample = match_to_sample(_match(), _index(holdings=holdings))
    assert sample.sources == ["exact"] + ["imputed"] * 5


def test_it_handles_the_recorded_fixture():
    match = json.load(open("tests/fixtures/match_detail.json"))
    sample = match_to_sample(match, _index())
    assert sample is not None
    assert sample.outcome in (0, 1)
    assert len(sample.features) == 6
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.dataset'`

- [ ] **Step 3: Implement**

`gibhub/dataset.py`:

```python
"""Turning API match payloads into model samples."""

import dataclasses
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .model import feature_vector
from .tiers import TierIndex

TEAM_SIZE = 3


@dataclasses.dataclass(frozen=True)
class Sample:
    match_id: str
    features: List[float]
    outcome: int  # 1 when alpha won, 0 when beta won
    sources: List[str]


def roster_ids(match: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    teams = match.get("teams") or {}
    alpha = [player["player_id"] for player in (teams.get("alpha") or [])]
    beta = [player["player_id"] for player in (teams.get("beta") or [])]
    return alpha, beta


def match_to_sample(match: Dict[str, Any], index: TierIndex) -> Optional[Sample]:
    """None when the match cannot train the model: a draw, or an odd roster."""
    winner = match.get("winner")
    if winner not in ("alpha", "beta"):
        return None

    alpha, beta = roster_ids(match)
    if len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
        return None

    channel_id = match.get("channel_id")
    alpha_resolved = index.resolve_all(alpha, channel_id)
    beta_resolved = index.resolve_all(beta, channel_id)

    return Sample(
        match_id=match.get("match_id", ""),
        features=feature_vector(
            [r.tier for r in alpha_resolved], [r.tier for r in beta_resolved]
        ),
        outcome=1 if winner == "alpha" else 0,
        sources=[r.source for r in alpha_resolved + beta_resolved],
    )


def iter_samples(
    client, index: TierIndex, to: Optional[str] = None, limit: Optional[int] = None
) -> Iterator[Sample]:
    """Walk every finished 3v3 match and yield the usable ones as samples."""
    params = {"size": "3v3", "state": "finished", "to": to}
    for match in client.paginate("/matches", params, page_size=100, limit=limit):
        sample = match_to_sample(match, index)
        if sample is not None:
            yield sample
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_dataset.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/dataset.py tests/test_dataset.py
git commit -m "feat: convert finished 3v3 matches into model samples

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Model bundle — load and save

**Files:**
- Create: `gibhub/bundle.py`
- Test: `tests/test_bundle.py`

The bundle is the one committed artifact that makes reports reproducible: fitted
coefficients, the tier index, per-player UTRO, and the provenance stamp.

- [ ] **Step 1: Write the failing tests**

`tests/test_bundle.py`:

```python
import json

import pytest

from gibhub.bundle import Bundle, BundleMissing, load, save
from gibhub.tiers import Holding


def _bundle():
    return Bundle(
        fitted_at="2026-09-18T12:00:00+00:00",
        data_cutoff="2026-09-18",
        sample_size=4200,
        coefficients=[0.9, 0.6, 0.3, 0.0, -0.4, -0.8],
        fit_metrics={"log_loss": 0.62, "brier": 0.21, "accuracy": 0.66, "samples": 4200},
        bands={"S": 1.3, "A": 1.15, "B": 1.0, "C": 0.9, "D": 0.8, "E": 0.7},
        utro={"p1": 1.24},
        holdings={"p1": (Holding("poland", "A", "2026-09-18T08:37:09+02:00"),)},
        channel_names={"poland": "Poland ET:Legacy: #3v3"},
    )


def test_a_bundle_round_trips_through_disk(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), path)
    assert load(path) == _bundle()


def test_the_saved_file_is_readable_json(tmp_path):
    path = tmp_path / "coefficients.json"
    save(_bundle(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["coefficients"] == {"S": 0.9, "A": 0.6, "B": 0.3, "C": 0.0, "D": -0.4, "E": -0.8}
    assert payload["holdings"]["p1"][0]["tier"] == "A"
    assert payload["sample_size"] == 4200


def test_loading_a_missing_bundle_tells_the_user_to_fit(tmp_path):
    with pytest.raises(BundleMissing, match="committee fit --refit"):
        load(tmp_path / "nope.json")


def test_a_bundle_exposes_a_tier_index():
    index = _bundle().index()
    assert index.resolve("p1", "poland").tier == "A"
    assert index.resolve("p1", "poland").source == "exact"


def test_coefficients_are_saved_by_tier_name_not_position(tmp_path):
    """Positional coefficients would silently corrupt if TIERS ever changed order."""
    path = tmp_path / "coefficients.json"
    save(_bundle(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload["coefficients"], dict)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_bundle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.bundle'`

- [ ] **Step 3: Implement**

`gibhub/bundle.py`:

```python
"""Persistence for the fitted model bundle."""

import dataclasses
import json
import os
from typing import Dict, List, Tuple

from .model import TIERS
from .tiers import Holding, TierIndex

DEFAULT_PATH = "coefficients.json"


class BundleMissing(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Bundle:
    fitted_at: str
    data_cutoff: str
    sample_size: int
    coefficients: List[float]
    fit_metrics: Dict[str, float]
    bands: Dict[str, float]
    utro: Dict[str, float]
    holdings: Dict[str, Tuple[Holding, ...]]
    channel_names: Dict[str, str]

    def index(self) -> TierIndex:
        return TierIndex(holdings=self.holdings, bands=self.bands, utro=self.utro)


def save(bundle: Bundle, path=DEFAULT_PATH) -> None:
    payload = {
        "fitted_at": bundle.fitted_at,
        "data_cutoff": bundle.data_cutoff,
        "sample_size": bundle.sample_size,
        # Keyed by tier name so a change to TIERS ordering cannot silently
        # reinterpret an existing bundle.
        "coefficients": dict(zip(TIERS, bundle.coefficients)),
        "fit_metrics": bundle.fit_metrics,
        "bands": bundle.bands,
        "utro": bundle.utro,
        "holdings": {
            player_id: [dataclasses.asdict(holding) for holding in holdings]
            for player_id, holdings in sorted(bundle.holdings.items())
        },
        "channel_names": bundle.channel_names,
    }
    temporary = str(path) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
    os.replace(temporary, str(path))


def load(path=DEFAULT_PATH) -> Bundle:
    if not os.path.exists(str(path)):
        raise BundleMissing(
            "no model bundle at %s — run: python3 -m gibhub.cli fit --refit" % path
        )
    with open(str(path), "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    return Bundle(
        fitted_at=payload["fitted_at"],
        data_cutoff=payload["data_cutoff"],
        sample_size=payload["sample_size"],
        coefficients=[payload["coefficients"][tier] for tier in TIERS],
        fit_metrics=payload["fit_metrics"],
        bands=payload["bands"],
        utro=payload["utro"],
        holdings={
            player_id: tuple(Holding(**holding) for holding in holdings)
            for player_id, holdings in payload["holdings"].items()
        },
        channel_names=payload.get("channel_names", {}),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_bundle.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/bundle.py tests/test_bundle.py
git commit -m "feat: persist the fitted model bundle

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Build the bundle from the API

**Files:**
- Create: `gibhub/build.py`
- Test: `tests/test_build.py`

Three fetches feed a bundle: the tier rosters (which players hold each tier), one
profile per tiered player (for their per-channel `tiers[]`), and the UTRO
leaderboard (for imputation).

- [ ] **Step 1: Write the failing tests**

`tests/test_build.py`:

```python
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


def test_fetch_tier_holdings_reads_each_players_channel_tiers():
    client = FakeClient(
        pages={("/players", tier): ([{"player_id": "p1"}] if tier == "A" else [])
               for tier in ("S", "A", "B", "C", "D", "E")},
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
        pages={("/players", tier): ([{"player_id": "p1"}] if tier == "S" else [])
               for tier in ("S", "A", "B", "C", "D", "E")},
        singles={"/players/p1": {"tiers": [
            {"channel_id": "c", "channel_name": "C", "tier": "S", "size": 6,
             "updated_at": "2026-01-01"}]}},
    )
    holdings, _ = fetch_tier_holdings(client)
    assert set(holdings) == {"p1"}


def test_fetch_tier_holdings_skips_a_player_whose_profile_has_no_3v3_tier():
    client = FakeClient(
        pages={("/players", tier): ([{"player_id": "p1"}] if tier == "A" else [])
               for tier in ("S", "A", "B", "C", "D", "E")},
        singles={"/players/p1": {"tiers": None}},
    )
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.build'`

- [ ] **Step 3: Implement**

`gibhub/build.py`:

```python
"""Fetching the raw material a model bundle is built from."""

import datetime
from typing import Dict, Tuple

from .dataset import iter_samples
from .model import TIERS, fit, metrics
from .bundle import Bundle
from .tiers import Holding, TierIndex, build_bands

SIZE_3V3 = "3v3"
ROUNDS_3V3 = 6  # the API reports 3v3 as size 6 (players per match)
MIN_ROUNDS = 10


def fetch_utro(client, min_rounds: int = MIN_ROUNDS) -> Dict[str, float]:
    """Sample-regularised 3v3 UTRO for every player, in one sweep.

    `utro_shrunken` rather than `utro`: the raw board is topped by players with a
    single round, which would wreck imputation.
    """
    values = {}
    params = {"metric": "utro_shrunken", "size": SIZE_3V3, "minGames": 1}
    for row in client.paginate("/leaderboards", params, page_size=200):
        if (row.get("rounds") or 0) < min_rounds:
            continue
        values[row["player_id"]] = row["value"]
    return values


def fetch_tier_holdings(client) -> Tuple[Dict[str, Tuple[Holding, ...]], Dict[str, str]]:
    """Per-channel 3v3 tiers for every tiered player, plus channel display names.

    The tier listing endpoint returns neither the channel nor the tier on each row,
    so each tiered player's profile has to be read for its `tiers[]` block.
    """
    player_ids = []
    for tier in TIERS:
        params = {"size": SIZE_3V3, "tier": tier}
        for row in client.paginate("/players", params, page_size=200):
            if row["player_id"] not in player_ids:
                player_ids.append(row["player_id"])

    holdings = {}
    channel_names = {}
    for player_id in player_ids:
        profile = client.get("/players/" + player_id, {"size": SIZE_3V3})
        entries = []
        for entry in profile.get("tiers") or []:
            if entry.get("size") != ROUNDS_3V3:
                continue  # a 6v6 tier says nothing about 3v3
            entries.append(
                Holding(
                    channel_id=entry["channel_id"],
                    tier=entry["tier"],
                    updated_at=entry["updated_at"],
                )
            )
            if entry.get("channel_name"):
                channel_names[entry["channel_id"]] = entry["channel_name"]
        if entries:
            holdings[player_id] = tuple(entries)

    return holdings, channel_names


def build_bundle(client, to=None, limit=None) -> Bundle:
    """Fetch everything, fit, and return a bundle ready to save."""
    utro = fetch_utro(client)
    holdings, channel_names = fetch_tier_holdings(client)

    holders = {tier: [] for tier in TIERS}
    for player_id, entries in holdings.items():
        for entry in entries:
            holders[entry.tier].append(player_id)
    bands = build_bands(holders, utro)

    index = TierIndex(holdings=holdings, bands=bands, utro=utro)
    samples = list(iter_samples(client, index, to=to, limit=limit))
    if not samples:
        raise ValueError("no usable 3v3 matches found; cannot fit")

    training = [(sample.features, sample.outcome) for sample in samples]
    coefficients = fit(training)

    return Bundle(
        fitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        data_cutoff=to or datetime.date.today().isoformat(),
        sample_size=len(samples),
        coefficients=coefficients,
        fit_metrics=metrics(coefficients, training),
        bands=bands,
        utro=utro,
        holdings=holdings,
        channel_names=channel_names,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_build.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/build.py tests/test_build.py
git commit -m "feat: build a model bundle from tier rosters and the UTRO board

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Report — weighted UTRO and match rows

**Files:**
- Create: `gibhub/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:

```python
import json

import pytest

from gibhub.report import side_of, weighted_utro

MATCH = {
    "match_id": "m1",
    "channel_id": "poland",
    "winner": "alpha",
    "teams": {
        "alpha": [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}],
        "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
    },
    "rounds": [
        {"alpha": [{"player_id": "a1", "utro": 1.0, "playtime_percent": 100}], "beta": []},
        {"alpha": [], "beta": [{"player_id": "a1", "utro": 0.5, "playtime_percent": 50}]},
    ],
}


def test_side_of_finds_the_player():
    assert side_of(MATCH, "a2") == "alpha"
    assert side_of(MATCH, "b3") == "beta"


def test_side_of_returns_none_for_a_stranger():
    assert side_of(MATCH, "zzz") is None


def test_weighted_utro_weights_by_playtime():
    # (1.0 * 100 + 0.5 * 50) / 150
    assert weighted_utro(MATCH, "a1") == pytest.approx(0.8333333333333334)


def test_weighted_utro_is_none_when_the_player_has_no_rounds():
    assert weighted_utro(MATCH, "b1") is None


def test_weighted_utro_ignores_rounds_with_no_utro():
    match = {"rounds": [
        {"alpha": [{"player_id": "a1", "utro": None, "playtime_percent": 100}], "beta": []},
        {"alpha": [{"player_id": "a1", "utro": 1.2, "playtime_percent": 80}], "beta": []},
    ]}
    assert weighted_utro(match, "a1") == pytest.approx(1.2)


def test_weighted_utro_ignores_zero_playtime():
    match = {"rounds": [
        {"alpha": [{"player_id": "a1", "utro": 9.9, "playtime_percent": 0}], "beta": []},
        {"alpha": [{"player_id": "a1", "utro": 1.0, "playtime_percent": 100}], "beta": []},
    ]}
    assert weighted_utro(match, "a1") == pytest.approx(1.0)


def test_weighted_utro_on_the_recorded_fixture():
    match = json.load(open("tests/fixtures/match_detail.json"))
    player_id = match["rounds"][0]["alpha"][0]["player_id"]
    value = weighted_utro(match, player_id)
    assert value is not None and 0.0 < value < 3.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.report'`

- [ ] **Step 3: Implement**

`gibhub/report.py`:

```python
"""Pure assembly of a player's evidence report. No I/O."""

from typing import Any, Dict, Optional

from .dataset import roster_ids


def side_of(match: Dict[str, Any], player_id: str) -> Optional[str]:
    alpha, beta = roster_ids(match)
    if player_id in alpha:
        return "alpha"
    if player_id in beta:
        return "beta"
    return None


def weighted_utro(match: Dict[str, Any], player_id: str) -> Optional[float]:
    """The player's UTRO across the match, weighted by time on the server.

    None when the player appears in no round with both a UTRO and playtime — a
    substitute, or a match predating the stats version that reports UTRO.
    """
    total_weight = 0.0
    total = 0.0

    for round_ in match.get("rounds") or []:
        for side in ("alpha", "beta"):
            for entry in round_.get(side) or []:
                if entry.get("player_id") != player_id:
                    continue
                utro = entry.get("utro")
                weight = entry.get("playtime_percent") or 0
                if utro is None or weight <= 0:
                    continue
                total += utro * weight
                total_weight += weight

    if total_weight == 0.0:
        return None
    return total / total_weight
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/report.py tests/test_report.py
git commit -m "feat: compute a player's playtime-weighted UTRO per match

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Report — expected versus actual

**Files:**
- Modify: `gibhub/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report.py`:

```python
from gibhub.report import MatchRow, build_report, classify
from gibhub.tiers import Holding, TierIndex

BANDS = {"S": 1.30, "A": 1.15, "B": 1.00, "C": 0.90, "D": 0.80, "E": 0.70}
COEFFICIENTS = [0.9, 0.6, 0.3, 0.0, -0.4, -0.8]


def test_classify_labels_the_delta():
    assert classify(2.6) == "OVER"
    assert classify(1.5) == "OVER"
    assert classify(0.4) == "ON TIER"
    assert classify(-1.5) == "UNDER"
    assert classify(-3.0) == "UNDER"


def _detail(match_id, winner, rounds_utro):
    return {
        "match_id": match_id,
        "channel_id": "poland",
        "winner": winner,
        "state": "finished",
        "start_time": "2026-09-01T20:00:00+02:00",
        "maps": [{"map": "supply"}, {"map": "adlernest"}],
        "teams": {
            "alpha": [{"player_id": "me"}, {"player_id": "a2"}, {"player_id": "a3"}],
            "beta": [{"player_id": "b1"}, {"player_id": "b2"}, {"player_id": "b3"}],
        },
        "rounds": [
            {"alpha": [{"player_id": "me", "utro": rounds_utro, "playtime_percent": 100}],
             "beta": []}
        ],
    }


def _index():
    holdings = {
        "me": (Holding("poland", "S", "2026-09-01"),),
        "b1": (Holding("poland", "E", "2026-09-01"),),
    }
    return TierIndex(holdings=holdings, bands=BANDS, utro={})


PROFILE = {
    "player_id": "me",
    "nick": "^1Me",
    "discord_nick": "me",
    "tiers": [{"channel_id": "poland", "channel_name": "Poland", "tier": "S", "size": 6,
               "updated_at": "2026-09-01T00:00:00+02:00"}],
    "lifetime": {"matches": 100, "match_wins": 60, "match_losses": 38, "match_draws": 2,
                 "utro": 1.20, "kdr": 1.15},
}

SPIDER = {"metrics": [{"key": "utro", "value": 1.2, "avg": 1.0, "percentile": 87.5}]}


def test_a_favoured_win_is_not_an_upset():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.3)], _index(),
                          COEFFICIENTS, {})
    row = report.rows[0]
    assert row.result == "W"
    assert row.expected > 0.5
    assert row.upset is False


def test_a_win_against_the_odds_is_an_upset_win():
    # The player's own side is beta here, so the strong roster is against them.
    detail = _detail("m2", "beta", 1.4)
    detail["teams"]["alpha"] = [{"player_id": "a1"}, {"player_id": "a2"}, {"player_id": "a3"}]
    detail["teams"]["beta"] = [{"player_id": "me"}, {"player_id": "b2"}, {"player_id": "b3"}]
    index = TierIndex(
        holdings={"a1": (Holding("poland", "S", "2026-09-01"),),
                  "me": (Holding("poland", "E", "2026-09-01"),)},
        bands=BANDS, utro={},
    )
    report = build_report(PROFILE, SPIDER, [detail], index, COEFFICIENTS, {})
    row = report.rows[0]
    assert row.result == "W"
    assert row.expected < 0.5
    assert row.upset is True
    assert report.upset_wins == 1
    assert report.upset_losses == 0


def test_a_loss_while_favoured_is_an_upset_loss():
    report = build_report(PROFILE, SPIDER, [_detail("m3", "beta", 0.7)], _index(),
                          COEFFICIENTS, {})
    assert report.rows[0].result == "L"
    assert report.upset_losses == 1


def test_expected_wins_sum_the_per_match_probabilities():
    details = [_detail("m1", "alpha", 1.2), _detail("m2", "beta", 1.1)]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert report.actual_wins == 1
    assert report.expected_wins == pytest.approx(2 * report.rows[0].expected)
    assert report.delta == pytest.approx(report.actual_wins - report.expected_wins)


def test_draws_are_listed_but_excluded_from_the_totals():
    details = [_detail("m1", "alpha", 1.2), _detail("m2", "", 1.0)]
    report = build_report(PROFILE, SPIDER, details, _index(), COEFFICIENTS, {})
    assert [row.result for row in report.rows] == ["W", "D"]
    assert report.draws == 1
    assert report.actual_wins == 1
    assert report.expected_wins == pytest.approx(report.rows[0].expected)


def test_utro_delta_is_against_the_lifetime_baseline():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.5)], _index(),
                          COEFFICIENTS, {})
    assert report.rows[0].utro == pytest.approx(1.5)
    assert report.rows[0].utro_delta == pytest.approx(0.30)


def test_a_match_the_player_is_not_in_is_skipped():
    detail = _detail("m1", "alpha", 1.2)
    detail["teams"]["alpha"] = [{"player_id": "x"}, {"player_id": "y"}, {"player_id": "z"}]
    report = build_report(PROFILE, SPIDER, [detail], _index(), COEFFICIENTS, {})
    assert report.rows == []
    assert report.skipped == 1


def test_source_counts_are_totalled_across_matches():
    report = build_report(PROFILE, SPIDER, [_detail("m1", "alpha", 1.2)], _index(),
                          COEFFICIENTS, {})
    assert report.source_counts["exact"] == 2
    assert report.source_counts["imputed"] == 4
    assert report.source_counts["cross_channel"] == 0


def test_lifetime_and_percentiles_are_carried_through():
    report = build_report(PROFILE, SPIDER, [], _index(), COEFFICIENTS,
                          {"fitted_at": "2026-09-18T00:00:00+00:00"})
    assert report.nick == "^1Me"
    assert report.lifetime["win_rate"] == pytest.approx(60 / 98)
    assert report.percentiles == [("utro", 87.5)]
    assert report.provenance["fitted_at"] == "2026-09-18T00:00:00+00:00"
    assert report.label == "ON TIER"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_report'`

- [ ] **Step 3: Implement**

Append to `gibhub/report.py`:

```python
import dataclasses
from typing import Dict, List, Sequence

from .dataset import TEAM_SIZE
from .model import feature_vector, predict
from .tiers import CROSS_CHANNEL, EXACT, IMPUTED, TierIndex

OVER_UNDER_THRESHOLD = 1.5


@dataclasses.dataclass(frozen=True)
class MatchRow:
    match_id: str
    date: str
    maps: List[str]
    side: str
    expected: float
    result: str  # "W", "L" or "D"
    utro: Optional[float]
    utro_delta: Optional[float]
    sources: List[str]
    upset: bool


@dataclasses.dataclass(frozen=True)
class PlayerReport:
    player_id: str
    nick: str
    discord_nick: str
    tiers: List[Dict[str, Any]]
    lifetime: Dict[str, Any]
    percentiles: List[Any]
    rows: List[MatchRow]
    expected_wins: float
    actual_wins: int
    delta: float
    label: str
    upset_wins: int
    upset_losses: int
    draws: int
    skipped: int
    source_counts: Dict[str, int]
    provenance: Dict[str, Any]


def classify(delta: float) -> str:
    """OVER / UNDER / ON TIER, at the +-1.5 win threshold from the spec."""
    if delta >= OVER_UNDER_THRESHOLD:
        return "OVER"
    if delta <= -OVER_UNDER_THRESHOLD:
        return "UNDER"
    return "ON TIER"


def _lifetime_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
    lifetime = profile.get("lifetime") or {}
    wins = lifetime.get("match_wins") or 0
    losses = lifetime.get("match_losses") or 0
    draws = lifetime.get("match_draws") or 0
    decided = wins + losses
    return {
        "matches": lifetime.get("matches") or 0,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": (wins / decided) if decided else 0.0,
        "utro": lifetime.get("utro"),
        "kdr": lifetime.get("kdr"),
    }


def build_report(
    profile: Dict[str, Any],
    spider: Dict[str, Any],
    details: Sequence[Dict[str, Any]],
    index: TierIndex,
    coefficients: Sequence[float],
    provenance: Dict[str, Any],
) -> PlayerReport:
    player_id = profile["player_id"]
    baseline = (profile.get("lifetime") or {}).get("utro")

    rows: List[MatchRow] = []
    counts = {EXACT: 0, CROSS_CHANNEL: 0, IMPUTED: 0}
    expected_wins = 0.0
    actual_wins = 0
    upset_wins = 0
    upset_losses = 0
    draws = 0
    skipped = 0

    for match in details:
        side = side_of(match, player_id)
        alpha, beta = roster_ids(match)
        if side is None or len(alpha) != TEAM_SIZE or len(beta) != TEAM_SIZE:
            skipped += 1
            continue

        channel_id = match.get("channel_id")
        alpha_resolved = index.resolve_all(alpha, channel_id)
        beta_resolved = index.resolve_all(beta, channel_id)
        for resolved in alpha_resolved + beta_resolved:
            counts[resolved.source] += 1

        p_alpha = predict(
            coefficients,
            feature_vector([r.tier for r in alpha_resolved], [r.tier for r in beta_resolved]),
        )
        expected = p_alpha if side == "alpha" else 1.0 - p_alpha

        winner = match.get("winner")
        if winner not in ("alpha", "beta"):
            result = "D"
            draws += 1
        elif winner == side:
            result = "W"
        else:
            result = "L"

        upset = False
        if result == "W":
            actual_wins += 1
            expected_wins += expected
            upset = expected < 0.5
            if upset:
                upset_wins += 1
        elif result == "L":
            expected_wins += expected
            upset = expected > 0.5
            if upset:
                upset_losses += 1

        utro = weighted_utro(match, player_id)
        rows.append(
            MatchRow(
                match_id=match.get("match_id", ""),
                date=(match.get("start_time") or "")[:10],
                maps=[entry.get("map", "") for entry in (match.get("maps") or [])],
                side=side,
                expected=expected,
                result=result,
                utro=utro,
                utro_delta=(utro - baseline) if (utro is not None and baseline) else None,
                sources=[r.source for r in alpha_resolved + beta_resolved],
                upset=upset,
            )
        )

    delta = actual_wins - expected_wins
    metrics = spider.get("metrics") or []

    return PlayerReport(
        player_id=player_id,
        nick=profile.get("nick") or "",
        discord_nick=profile.get("discord_nick") or "",
        tiers=[t for t in (profile.get("tiers") or []) if t.get("size") == 6],
        lifetime=_lifetime_summary(profile),
        percentiles=[(m["key"], m["percentile"]) for m in metrics],
        rows=rows,
        expected_wins=expected_wins,
        actual_wins=actual_wins,
        delta=delta,
        label=classify(delta),
        upset_wins=upset_wins,
        upset_losses=upset_losses,
        draws=draws,
        skipped=skipped,
        source_counts=counts,
        provenance=provenance,
    )
```

Also extend the imports at the top of `gibhub/report.py`:

```python
from typing import Any, Dict, List, Optional, Sequence
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/report.py tests/test_report.py
git commit -m "feat: build expected-vs-actual player reports with upset detection

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Render — markdown

**Files:**
- Create: `gibhub/render.py`
- Test: `tests/test_render.py`

ET nicks contain Quake 3 colour codes (`^1`, `^~`). Strip them for display.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:

```python
from gibhub.render import strip_colors, to_markdown
from gibhub.report import MatchRow, PlayerReport

REPORT = PlayerReport(
    player_id="p1",
    nick="^6K^5R^3E^2D^EY",
    discord_nick="Kredenc",
    tiers=[{"channel_id": "poland", "channel_name": "Poland ET:Legacy: #3v3", "tier": "A",
            "size": 6, "updated_at": "2026-09-18T08:37:09+02:00"}],
    lifetime={"matches": 635, "wins": 314, "losses": 280, "draws": 41,
              "win_rate": 0.5286, "utro": 1.1011, "kdr": 1.1245},
    percentiles=[("utro", 87.5), ("acc", 62.0)],
    rows=[
        MatchRow("m1", "2026-09-18", ["supply", "adlernest"], "alpha", 0.62, "W",
                 1.25, 0.15, ["exact"] * 6, False),
        MatchRow("m2", "2026-09-17", ["erdenberg_t2"], "beta", 0.41, "W",
                 1.40, 0.30, ["exact"] * 5 + ["imputed"], True),
        MatchRow("m3", "2026-09-16", ["supply"], "alpha", 0.70, "L",
                 None, None, ["exact"] * 6, True),
        MatchRow("m4", "2026-09-15", ["supply"], "alpha", 0.50, "D",
                 1.0, -0.10, ["exact"] * 6, False),
    ],
    expected_wins=1.73,
    actual_wins=2,
    delta=0.27,
    label="ON TIER",
    upset_wins=1,
    upset_losses=1,
    draws=1,
    skipped=0,
    source_counts={"exact": 23, "cross_channel": 0, "imputed": 1},
    provenance={"fitted_at": "2026-09-18T10:00:00+00:00", "data_cutoff": "2026-09-18",
                "sample_size": 4200, "window": "6m"},
)


def test_strip_colors_removes_quake_codes():
    assert strip_colors("^6K^5R^3E^2D^EY") == "KREDY"
    assert strip_colors("^1L^Ae^Lg^3i^Oo^7n") == "Legion"
    assert strip_colors("plain") == "plain"
    assert strip_colors(None) == ""


def test_markdown_leads_with_the_nick_and_tier():
    text = to_markdown(REPORT)
    assert text.startswith("## KREDY (Kredenc)")
    assert "Poland ET:Legacy: #3v3: **A**" in text


def test_markdown_shows_the_headline_comparison():
    text = to_markdown(REPORT)
    assert "expected 1.73" in text
    assert "actual 2" in text
    assert "ON TIER" in text


def test_markdown_marks_upsets():
    text = to_markdown(REPORT)
    lines = [line for line in text.splitlines() if line.startswith("| 2026-09-17")]
    assert "upset" in lines[0]


def test_markdown_renders_a_missing_utro_without_crashing():
    text = to_markdown(REPORT)
    assert "| 2026-09-16" in text
    assert "n/a" in text


def test_markdown_footer_reports_provenance_and_sources():
    text = to_markdown(REPORT)
    assert "1 of 24 tier inputs imputed" in text
    assert "2026-09-18T10:00:00+00:00" in text
    assert "4200" in text


def test_markdown_notes_draws_are_excluded():
    assert "1 draw excluded" in to_markdown(REPORT)


def test_markdown_handles_an_empty_report():
    empty = PlayerReport(
        player_id="p1", nick="x", discord_nick="x", tiers=[],
        lifetime={"matches": 0, "wins": 0, "losses": 0, "draws": 0, "win_rate": 0.0,
                  "utro": None, "kdr": None},
        percentiles=[], rows=[], expected_wins=0.0, actual_wins=0, delta=0.0,
        label="ON TIER", upset_wins=0, upset_losses=0, draws=0, skipped=0,
        source_counts={"exact": 0, "cross_channel": 0, "imputed": 0},
        provenance={"fitted_at": "x", "data_cutoff": "x", "sample_size": 0, "window": "6m"},
    )
    text = to_markdown(empty)
    assert "no 3v3 matches in this window" in text


def test_markdown_flags_an_untiered_player():
    untiered = dataclasses.replace(REPORT, tiers=[])
    assert "no 3v3 tier held" in to_markdown(untiered)
```

Add `import dataclasses` at the top of the test file.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.render'`

- [ ] **Step 3: Implement**

`gibhub/render.py`:

```python
"""Pure rendering of a PlayerReport. No I/O, no fetching."""

import re
from typing import Optional

from .report import PlayerReport

# Quake 3 colour codes: a caret followed by any single character.
_COLOR = re.compile(r"\^.")


def strip_colors(nick: Optional[str]) -> str:
    if not nick:
        return ""
    return _COLOR.sub("", nick)


def _pct(value: float) -> str:
    return "%d%%" % round(value * 100)


def _utro(value: Optional[float], delta: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if delta is None:
        return "%.2f" % value
    return "%.2f (%+.2f)" % (value, delta)


def to_markdown(report: PlayerReport) -> str:
    lines = []
    name = strip_colors(report.nick) or report.discord_nick
    lines.append("## %s (%s)" % (name, report.discord_nick))
    lines.append("")

    if report.tiers:
        for tier in report.tiers:
            lines.append(
                "- %s: **%s**  _(set %s)_"
                % (tier.get("channel_name", tier.get("channel_id", "?")),
                   tier["tier"], (tier.get("updated_at") or "")[:10])
            )
    else:
        lines.append("- no 3v3 tier held")

    life = report.lifetime
    lines.append(
        "- 3v3 lifetime: %d matches, %dW-%dL (%s)  UTRO %s  KDR %s"
        % (
            life["matches"], life["wins"], life["losses"], _pct(life["win_rate"]),
            "%.2f" % life["utro"] if life["utro"] else "n/a",
            "%.2f" % life["kdr"] if life["kdr"] else "n/a",
        )
    )
    if report.percentiles:
        lines.append(
            "- percentiles: "
            + ", ".join("%s p%d" % (key, round(value)) for key, value in report.percentiles)
        )
    lines.append("")

    if not report.rows:
        lines.append("_no 3v3 matches in this window_")
        lines.append("")
    else:
        lines.append(
            "**Expected %.2f wins, actual %d — %+.2f → %s**"
            % (report.expected_wins, report.actual_wins, report.delta, report.label)
        )
        lines.append("")
        lines.append("| date | maps | exp | res | utro (vs base) | |")
        lines.append("| --- | --- | ---: | :---: | ---: | --- |")
        for row in report.rows:
            lines.append(
                "| %s | %s | %s | %s | %s | %s |"
                % (
                    row.date,
                    "/".join(row.maps) or "-",
                    _pct(row.expected),
                    row.result,
                    _utro(row.utro, row.utro_delta),
                    "upset" if row.upset else "",
                )
            )
        lines.append("")
        lines.append(
            "Upsets: %d win%s against the odds, %d loss%s while favoured."
            % (
                report.upset_wins, "" if report.upset_wins == 1 else "s",
                report.upset_losses, "" if report.upset_losses == 1 else "es",
            )
        )

    if report.draws:
        lines.append(
            "%d draw%s excluded from the totals."
            % (report.draws, "" if report.draws == 1 else "s")
        )
    if report.skipped:
        lines.append("%d match(es) skipped: incomplete roster or player absent." % report.skipped)

    counts = report.source_counts
    total = counts["exact"] + counts["cross_channel"] + counts["imputed"]
    lines.append("")
    lines.append(
        "_%d of %d tier inputs imputed, %d cross-channel. Model fitted %s on %s matches, "
        "cutoff %s, window %s._"
        % (
            counts["imputed"], total, counts["cross_channel"],
            report.provenance.get("fitted_at"), report.provenance.get("sample_size"),
            report.provenance.get("data_cutoff"), report.provenance.get("window"),
        )
    )
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/render.py tests/test_render.py
git commit -m "feat: render a player report as Discord-ready markdown

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Render — CSV and JSON

**Files:**
- Modify: `gibhub/render.py`
- Test: `tests/test_render.py`

Columns are fixed by the spec.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:

```python
import csv
import io
import json

from gibhub.render import CSV_COLUMNS, to_csv, to_json


def test_csv_header_matches_the_spec():
    assert CSV_COLUMNS == [
        "player_id", "nick", "discord_nick", "tier", "tier_channel", "tier_updated_at",
        "matches", "wins", "losses", "draws", "win_rate", "expected_wins", "actual_wins",
        "delta", "label", "upset_wins", "upset_losses", "utro", "utro_percentile", "kdr",
        "exact_tiers", "crosschannel_tiers", "imputed_tiers",
    ]


def test_csv_writes_one_row_per_report():
    rows = list(csv.DictReader(io.StringIO(to_csv([REPORT, REPORT]))))
    assert len(rows) == 2
    assert rows[0]["nick"] == "KREDY"
    assert rows[0]["tier"] == "A"
    assert rows[0]["tier_channel"] == "Poland ET:Legacy: #3v3"
    assert rows[0]["label"] == "ON TIER"
    assert rows[0]["imputed_tiers"] == "1"


def test_csv_reads_the_utro_percentile_from_the_spider_metrics():
    rows = list(csv.DictReader(io.StringIO(to_csv([REPORT]))))
    assert rows[0]["utro_percentile"] == "87.5"


def test_csv_leaves_tier_columns_blank_for_an_untiered_player():
    untiered = dataclasses.replace(REPORT, tiers=[])
    rows = list(csv.DictReader(io.StringIO(to_csv([untiered]))))
    assert rows[0]["tier"] == ""
    assert rows[0]["tier_channel"] == ""


def test_csv_joins_multiple_tiers():
    two = dataclasses.replace(REPORT, tiers=REPORT.tiers + [
        {"channel_id": "events", "channel_name": "Events", "tier": "S", "size": 6,
         "updated_at": "2026-09-01T00:00:00+02:00"}])
    rows = list(csv.DictReader(io.StringIO(to_csv([two]))))
    assert rows[0]["tier"] == "A|S"
    assert rows[0]["tier_channel"] == "Poland ET:Legacy: #3v3|Events"


def test_json_round_trips_and_includes_the_rows():
    payload = json.loads(to_json(REPORT))
    assert payload["player_id"] == "p1"
    assert len(payload["rows"]) == 4
    assert payload["rows"][0]["expected"] == 0.62
    assert payload["label"] == "ON TIER"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL — `ImportError: cannot import name 'CSV_COLUMNS'`

- [ ] **Step 3: Implement**

Append to `gibhub/render.py`:

```python
import csv
import dataclasses
import io
import json
from typing import Sequence

CSV_COLUMNS = [
    "player_id", "nick", "discord_nick", "tier", "tier_channel", "tier_updated_at",
    "matches", "wins", "losses", "draws", "win_rate", "expected_wins", "actual_wins",
    "delta", "label", "upset_wins", "upset_losses", "utro", "utro_percentile", "kdr",
    "exact_tiers", "crosschannel_tiers", "imputed_tiers",
]


def _percentile(report: PlayerReport, key: str):
    for name, value in report.percentiles:
        if name == key:
            return value
    return ""


def _csv_row(report: PlayerReport):
    life = report.lifetime
    return {
        "player_id": report.player_id,
        "nick": strip_colors(report.nick),
        "discord_nick": report.discord_nick,
        "tier": "|".join(tier["tier"] for tier in report.tiers),
        "tier_channel": "|".join(
            tier.get("channel_name", tier.get("channel_id", "")) for tier in report.tiers
        ),
        "tier_updated_at": "|".join(
            (tier.get("updated_at") or "")[:10] for tier in report.tiers
        ),
        "matches": life["matches"],
        "wins": life["wins"],
        "losses": life["losses"],
        "draws": life["draws"],
        "win_rate": "%.4f" % life["win_rate"],
        "expected_wins": "%.2f" % report.expected_wins,
        "actual_wins": report.actual_wins,
        "delta": "%.2f" % report.delta,
        "label": report.label,
        "upset_wins": report.upset_wins,
        "upset_losses": report.upset_losses,
        "utro": life["utro"] if life["utro"] is not None else "",
        "utro_percentile": _percentile(report, "utro"),
        "kdr": life["kdr"] if life["kdr"] is not None else "",
        "exact_tiers": report.source_counts["exact"],
        "crosschannel_tiers": report.source_counts["cross_channel"],
        "imputed_tiers": report.source_counts["imputed"],
    }


def to_csv(reports: Sequence[PlayerReport]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for report in reports:
        writer.writerow(_csv_row(report))
    return buffer.getvalue()


def to_json(report: PlayerReport) -> str:
    return json.dumps(dataclasses.asdict(report), indent=1, sort_keys=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/render.py tests/test_render.py
git commit -m "feat: render reports as CSV and JSON

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Fetching a player's report data

**Files:**
- Create: `gibhub/fetch.py`
- Test: `tests/test_fetch.py`

This is the thin layer between the API and the pure `build_report`.

- [ ] **Step 1: Write the failing tests**

`tests/test_fetch.py`:

```python
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
            {"player_id": "p1", "nick": "^1kiz", "discord_nick": "kiz"},
            {"player_id": "p2", "nick": "kiz2", "discord_nick": "kiz2"},
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.fetch'`

- [ ] **Step 3: Implement**

`gibhub/fetch.py`:

```python
"""Fetching the data a player report needs. Thin: no scoring, no formatting."""

import re
from typing import Any, Dict, List, Optional, Tuple

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
SIZE_3V3 = "3v3"


class PlayerNotFound(Exception):
    pass


class AmbiguousPlayer(Exception):
    pass


def resolve_player(client, term: str, exact: bool = False) -> str:
    """A UUID passes through; a name goes through fuzzy search.

    Several hits raise rather than guess, unless one is an exact nick match and
    `exact` allows it.
    """
    if UUID.match(term):
        return term

    results = (client.get("/players/search", {"q": term, "limit": 10}) or {}).get("data") or []
    if not results:
        raise PlayerNotFound("no player matches %r" % term)
    if len(results) == 1:
        return results[0]["player_id"]

    if exact:
        lowered = term.lower()
        for result in results:
            if (result.get("discord_nick") or "").lower() == lowered:
                return result["player_id"]

    listing = "\n".join(
        "  %s  %s (%s)" % (r["player_id"], r.get("discord_nick") or "?", r.get("nick") or "?")
        for r in results
    )
    raise AmbiguousPlayer("%r matches several players:\n%s" % (term, listing))


def fetch_player_data(
    client,
    player_id: str,
    matches: int,
    range_: Optional[str] = None,
    to: Optional[str] = None,
    channel: Optional[str] = None,
    cache=None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    scope = {"size": SIZE_3V3, "range": range_, "to": to, "channel": channel}
    profile = client.get("/players/" + player_id, scope)
    spider = client.get("/players/" + player_id + "/spider", scope)

    listing = client.paginate(
        "/players/" + player_id + "/matches", scope, page_size=50, limit=matches
    )

    def load(match_id):
        return client.get("/matches/" + match_id)

    details = []
    for item in listing:
        match_id = item["match_id"]
        details.append(cache.fetch(match_id, load) if cache else load(match_id))

    return profile, spider, details
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_fetch.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/fetch.py tests/test_fetch.py
git commit -m "feat: fetch profile, spider and match details for a player

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: CLI — the `player` command

**Files:**
- Create: `gibhub/cli.py`
- Create: `gibhub/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json

import pytest

from gibhub.cli import build_parser, main


def test_parser_defaults_match_the_spec():
    args = build_parser().parse_args(["player", "Kredenc"])
    assert args.command == "player"
    assert args.player == "Kredenc"
    assert args.matches == 20
    assert args.range == "6m"
    assert args.format == "md"


def test_parser_accepts_the_documented_flags():
    args = build_parser().parse_args(
        ["player", "p1", "--matches", "5", "--channel", "Poland", "--range", "1y",
         "--to", "2026-01-01", "--format", "json"]
    )
    assert args.matches == 5
    assert args.channel == "Poland"
    assert args.range == "1y"
    assert args.to == "2026-01-01"
    assert args.format == "json"


def test_bulk_requires_a_selector():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["bulk"])


def test_bulk_accepts_repeated_tiers():
    args = build_parser().parse_args(["bulk", "--tier", "A", "--tier", "B", "--out", "x.csv"])
    assert args.tier == ["A", "B"]
    assert args.out == "x.csv"


def test_missing_bundle_exits_non_zero_with_guidance(tmp_path, capsys):
    code = main(["player", "someone", "--bundle", str(tmp_path / "nope.json")])
    assert code != 0
    assert "committee fit --refit" in capsys.readouterr().err


def test_player_command_prints_markdown(monkeypatch, tmp_path, capsys, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    code = main(["player", "p1", "--bundle", fake_bundle_path, "--cache", str(tmp_path)])
    assert code == 0
    assert "## Me" in capsys.readouterr().out


def test_player_command_prints_json(monkeypatch, tmp_path, capsys, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    main(["player", "p1", "--bundle", fake_bundle_path, "--cache", str(tmp_path),
          "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["player_id"] == "p1"


def test_an_ambiguous_name_exits_non_zero_and_lists_candidates(
    monkeypatch, tmp_path, capsys, fake_bundle_path
):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: AMBIGUOUS_CLIENT)
    code = main(["player", "kiz", "--bundle", fake_bundle_path, "--cache", str(tmp_path)])
    assert code != 0
    assert "matches several players" in capsys.readouterr().err
```

Add this fixture and the fake clients at the top of `tests/test_cli.py`:

```python
import pytest

from gibhub.bundle import Bundle, save
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gibhub.cli'`

- [ ] **Step 3: Implement**

`gibhub/cli.py`:

```python
"""Command line entry point."""

import argparse
import os
import sys

from .api import ApiError, Client
from .bundle import DEFAULT_PATH, BundleMissing, load
from .cache import MatchCache
from .fetch import AmbiguousPlayer, PlayerNotFound, fetch_player_data, resolve_player
from .render import to_csv, to_json, to_markdown
from .report import build_report


def make_client(args) -> Client:
    return Client(token=os.environ.get("GIBHUB_TOKEN"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="committee", description="Tiering evidence for 3v3 gathers."
    )
    parser.add_argument("--bundle", default=DEFAULT_PATH, help="path to coefficients.json")
    parser.add_argument("--cache", default=".cache", help="match cache directory")
    sub = parser.add_subparsers(dest="command", required=True)

    player = sub.add_parser("player", help="report on one player")
    player.add_argument("player", help="name, discord nick, or player UUID")
    player.add_argument("--matches", type=int, default=20)
    player.add_argument("--channel")
    player.add_argument("--range", default="6m")
    player.add_argument("--to")
    player.add_argument("--format", choices=["md", "json", "csv"], default="md")

    bulk = sub.add_parser("bulk", help="report on many players as CSV")
    selector = bulk.add_mutually_exclusive_group(required=True)
    selector.add_argument("--tier", action="append")
    selector.add_argument("--players", help="file with one name or UUID per line")
    bulk.add_argument("--matches", type=int, default=20)
    bulk.add_argument("--range", default="6m")
    bulk.add_argument("--out")

    fit = sub.add_parser("fit", help="show or refit the model")
    fit.add_argument("--refit", action="store_true")
    fit.add_argument("--to")
    fit.add_argument("--limit", type=int)

    return parser


def _report_for(client, bundle, player_id, args, cache):
    profile, spider, details = fetch_player_data(
        client,
        player_id,
        matches=args.matches,
        range_=args.range,
        to=getattr(args, "to", None),
        channel=getattr(args, "channel", None),
        cache=cache,
    )
    provenance = {
        "fitted_at": bundle.fitted_at,
        "data_cutoff": bundle.data_cutoff,
        "sample_size": bundle.sample_size,
        "window": args.range,
    }
    return build_report(
        profile, spider, details, bundle.index(), bundle.coefficients, provenance
    )


def cmd_player(args) -> int:
    bundle = load(args.bundle)
    client = make_client(args)
    cache = MatchCache(args.cache)

    player_id = resolve_player(client, args.player, exact=True)
    report = _report_for(client, bundle, player_id, args, cache)

    if args.format == "json":
        print(to_json(report))
    elif args.format == "csv":
        print(to_csv([report]), end="")
    else:
        print(to_markdown(report), end="")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "player":
            return cmd_player(args)
        return cmd_bulk(args) if args.command == "bulk" else cmd_fit(args)
    except (BundleMissing, PlayerNotFound, AmbiguousPlayer, ApiError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

`gibhub/__main__.py`:

```python
import sys

from .cli import main

sys.exit(main())
```

Note: `cmd_bulk` and `cmd_fit` are added in Task 19. Until then, `main` will raise
`NameError` for those commands, which the Task 19 tests cover.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/cli.py gibhub/__main__.py tests/test_cli.py
git commit -m "feat: add the player command

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 19: CLI — the `bulk` and `fit` commands

**Files:**
- Modify: `gibhub/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
import csv
import io


def test_bulk_writes_csv_to_stdout(monkeypatch, tmp_path, capsys, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    monkeypatch.setattr("gibhub.cli.select_players", lambda client, args: ["p1", "p1"])
    code = main(["bulk", "--tier", "A", "--bundle", fake_bundle_path, "--cache", str(tmp_path)])
    assert code == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 2
    assert rows[0]["player_id"] == "p1"


def test_bulk_writes_csv_to_a_file(monkeypatch, tmp_path, fake_bundle_path):
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    monkeypatch.setattr("gibhub.cli.select_players", lambda client, args: ["p1"])
    out = tmp_path / "out.csv"
    code = main(["bulk", "--tier", "A", "--out", str(out), "--bundle", fake_bundle_path,
                 "--cache", str(tmp_path)])
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
    code = main(["fit", "--bundle", fake_bundle_path])
    assert code == 0
    output = capsys.readouterr().out
    assert "2026-09-18T00:00:00+00:00" in output
    assert "accuracy" in output
    assert "S" in output  # the per-tier coefficient table


def test_fit_with_refit_writes_a_bundle(monkeypatch, tmp_path, capsys):
    from gibhub.bundle import Bundle, load
    from gibhub.tiers import Holding

    fake = Bundle(
        fitted_at="2026-09-19T00:00:00+00:00", data_cutoff="2026-09-19", sample_size=7,
        coefficients=[1.0, 0.5, 0.2, 0.0, -0.3, -0.7],
        fit_metrics={"log_loss": 0.5, "brier": 0.2, "accuracy": 0.8, "samples": 7},
        bands={"S": 1.3}, utro={}, holdings={"p1": (Holding("c", "S", "2026-01-01"),)},
        channel_names={},
    )
    monkeypatch.setattr("gibhub.cli.make_client", lambda args: FAKE_CLIENT)
    monkeypatch.setattr("gibhub.cli.build_bundle", lambda client, to=None, limit=None: fake)

    path = tmp_path / "coefficients.json"
    code = main(["fit", "--refit", "--bundle", str(path)])
    assert code == 0
    assert load(path).sample_size == 7
    assert "7" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_players'`

- [ ] **Step 3: Implement**

Add to `gibhub/cli.py`, and extend the imports with
`from .build import build_bundle`, `from .bundle import save`, and
`from .model import TIERS`:

```python
def select_players(client, args):
    """The players a bulk run covers: a tier roster, or a file of names."""
    if args.players:
        player_ids = []
        with open(args.players, "r", encoding="utf-8") as handle:
            for line in handle:
                term = line.strip()
                if not term or term.startswith("#"):
                    continue
                player_ids.append(resolve_player(client, term, exact=True))
        return player_ids

    player_ids = []
    for tier in args.tier:
        for row in client.paginate(
            "/players", {"size": "3v3", "tier": tier}, page_size=200
        ):
            if row["player_id"] not in player_ids:
                player_ids.append(row["player_id"])
    return player_ids


def cmd_bulk(args) -> int:
    bundle = load(args.bundle)
    client = make_client(args)
    cache = MatchCache(args.cache)

    args.channel = None
    args.to = None

    reports = [
        _report_for(client, bundle, player_id, args, cache)
        for player_id in select_players(client, args)
    ]

    text = to_csv(reports)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("wrote %d rows to %s" % (len(reports), args.out))
    else:
        print(text, end="")
    return 0


def cmd_fit(args) -> int:
    if args.refit:
        bundle = build_bundle(make_client(args), to=args.to, limit=args.limit)
        save(bundle, args.bundle)
        print("wrote %s" % args.bundle)
    else:
        bundle = load(args.bundle)

    print("fitted_at:   %s" % bundle.fitted_at)
    print("data_cutoff: %s" % bundle.data_cutoff)
    print("samples:     %d" % bundle.sample_size)
    print("metrics:     " + "  ".join(
        "%s=%.4f" % (key, value)
        for key, value in sorted(bundle.fit_metrics.items())
        if key != "samples"
    ))
    print("")
    print("tier value (log-odds, higher is stronger):")
    for tier, coefficient in zip(TIERS, bundle.coefficients):
        band = bundle.bands.get(tier)
        print("  %s  %+.4f   band utro %s" % (
            tier, coefficient, "%.3f" % band if band else "n/a"))
    return 0
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add gibhub/cli.py tests/test_cli.py
git commit -m "feat: add the bulk and fit commands

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 20: Integration test against the live API

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write the test**

`tests/test_integration.py`:

```python
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


def test_the_utro_leaderboard_still_serves_every_3v3_player(client):
    payload = client.get(
        "/leaderboards",
        {"metric": "utro_shrunken", "size": "3v3", "minGames": 1, "pageSize": 5},
    )
    assert payload["total"] > 100
    assert payload["items"][0]["player_id"]
    assert "rounds" in payload["items"][0]


def test_tier_rosters_are_still_served_per_size(client):
    payload = client.get("/players", {"size": "3v3", "tier": "A", "pageSize": 5})
    assert payload["total"] > 0


def test_a_tiered_profile_still_carries_per_channel_tiers(client):
    roster = client.get("/players", {"size": "3v3", "tier": "A", "pageSize": 1})
    profile = client.get("/players/" + roster["items"][0]["player_id"], {"size": "3v3"})
    tiers = profile.get("tiers") or []
    assert any(entry.get("size") == 6 for entry in tiers)
    assert "lifetime" in profile
```

- [ ] **Step 2: Verify it is skipped by default**

Run: `python3 -m pytest tests/test_integration.py -v`
Expected: 5 skipped.

- [ ] **Step 3: Verify it passes against the live API**

Run: `GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add opt-in live API contract checks

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 21: Fit the real model and commit the bundle

**Files:**
- Create: `coefficients.json`

This task runs the real pipeline. It is the first end-to-end proof the tool works.

- [ ] **Step 1: Run the full unit suite**

Run: `python3 -m pytest -v`
Expected: PASS, 0 failures, integration tests skipped.

- [ ] **Step 2: Fit against the live API**

Run: `python3 -m gibhub.cli fit --refit`

Expected: `wrote coefficients.json`, then a metadata block and a tier table. This
walks every finished 3v3 match and fetches ~134 profiles, so allow several minutes.

- [ ] **Step 3: Sanity-check the fit**

The tier coefficients must be **monotonically decreasing** from S to E. If they are
not, the model has learned something implausible and the cause must be found before
the committee sees any number from it.

Run:

```bash
python3 - <<'PY'
import json
bundle = json.load(open("coefficients.json"))
tiers = ["S", "A", "B", "C", "D", "E"]
values = [bundle["coefficients"][t] for t in tiers]
print("samples:", bundle["sample_size"])
print("metrics:", bundle["fit_metrics"])
for tier, value in zip(tiers, values):
    print("  %s %+.4f" % (tier, value))
assert bundle["sample_size"] > 500, "suspiciously few training matches"
assert bundle["fit_metrics"]["accuracy"] > 0.5, "worse than a coin flip"
assert values == sorted(values, reverse=True), "tier values are not monotonic"
print("fit OK")
PY
```

Expected: `fit OK`

If the monotonicity assertion fails, stop and report it rather than committing the
bundle. The most likely causes are imputation collapsing most players into one tier,
or a tier with too few holders to estimate.

- [ ] **Step 4: Generate a real report end to end**

Run: `python3 -m gibhub.cli player Kredenc`

Expected: a markdown block naming KREDY, their Poland tier, a match table with
percentages and results, and a provenance footer.

- [ ] **Step 5: Commit the bundle**

```bash
git add coefficients.json
git commit -m "feat: fit and commit the initial model bundle

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 22: Document the tool

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the README**

Replace `README.md` with:

```markdown
# committee

Evidence generator for the ET:Legacy 3v3 tiering committee. For each player it
shows the win probability their team's tier composition implied for every recent
match, what actually happened, and how the player themself performed — so the
committee can see whether a record matches the tier held.

Python 3.9+, no runtime dependencies.

## Use

Report on one player (Discord-ready markdown):

    python3 -m gibhub.cli player Kredenc
    python3 -m gibhub.cli player Kredenc --matches 40 --range 1y
    python3 -m gibhub.cli player b04c4850-29c9-52a9-babe-f1feadbeb206 --format json

Review a whole tier as a spreadsheet:

    python3 -m gibhub.cli bulk --tier A --tier B --out tier-ab.csv
    python3 -m gibhub.cli bulk --players shortlist.txt --out shortlist.csv

Inspect or refit the model:

    python3 -m gibhub.cli fit            # show the committed model
    python3 -m gibhub.cli fit --refit    # refit from the live API (slow)

## Reading the output

`exp` is the probability the player's side wins, given the six players' tiers.
`res` is what happened. A win at `exp` below 50% or a loss above it is marked
`upset`. The headline line sums the per-match probabilities into expected wins and
compares that to actual wins:

- **OVER** — won at least 1.5 more than their tier predicted
- **UNDER** — won at least 1.5 fewer
- **ON TIER** — within that band

`utro` is the player's own performance rating for the match, playtime-weighted,
with the change from their lifetime 3v3 baseline in brackets.

## How the model works

A logistic regression over per-tier headcount differences, fitted on every finished
3v3 match. It has no intercept, so two identically-tiered rosters always score
exactly 50%. `fit` prints each tier's fitted value in log-odds, which doubles as a
check on whether adjacent tiers are actually distinguishable.

Players without a tier in the match's channel fall back to their tier elsewhere;
players with no tier at all get one imputed from their 3v3 UTRO. Every report
footer counts how many of its inputs were imputed.

## Reproducibility

`coefficients.json` is the committed model: coefficients, the tier index, per-player
UTRO, and a provenance stamp. Finished matches are immutable and cached in
`.cache/`, so the same command with the same cache produces identical output. Only
`fit --refit` changes the model.

## Known limitations

Tiers have no history, so past matches are scored against today's tiers. A recently
promoted player looks like they were overperforming for their whole history — hence
the 6-month default window. Tiers are per-channel, so a player active in several
channels may be scored against another channel's assignment.

## Development

    python3 -m pytest                                    # unit tests, no network
    GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py
    python3 tools/record_fixtures.py                     # refresh test fixtures

`GIBHUB_TOKEN` is only needed for the `_internal` endpoints, which this tool does
not call. Public endpoints need no authentication.
```

- [ ] **Step 2: Verify every documented command runs**

Run:

```bash
python3 -m gibhub.cli fit
python3 -m gibhub.cli player Kredenc --matches 3
python3 -m gibhub.cli bulk --tier S --out /tmp/tier-s.csv && head -2 /tmp/tier-s.csv
```

Expected: each command exits 0 and prints the documented output.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document usage, the model, and its limitations

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Verification checklist

Run before declaring the work complete.

- [ ] `python3 -m pytest` passes with zero failures
- [ ] `GIBHUB_INTEGRATION=1 python3 -m pytest tests/test_integration.py` passes
- [ ] `python3 -m gibhub.cli fit` prints monotonically decreasing tier values S→E
- [ ] `python3 -m gibhub.cli player <someone>` produces a report with a footer
- [ ] Running the same `player` command twice produces byte-identical output:
      `diff <(python3 -m gibhub.cli player Kredenc) <(python3 -m gibhub.cli player Kredenc)`
- [ ] `git status` is clean and `.cache/` is untracked
- [ ] No API token appears anywhere in the repository:
      `git grep -i <REDACTED-TOKEN-PREFIX> || echo clean`
