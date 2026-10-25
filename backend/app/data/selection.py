"""Pure historical selection over a read-only snapshot. No network or metrics."""

from contextlib import closing, nullcontext
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .models import DECISION_END, DECISION_START, DEFAULT_CUTOFF, LONDON, delivery_bounds, iso
from .snapshot import connect_readonly


def select_day(snapshot: Path, decision_day: date, cutoff: time = DEFAULT_CUTOFF, *, connection=None) -> dict:
    if not DECISION_START <= decision_day <= DECISION_END:
        raise ValueError("Decision date must be in January 2026")
    if cutoff.tzinfo is not None or cutoff.second or cutoff.microsecond:
        raise ValueError("Cutoff must be a local London time at minute resolution")
    cutoff_epoch = int(datetime.combine(decision_day, cutoff, LONDON).timestamp())
    delivery_day = decision_day + timedelta(days=1)
    start, end = delivery_bounds(delivery_day)
    scope = closing(connect_readonly(snapshot)) if connection is None else nullcontext(connection)
    with scope as connection:
        manifest = json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        forecasts = connection.execute("""
            SELECT start, published, generation FROM records
            WHERE dataset='WINDFOR' AND start >= ? AND start < ? AND published <= ?
            ORDER BY start, published
        """, (start, end, cutoff_epoch)).fetchall()
        actuals = connection.execute("""
            SELECT start, published, generation FROM records
            WHERE dataset='FUELHH' AND start >= ? AND start < ? ORDER BY start, published
        """, (start, end)).fetchall()
    # Ordered overwrite is an explicit latest-publication rule. Composite-key
    # conflicts were already rejected during normalization.
    forecast_by_time = {row["start"]: row for row in forecasts}
    actual_by_time = {row["start"]: row for row in actuals}
    latest_eligible = max((r["published"] for r in forecasts), default=None)
    rows = []
    for target in range(start, end, 3600):
        forecast = forecast_by_time.get(target)
        halves = [actual_by_time.get(target), actual_by_time.get(target + 1800)]
        complete_actual = all(half is not None for half in halves)
        published = forecast["published"] if forecast is not None else None
        flags = []
        if forecast is None:
            flags.append("missing_forecast")
        if not complete_actual:
            flags.append("missing_actual_half_hour")
        if published is not None and published < latest_eligible:
            flags.append("older_publication_fallback")
        rows.append({
            "start_time": iso(target), "end_time": iso(target + 3600),
            "forecast_mw": forecast["generation"] if forecast is not None else None,
            "forecast_publish_time": iso(published) if published is not None else None,
            "forecast_age_hours": (cutoff_epoch - published) / 3600 if published is not None else None,
            "lead_time_hours": (target - published) / 3600 if published is not None else None,
            "actual_mw": sum(h["generation"] for h in halves) / 2 if complete_actual else None,
            "actual_publish_times": [iso(h["published"]) if h is not None else None for h in halves],
            "paired": forecast is not None and complete_actual, "quality_flags": flags,
        })
    paired = sum(row["paired"] for row in rows)
    return {
        "snapshot_id": manifest["snapshot_id"],
        "decision_date": decision_day.isoformat(), "delivery_date": delivery_day.isoformat(),
        "cutoff": iso(cutoff_epoch), "timezone": "Europe/London",
        "cutoff_is_assumption": True, "expected_hours": len(rows), "paired_hours": paired,
        "coverage": paired / len(rows),
        "forecast_hours": sum(r["forecast_mw"] is not None for r in rows),
        "actual_hours": sum(r["actual_mw"] is not None for r in rows),
        "mixed_forecast_vintages": len({r["forecast_publish_time"] for r in rows if r["forecast_publish_time"]}) > 1,
        "rows": rows,
    }


def coverage_report(snapshot: Path, cutoff: time = DEFAULT_CUTOFF) -> dict:
    days = []
    day = DECISION_START
    while day <= DECISION_END:
        selected = select_day(snapshot, day, cutoff)
        days.append({k: v for k, v in selected.items() if k != "rows"})
        day += timedelta(days=1)
    expected = sum(d["expected_hours"] for d in days)
    paired = sum(d["paired_hours"] for d in days)
    return {"expected_hours": expected, "paired_hours": paired, "coverage": paired / expected, "days": days}
