"""Small synchronous Elexon client: bounded requests and retryable failures only."""

import json
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import DataError, iso

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class FetchError(RuntimeError):
    """Upstream acquisition failed without replacing the last usable snapshot."""


class ElexonClient:
    def __init__(self, *, timeout=30, attempts=4, opener=urlopen, sleep=time.sleep,
                 jitter=random.random, now=lambda: datetime.now(UTC)):
        if attempts < 1 or timeout <= 0:
            raise ValueError("attempts and timeout must be positive")
        self.timeout, self.attempts = timeout, attempts
        self.opener, self.sleep, self.jitter, self.now = opener, sleep, jitter, now

    def _delay(self, attempt, retry_after):
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(retry_after) - self.now()).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    delay = 2 ** attempt + self.jitter()
            # Stop instead of retrying earlier than the server permits.
            if delay > 30:
                raise FetchError(f"Retry-After requests {delay:g}s; retry this acquisition later")
            return max(0, delay)
        return min(30, 2 ** attempt + self.jitter())

    def fetch(self, dataset: str, start: int, end: int) -> tuple[bytes, str, str]:
        if dataset not in {"WINDFOR", "FUELHH"} or start >= end:
            raise ValueError("Expected supported dataset and increasing publication bounds")
        # One-second overlap protects against exclusive lower bounds. Ingestion
        # applies the explicit [start,end) window and deduplicates intersections.
        params = {"publishDateTimeFrom": iso(start - 1), "publishDateTimeTo": iso(end)}
        if dataset == "FUELHH":
            params["fuelType"] = "WIND"
        url = f"{BASE_URL}/datasets/{dataset}/stream?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "REint-pilot/1.0"})
        for attempt in range(self.attempts):
            retry_after = None
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise FetchError("Response too large; reduce publication window")
                try:
                    rows = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise DataError("Upstream returned invalid JSON") from exc
                if not isinstance(rows, list):
                    raise DataError("Expected top-level JSON array")
                return raw, url, self.now().isoformat().replace("+00:00", "Z")
            except HTTPError as exc:
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    exc.close()
                    raise FetchError(f"Elexon HTTP {exc.code}: {url}") from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                failure = f"HTTP {exc.code}"
                exc.close()
            except (URLError, TimeoutError, ConnectionError, IncompleteRead) as exc:
                failure = str(exc)
            if attempt + 1 == self.attempts:
                raise FetchError(f"Elexon failed after {self.attempts} attempts: {failure}")
            self.sleep(self._delay(attempt, retry_after))
        raise AssertionError("unreachable")
