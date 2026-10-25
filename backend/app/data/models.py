"""Strict normalization at the upstream boundary; timestamps stored as UTC seconds."""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
DECISION_START = date(2026, 1, 1)
DECISION_END = date(2026, 1, 31)
DEFAULT_CUTOFF = time(9)
SCHEMA_VERSION = 1
POLICY_VERSION = "january-hourly-v1"


class DataError(ValueError):
    """Invalid or ambiguous upstream data; no snapshot should be published."""


def parse_timestamp(value: str) -> int:
    if not isinstance(value, str) or "T" not in value:
        raise DataError(f"Expected ISO datetime, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataError(f"Invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
        raise DataError(f"Timestamp must be timezone-aware with whole seconds: {value!r}")
    return int(parsed.timestamp())


def iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def delivery_bounds(day: date) -> tuple[int, int]:
    """Delivery day's local midnight bounds, including 23/25-hour DST days."""
    start = datetime.combine(day, time(), LONDON)
    end = datetime.combine(day + timedelta(days=1), time(), LONDON)
    return int(start.timestamp()), int(end.timestamp())


@dataclass(frozen=True, order=True)
class Record:
    dataset: str
    start: int
    published: int
    generation: float

    @property
    def key(self) -> tuple[str, int, int]:
        return self.dataset, self.start, self.published


def normalize(row: dict, dataset: str) -> Record | None:
    if not isinstance(row, dict) or row.get("dataset") != dataset:
        raise DataError(f"Expected a {dataset} record")
    if dataset not in {"WINDFOR", "FUELHH"}:
        raise DataError(f"Unsupported dataset: {dataset}")
    if dataset == "FUELHH":
        if not isinstance(row.get("fuelType"), str):
            raise DataError("Missing fuelType")
        if row["fuelType"] != "WIND":
            return None
    try:
        start = parse_timestamp(row["startTime"])
        published = parse_timestamp(row["publishTime"])
        value = row["generation"]
    except KeyError as exc:
        raise DataError(f"Missing required field: {exc}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise DataError(f"Invalid wind generation: {value!r}")
    resolution = 3600 if dataset == "WINDFOR" else 1800
    if start % resolution:
        raise DataError(f"Off-grid {dataset} startTime: {iso(start)}")
    if dataset == "FUELHH":
        local_day = datetime.fromtimestamp(start, LONDON).date()
        midnight, _ = delivery_bounds(local_day)
        expected_period = (start - midnight) // 1800 + 1
        if row.get("settlementDate") != local_day.isoformat():
            raise DataError("settlementDate disagrees with startTime")
        period = row.get("settlementPeriod")
        if type(period) is not int or period != expected_period:
            raise DataError("settlementPeriod disagrees with startTime")
    return Record(dataset, start, published, float(value))
