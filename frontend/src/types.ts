// Public contracts mirror backend/app/schemas.py and artifacts/openapi.json.
export interface Metrics {
  expected_hours: number
  paired_hours: number
  coverage: number
  forecast_hours: number
  actual_hours: number
  mae_mw: number | null
  bias_mw: number | null
  rmse_mw: number | null
  p90_absolute_error_mw: number | null
  signed_energy_error_mwh: number | null
}
export interface ForecastPoint {
  start_time: string
  end_time: string
  forecast_mw: number | null
  forecast_publish_time: string | null
  forecast_age_hours: number | null
  lead_time_hours: number | null
  quality_flags: string[]
}
export interface EvaluationPoint extends ForecastPoint {
  decision_date: string
  delivery_date: string
  actual_mw: number | null
  actual_publish_times: (string | null)[]
  paired: boolean
  error_mw: number | null
  absolute_error_mw: number | null
  energy_error_mwh: number | null
}
export interface DailyEvaluation {
  decision_date: string
  delivery_date: string
  cutoff: string
  mixed_forecast_vintages: boolean
  metrics: Metrics
}
export interface Evaluation {
  snapshot_id: string
  decision_start: string
  decision_end: string
  cutoff_local: string
  timezone: string
  evaluation_mode: 'retrospective'
  error_definition: 'forecast_minus_actual'
  summary: Metrics
  days: DailyEvaluation[]
  rows: EvaluationPoint[]
}
export interface Forecast {
  snapshot_id: string
  decision_date: string
  delivery_date: string
  cutoff: string
  timezone: string
  cutoff_is_assumption: boolean
  expected_hours: number
  forecast_hours: number
  forecast_coverage: number
  mixed_forecast_vintages: boolean
  rows: ForecastPoint[]
}
export interface Metadata {
  snapshot_id: string
  normalized_sha256: string
  schema_version: number
  policy_version: string
  decision_start: string
  decision_end: string
  delivery_start: string
  delivery_end: string
  timezone: string
  default_cutoff: string
  resolution_minutes: number
  generation_unit: string
  energy_unit: string
  record_counts: Record<string, number>
  sources: { dataset: string; url: string; sha256: string; retrieved_at: string | null; retrieved_date: string | null }[]
  methodology: string[]
}
export interface Query { date: string; cutoff: string }
export interface DashboardData { metadata: Metadata; forecast: Forecast; evaluation: Evaluation }
