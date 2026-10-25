"""Public response contracts; OpenAPI is the frontend integration contract."""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Metrics(Contract):
    expected_hours: int = Field(ge=0)
    paired_hours: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    forecast_hours: int = Field(ge=0)
    actual_hours: int = Field(ge=0)
    mae_mw: float | None = Field(ge=0)
    bias_mw: float | None
    rmse_mw: float | None = Field(ge=0)
    p90_absolute_error_mw: float | None = Field(ge=0)
    signed_energy_error_mwh: float | None


class ForecastPoint(Contract):
    start_time: AwareDatetime
    end_time: AwareDatetime
    forecast_mw: float | None = Field(ge=0)
    forecast_publish_time: AwareDatetime | None
    forecast_age_hours: float | None = Field(ge=0)
    lead_time_hours: float | None = Field(ge=0)
    quality_flags: list[Literal["missing_forecast", "missing_actual_half_hour", "older_publication_fallback"]]


class ForecastResponse(Contract):
    snapshot_id: str
    decision_date: date
    delivery_date: date
    cutoff: AwareDatetime
    timezone: Literal["Europe/London"]
    cutoff_is_assumption: bool
    expected_hours: int
    forecast_hours: int
    forecast_coverage: float = Field(ge=0, le=1)
    mixed_forecast_vintages: bool
    rows: list[ForecastPoint]


class EvaluationPoint(ForecastPoint):
    decision_date: date
    delivery_date: date
    actual_mw: float | None = Field(ge=0)
    actual_publish_times: list[AwareDatetime | None]
    paired: bool
    error_mw: float | None
    absolute_error_mw: float | None = Field(ge=0)
    energy_error_mwh: float | None


class DailyEvaluation(Contract):
    decision_date: date
    delivery_date: date
    cutoff: AwareDatetime
    mixed_forecast_vintages: bool
    metrics: Metrics


class EvaluationResponse(Contract):
    snapshot_id: str
    decision_start: date
    decision_end: date
    cutoff_local: str
    timezone: Literal["Europe/London"]
    evaluation_mode: Literal["retrospective"]
    error_definition: Literal["forecast_minus_actual"]
    summary: Metrics
    days: list[DailyEvaluation]
    rows: list[EvaluationPoint]


class Source(Contract):
    dataset: Literal["WINDFOR", "FUELHH"]
    url: str
    sha256: str
    retrieved_at: AwareDatetime | None
    retrieved_date: date | None


class MetadataResponse(Contract):
    snapshot_id: str
    normalized_sha256: str
    schema_version: int
    policy_version: str
    decision_start: date
    decision_end: date
    delivery_start: date
    delivery_end: date
    timezone: Literal["Europe/London"]
    default_cutoff: str
    resolution_minutes: int
    generation_unit: Literal["MW"]
    energy_unit: Literal["MWh"]
    record_counts: dict[str, int]
    sources: list[Source]
    methodology: list[str]


class HealthResponse(Contract):
    status: Literal["ok"]
    snapshot_id: str


class ErrorResponse(Contract):
    detail: str
