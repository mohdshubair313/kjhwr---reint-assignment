"""Audit saved Elexon responses without network access or third-party packages."""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "artifacts" / "phase-1"


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    records = {}
    report = {"files": {}, "cutoff_assumption": "09:00 Europe/London (GMT in January)"}
    for name in ("windfor", "fuelhh"):
        raw = (DATA / f"{name}.json").read_bytes()
        rows = json.loads(raw)
        records[name] = rows
        keys = defaultdict(list)
        for row in rows:
            keys[(row["startTime"], row["publishTime"], row.get("fuelType"))].append(row["generation"])
        report["files"][name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": len(rows),
            "publication_range": [min(r["publishTime"] for r in rows), max(r["publishTime"] for r in rows)],
            "delivery_range": [min(r["startTime"] for r in rows), max(r["startTime"] for r in rows)],
            "duplicate_keys": sum(len(values) > 1 for values in keys.values()),
            "conflicting_keys": sum(len(set(values)) > 1 for values in keys.values()),
            "invalid_generation": sum(not isinstance(r["generation"], (int, float)) or r["generation"] < 0 for r in rows),
        }

    vintages = defaultdict(list)
    forecasts = defaultdict(list)
    for row in records["windfor"]:
        vintages[row["publishTime"]].append(timestamp(row["startTime"]))
        forecasts[timestamp(row["startTime"])].append(row)
    steps = Counter()
    for times in vintages.values():
        ordered = sorted(set(times))
        steps.update((b - a).total_seconds() / 60 for a, b in zip(ordered, ordered[1:]))
    report["forecast_step_minutes"] = dict(steps)
    report["forecast_publication_times_utc"] = sorted({timestamp(p).strftime("%H:%M") for p in vintages})
    actuals = defaultdict(list)
    for row in records["fuelhh"]:
        if row["fuelType"] == "WIND":
            actuals[timestamp(row["startTime"])].append(row)
    report["actual_delivery_duplicate_keys"] = sum(len(rows) > 1 for rows in actuals.values())
    report["days"] = []
    for day in range(1, 32):
        decision = datetime(2026, 1, day, tzinfo=UTC)
        cutoff = decision + timedelta(hours=9)
        delivery = decision + timedelta(days=1)
        forecast_count = actual_count = 0
        selected_publications = set()
        for hour in range(24):
            target = delivery + timedelta(hours=hour)
            eligible = [r for r in forecasts[target] if timestamp(r["publishTime"]) <= cutoff]
            if eligible:
                selected = max(eligible, key=lambda r: timestamp(r["publishTime"]))
                forecast_count += 1
                selected_publications.add(selected["publishTime"])
            if len(actuals[target]) == 1 and len(actuals[target + timedelta(minutes=30)]) == 1:
                actual_count += 1
        report["days"].append({
            "decision_date": decision.date().isoformat(),
            "delivery_date": delivery.date().isoformat(),
            "forecast_hours": forecast_count,
            "complete_actual_hours": actual_count,
            "selected_publications": sorted(selected_publications),
        })
    report["expected_hours"] = 31 * 24
    report["eligible_forecast_hours"] = sum(d["forecast_hours"] for d in report["days"])
    report["complete_actual_hours"] = sum(d["complete_actual_hours"] for d in report["days"])
    (DATA / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "days"}, indent=2))


if __name__ == "__main__":
    main()
