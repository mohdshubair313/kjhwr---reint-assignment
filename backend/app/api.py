"""Read-only API: one SQLite read transaction per request, no upstream IO."""

import json
import logging
import os
import sqlite3
from datetime import date, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .analytics import evaluate
from .data.models import DataError, DECISION_END, DECISION_START
from .data.selection import select_day
from .data.snapshot import connect_readonly
from .schemas import (ErrorResponse, EvaluationResponse, ForecastPoint, ForecastResponse,
                      HealthResponse, MetadataResponse)

LOGGER = logging.getLogger(__name__)
DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "january-2026.sqlite"

METHODOLOGY = [
    "Decision dates are in January 2026; delivery is the next London calendar day.",
    "09:00 Europe/London is a configurable pilot assumption, not a verified market deadline.",
    "For each delivery hour, select the latest publication at or before the decision cutoff.",
    "WINDFOR startTime is assumed to label the coming hour's mean MW; interval semantics remain unconfirmed.",
    "Hourly actual MW is the mean of both half-hours, using their latest publications in this snapshot.",
    "Missing observations remain null. All metrics use the same complete hourly pairs.",
    "Error is forecast minus actual: positive means wind overforecasting.",
    "MAE=mean(abs(error)); bias=mean(error); RMSE=sqrt(mean(error squared)).",
    "P90 absolute error uses linear interpolation at index 0.9*(n-1) in sorted absolute errors.",
    "Signed energy error sums error times interval duration in hours. Coverage is paired/expected hours.",
    "Monthly metrics pool hourly pairs; they are not unweighted averages of daily metrics.",
    "Evaluation is retrospective, not decision-time risk information. Actuals may include later revisions.",
    "publishTime is an availability proxy; receipt latency is unknown. Snapshot acquisition dates are not forecast publication dates.",
    "These Elexon series alone cannot establish the utility's procurement volumes or financial savings.",
]


def create_app(snapshot_path: Path | None = None) -> FastAPI:
    snapshot = Path(snapshot_path or os.environ.get("REINT_SNAPSHOT_PATH", DEFAULT_SNAPSHOT)).resolve()
    app = FastAPI(title="REint Wind Forecast API", version="0.3.0",
                  description="January 2026 day-ahead forecast replay and retrospective accuracy.")
    origins = [value.strip() for value in os.environ.get("REINT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if value.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["Accept"])

    def database():
        connection = None
        try:
            connection = connect_readonly(snapshot)
            connection.execute("BEGIN")
            yield connection
        except (sqlite3.Error, DataError, OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Snapshot unavailable: %s", exc)
            raise HTTPException(503, "Snapshot unavailable. Build or restore the configured dataset.") from exc
        finally:
            if connection is not None:
                connection.close()

    def cutoff_time(cutoff: Annotated[str, Query(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$",
                                               description="Local Europe/London decision cutoff, HH:MM")] = "09:00") -> time:
        return time.fromisoformat(cutoff)

    def check_day(day: date):
        if not DECISION_START <= day <= DECISION_END:
            raise HTTPException(422, "Decision dates must be within January 2026.")

    def manifest(connection):
        row = connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        if row is None:
            raise DataError("Missing snapshot manifest")
        value = json.loads(row[0])
        required = {"snapshot_id", "normalized_sha256", "schema_version", "policy_version",
                    "decision_start", "decision_end", "default_cutoff", "counts", "sources"}
        if not isinstance(value, dict) or not required <= value.keys():
            raise DataError("Incomplete snapshot manifest")
        return value

    unavailable = {503: {"model": ErrorResponse, "description": "Snapshot is missing or unreadable"}}

    static_dir = Path(os.environ.get("REINT_STATIC_DIR", "")).resolve() if os.environ.get("REINT_STATIC_DIR") else None
    if static_dir and static_dir.is_dir():
        index_html = static_dir / "index.html"

        @app.get("/", include_in_schema=False)
        def root():
            return FileResponse(index_html, media_type="text/html")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse("/docs")

    @app.get("/health", response_model=HealthResponse, responses=unavailable)
    def health(connection=Depends(database)):
        info = manifest(connection)
        connection.execute("SELECT dataset, start, published, generation FROM records LIMIT 1").fetchone()
        return {"status": "ok", "snapshot_id": info["snapshot_id"]}

    @app.get("/api/metadata", response_model=MetadataResponse, responses=unavailable)
    def get_metadata(connection=Depends(database)):
        info = manifest(connection)
        return {
            "snapshot_id": info["snapshot_id"], "normalized_sha256": info["normalized_sha256"],
            "schema_version": info["schema_version"], "policy_version": info["policy_version"],
            "decision_start": info["decision_start"], "decision_end": info["decision_end"],
            "delivery_start": DECISION_START + timedelta(days=1), "delivery_end": DECISION_END + timedelta(days=1),
            "timezone": "Europe/London", "default_cutoff": info["default_cutoff"], "resolution_minutes": 60,
            "generation_unit": "MW", "energy_unit": "MWh", "record_counts": info["counts"],
            "sources": [{"dataset": source["dataset"], "url": source["url"], "sha256": source["sha256"],
                         "retrieved_at": source.get("retrieved_at"), "retrieved_date": source.get("retrieved_date")}
                        for source in info["sources"]], "methodology": METHODOLOGY,
        }

    @app.get("/api/forecast", response_model=ForecastResponse, responses=unavailable)
    def forecast(decision_date: date, cutoff: time = Depends(cutoff_time), connection=Depends(database)):
        check_day(decision_date)
        manifest(connection)
        selected = select_day(snapshot, decision_date, cutoff, connection=connection)
        fields = set(ForecastPoint.model_fields)
        points = [{key: value for key, value in row.items() if key in fields} for row in selected["rows"]]
        for point in points:
            point["quality_flags"] = [flag for flag in point["quality_flags"] if flag != "missing_actual_half_hour"]
        keys = {"snapshot_id", "decision_date", "delivery_date", "cutoff", "timezone", "cutoff_is_assumption",
                "expected_hours", "forecast_hours", "mixed_forecast_vintages"}
        return {**{key: selected[key] for key in keys}, "rows": points,
                "forecast_coverage": selected["forecast_hours"] / selected["expected_hours"]}

    @app.get("/api/evaluation", response_model=EvaluationResponse, responses=unavailable)
    def evaluation(decision_start: date = DECISION_START, decision_end: date = DECISION_END,
                   cutoff: time = Depends(cutoff_time), connection=Depends(database)):
        check_day(decision_start)
        check_day(decision_end)
        if decision_start > decision_end:
            raise HTTPException(422, "decision_start must not be after decision_end.")
        manifest(connection)
        return evaluate(snapshot, decision_start, decision_end, cutoff, connection=connection)

    # Mount static files LAST so they never shadow API routes or /health
    if static_dir and static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
