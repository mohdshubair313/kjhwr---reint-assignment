# Phase 3: metrics and FastAPI endpoints

Completed 25 October 2026. Backend version: 0.3.0. Phase 4 (frontend dashboard)
is next. Existing Phase 2 CLI commands remain supported.

## Run and explore

From `backend/`:

```powershell
uv sync --locked
uv run python -m app.data.cli build --source-dir ../artifacts/phase-1
uv run fastapi dev main.py
```

Visit `http://127.0.0.1:8000/docs` for interactive OpenAPI documentation. The root
redirects there until a frontend is added. An exported copy of the contract is
stored at `artifacts/openapi.json`; the running `/openapi.json` is authoritative.

## Endpoints

| Endpoint | Parameters and behavior |
| --- | --- |
| `GET /health` | Readiness: checks snapshot manifest and records table; 503 if unavailable |
| `GET /api/metadata` | Scope, provenance, snapshot ID, units, counts and methodology |
| `GET /api/forecast` | Required `decision_date`; optional `cutoff=09:00`; next-day forecast only |
| `GET /api/evaluation` | Optional inclusive `decision_start=2026-01-01`, `decision_end=2026-01-31`, `cutoff=09:00` |

Examples:

```text
/api/forecast?decision_date=2026-01-15&cutoff=09:00
/api/evaluation?decision_start=2026-01-15&decision_end=2026-01-15&cutoff=09:00
/api/evaluation?decision_start=2026-01-01&decision_end=2026-01-31&cutoff=09:00
```

Dates refer to **decision dates**, not delivery dates. January 31 decisions target
February 1 delivery. Cutoff must be exactly `HH:MM`, from `00:00` to `23:59`, in
Europe/London. Date ranges outside January and reversed ranges return 422.

The forecast response excludes actuals, paired coverage and actual-data warnings.
It includes forecast coverage, publication times, age, lead time, missing forecasts
and older-publication fallback flags. A later cutoff can legitimately select a
newer publication. It never selects a publication later than the requested cutoff.

The evaluation response contains:
- `summary`: pooled metrics for the entire decision-date range.
- `days`: delivery dates, UTC decision cutoffs, mixed-vintage indicator and daily metrics.
- `rows`: every expected delivery hour, forecast/actual values, their provenance,
  signed MW error, absolute MW error, signed MWh error, paired status and flags.
- `snapshot_id`: identifies the exact data and policy version used.
- `evaluation_mode=retrospective`: these results are not risk estimates available
  at the historical decision time.

All responses have Pydantic contracts exposed in OpenAPI. Timestamp output is UTC
with a timezone marker. Nullable values remain JSON null; generation zero remains
a valid observation. Floating-point metrics are returned without display rounding.

## Metric definitions

For each complete pair, error = forecast MW minus actual MW. Positive means wind
was overforecast. Every metric uses the same complete hourly pairs.

| Field | Definition |
| --- | --- |
| `expected_hours` | Number of expected hourly delivery intervals |
| `paired_hours` | Intervals containing forecast and both actual half-hours |
| `coverage` | Paired / expected; ratio from 0 to 1, not percentage |
| `forecast_hours` / `actual_hours` | Separate availability counts |
| `mae_mw` | Mean absolute error |
| `bias_mw` | Mean signed error |
| `rmse_mw` | Square root of mean squared error |
| `p90_absolute_error_mw` | Linear percentile interpolation at `0.9*(n-1)` |
| `signed_energy_error_mwh` | Sum of signed MW error times interval hours |

No complete pairs means null error metrics, including signed energy error, and
zero coverage. It does not mean zero error. A valid empty delivery day returns
200 with its complete grid and null values; missing/corrupt snapshots return 503.

Monthly metrics pool hourly observations. Averaging daily MAE or bias without
weighting by paired hours would be wrong when daily coverage differs. RMSE and
percentiles must also be calculated from the pooled observations.

## Runtime behavior and configuration

- Each request uses its own read-only SQLite connection and read transaction.
  Multi-day evaluation uses that same connection throughout, so a rebuild cannot
  mix snapshot versions within one response. Connections close even on failures.
- The API performs no upstream fetching and does not build missing snapshots.
  Run the explicit CLI build command before serving the app.
- Missing, corrupt or incompatible snapshots return 503 with an actionable,
  generic message. Filesystem paths are not included in the public response.
- `REINT_SNAPSHOT_PATH` overrides the default `backend/data/january-2026.sqlite`.
  Use an absolute path when running from different working directories.
- `REINT_CORS_ORIGINS` is a comma-separated allowlist. Defaults are
  `http://localhost:5173,http://127.0.0.1:5173`; an empty value disables CORS middleware.
  Browser cross-origin requests allow GET, no credentials. Production should use
  the deployed frontend origin or same-origin serving.
- `/health` is readiness, not a completeness guarantee. Use metadata and
  evaluation coverage to assess available observations.

## Implementation

- `backend/app/analytics.py`: error enrichment, pooled summary and daily evaluation.
- `backend/app/schemas.py`: typed response models and OpenAPI contracts.
- `backend/app/api.py`: application factory, dependencies, validation and routes.
- `backend/main.py`: FastAPI development/production entrypoint.
- `backend/tests/test_api.py`: numerical examples, API errors and integration tests.

No frontend implementation, trading recommendation, calibrated uncertainty band
or cost/savings calculation is introduced in this phase. The cutoff and hourly
mean interpretation remain the assumptions documented in `data-contract.md`.

## Validation results

```powershell
uv run python -W error::ResourceWarning -m unittest discover -s tests -v
uv run python ../scripts/validate_phase3.py
```

38 tests passed (24 existing pipeline tests plus 14 metric/API tests). Tests cover
hand-calculated errors and percentile interpolation, zero/missing values, unequal
daily coverage, cutoff changes, invalid inputs, missing/corrupt snapshots, CORS,
OpenAPI, no upstream IO and full-January row-to-summary reconciliation.

In-process ASGI smoke checks returned 200 for health, metadata, forecast,
evaluation and OpenAPI. See `artifacts/phase-3-validation.json` for the saved
snapshot identity and unrounded results. This is not an external deployment test.

For January decision dates at the assumed 09:00 London cutoff:

| Metric | Result |
| --- | ---: |
| Complete hourly pairs | 744 / 744 |
| MAE | 2,038.91 MW |
| Bias | +1,747.89 MW |
| RMSE | 2,504.76 MW |
| P90 absolute error | 4,097.90 MW |
| Signed energy error | +1,300,428.00 MWh |

These describe the selected Elexon series and documented hourly alignment, not
the client's portfolio, a financial loss or a verified procurement requirement.
