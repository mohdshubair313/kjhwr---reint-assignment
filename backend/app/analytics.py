"""Retrospective error calculations on the same complete hourly pairs."""

import math
from datetime import date, time, timedelta
from pathlib import Path

from .data.models import DECISION_END, DECISION_START, parse_timestamp
from .data.selection import select_day


def with_error(row: dict) -> dict:
    forecast, actual = row["forecast_mw"], row["actual_mw"]
    error = forecast - actual if forecast is not None and actual is not None else None
    hours = (parse_timestamp(row["end_time"]) - parse_timestamp(row["start_time"])) / 3600
    if hours != 1:
        raise ValueError("This evaluation policy requires one-hour delivery intervals")
    return dict(row, error_mw=error, absolute_error_mw=abs(error) if error is not None else None,
                energy_error_mwh=error * hours if error is not None else None)


def summarize(rows: list[dict]) -> dict:
    """Linear P90 interpolation; null error metrics when no complete pairs exist."""
    paired = [row for row in rows if row["error_mw"] is not None]
    errors = [row["error_mw"] for row in paired]
    count = len(errors)
    result = {
        "expected_hours": len(rows), "paired_hours": count,
        "coverage": count / len(rows) if rows else 0,
        "forecast_hours": sum(row["forecast_mw"] is not None for row in rows),
        "actual_hours": sum(row["actual_mw"] is not None for row in rows),
        "mae_mw": None, "bias_mw": None, "rmse_mw": None,
        "p90_absolute_error_mw": None, "signed_energy_error_mwh": None,
    }
    if not count:
        return result
    absolute = sorted(abs(error) for error in errors)
    position = (count - 1) * 0.9
    lower = math.floor(position)
    upper = math.ceil(position)
    p90 = absolute[lower] + (absolute[upper] - absolute[lower]) * (position - lower)
    result.update(
        mae_mw=math.fsum(absolute) / count,
        bias_mw=math.fsum(errors) / count,
        rmse_mw=math.sqrt(math.fsum(error * error for error in errors) / count),
        p90_absolute_error_mw=p90,
        signed_energy_error_mwh=math.fsum(row["energy_error_mwh"] for row in paired),
    )
    return result


def evaluate(snapshot: Path, start: date, end: date, cutoff: time, *, connection) -> dict:
    if not DECISION_START <= start <= end <= DECISION_END:
        raise ValueError("Use an increasing inclusive decision-date range within January 2026")
    days, rows = [], []
    day = start
    while day <= end:
        selected = select_day(snapshot, day, cutoff, connection=connection)
        daily_rows = [with_error(row) for row in selected["rows"]]
        rows.extend(dict(row, decision_date=day.isoformat(), delivery_date=selected["delivery_date"])
                    for row in daily_rows)
        days.append({"decision_date": day.isoformat(), "delivery_date": selected["delivery_date"],
                     "cutoff": selected["cutoff"], "mixed_forecast_vintages": selected["mixed_forecast_vintages"],
                     "metrics": summarize(daily_rows)})
        day += timedelta(days=1)
    return {
        "snapshot_id": selected["snapshot_id"], "decision_start": start.isoformat(),
        "decision_end": end.isoformat(), "cutoff_local": cutoff.strftime("%H:%M"),
        "timezone": "Europe/London", "evaluation_mode": "retrospective",
        "error_definition": "forecast_minus_actual", "summary": summarize(rows),
        "days": days, "rows": rows,
    }
