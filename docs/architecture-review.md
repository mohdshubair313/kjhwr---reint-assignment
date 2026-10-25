# REint architecture and requirement review

Reviewed 25 October 2026. Source brief: [AGENTS.md](../AGENTS.md).
This document preserves the agreed planning context. Phase 1 findings and
implementation assumptions are maintained in [data-contract.md](data-contract.md).

Progress: Phases 1–3 are complete. See [phase-2.md](phase-2.md) for the pipeline
and [phase-3.md](phase-3.md) for metrics, API contracts and validation evidence.
Phase 4 (frontend dashboard) is next.

## Scope and deliverables

- Help a UK utility understand wind forecasts available for day-ahead decisions
  and quantitatively evaluate their accuracy using Elexon alone.
- Interpret January 2026 as **decision dates 1–31 January**, corresponding to
  delivery dates **2 January–1 February**. State this explicitly in the UI.
- React + TypeScript + Vite frontend; Tailwind and Recharts planned.
- Python + FastAPI backend managed with uv; Docker; Vercel or Heroku deployment.
- Maximum assignment effort: 16 hours. Build a focused, reproducible pilot.
- Public GitHub repository with anonymous name; README with structure, startup,
  deployed URL and explicit AI-use disclosure.
- Unlisted YouTube video, maximum 10 minutes: client presentation and technical
  review, each with at most five minutes of initial overview.
- Verify all submitted links in incognito and submit using the form in AGENTS.md.

## Critical analytical rules

1. Select the latest forecast for each delivery interval with publishTime at or
   before the selected decision cutoff. Never use hindsight updates.
2. A single decision cutoff applies to the next delivery day. This differs from
   selecting forecasts exactly 24 hours ahead of every interval.
3. The client has not specified a cutoff or auction. Make cutoff configurable;
   label the initial value as an assumption, not a market deadline.
4. Verify cadence using real records: Elexon's wind guidance describes hourly
   forecasts while FUELHH is half-hourly. Do not silently interpolate or compare
   hourly forecasts with only one half-hour actual.
5. Preserve all forecast vintages, source records and retrieval provenance.
6. Maintain an expected delivery grid. Missing values remain gaps, never zero.
   Only complete matched observations contribute to metrics; show coverage.
7. Deduplicate identical records. Resolve conflicts using documented revision
   metadata or flag them; do not arbitrarily sum or average forecast vintages.
8. Flag incomplete publications and make fallback to older forecasts explicit.
9. Use aware UTC timestamps internally; display Europe/London explicitly.
   January uses GMT. Future DST dates cannot assume 48 half-hours per day.
10. publishTime is a proxy for historical availability, not proof of client receipt.
11. Full-month evaluation is retrospective. Decision-time risk estimates must not
    use outcomes unavailable at the selected historical cutoff.

## Metrics

Signed error = forecast minus actual. Positive means wind overforecasting.

| Metric | Meaning |
| --- | --- |
| MAE (MW) | Typical absolute miss |
| Bias (MW) | Direction of systematic error |
| RMSE (MW) | Sensitivity to larger misses |
| P90 absolute error (MW) | Larger historical misses |
| Matched count and coverage | Evidence supporting the metrics |
| Signed energy error (MWh) | Sum of error times interval duration in hours |

Show daily MAE/bias; delivery-hour and lead-time breakdowns are useful extensions.
Avoid headline MAPE because actual generation near zero destabilizes it. Never
present bias alone: positive and negative errors cancel. Use consistent matched
observations and forecast policy throughout. Define percentile convention.

## Product boundaries

The specified wind forecast covers farms visible to the system operator with
operational metering. Do not claim complete UK renewable coverage. These series
alone cannot calculate the client's procurement requirement, financial savings,
or trading profit: demand, portfolio, contract and price inputs are absent.

## Architecture

Elexon -> ingestion/validation -> versioned snapshot -> selection/metrics ->
FastAPI -> React dashboard.

Use a reproducible read-only SQLite snapshot for this historical pilot. Fetch
outside the request path; rebuild explicitly. Retain provenance and checksums.
Continuous production ingestion would require scheduling and durable storage.

Proposed API:
- GET /api/metadata: scope, units, resolution, provenance and methodology.
- GET /api/forecast: next-day forecast available at a decision cutoff.
- GET /api/evaluation: aligned values, metrics and daily breakdowns.
- GET /health: health status.

Backend owns calculations. Responses carry publication times, cutoff policy,
coverage and missing-data flags. Frontend renders those results consistently.

Dashboard: decision date/cutoff controls, publication age and coverage, forecast
versus retrospective actual chart, signed-error chart, KPI cards, monthly
overview, methodology, and loading/empty/partial/error states.

Prefer a single image containing the built React app and FastAPI for a simple
same-origin Heroku deployment. Bind to platform PORT. Heroku runtime filesystem
writes are ephemeral; bundle the fixed snapshot or use external durable storage.

## Execution budget

| Phase | Deliverable | Hours |
| --- | --- | ---: |
| 1 | Verify data contract, cadence, coverage, scope and cutoff | 1.5 |
| 2 | Ingestion, validation, deduplication, snapshot, selection | 3 |
| 3 | API, metrics, focused correctness tests | 2.5 |
| 4 | Dashboard and charts | 4 |
| 5 | Docker, deployment, smoke checks | 2 |
| 6 | README, methodology, video, public access verification | 3 |
| Total | | 16 |

Test meaningful failure modes: look-ahead leakage, month boundaries, conflicting
duplicates, missing half-hours, timezone handling, coverage and known metric
examples. Do not expand infrastructure beyond the pilot's needs.

## API risks and verification

Elexon public APIs require no API key. Stream endpoints return JSON; their
documented lack of data-return limits does not guarantee unlimited throughput.
No numerical request-rate guarantee was established in this review. Use bounded
requests, timeouts, retry backoff and Retry-After handling. Stream is not a
WebSocket subscription. Verify whether endpoint filters concern publication or
delivery time and whether bounds are inclusive. Use internal half-open windows.

At initial review, the linked endpoint documentation was JavaScript-rendered;
exact parameters, January completeness and cadence still required live checks.
Consult the Phase 1 contract for subsequent evidence.

## Sources

- https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream
- https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream
- https://developer.data.elexon.co.uk/
- https://bmrs.elexon.co.uk/wind-generation
- https://devcenter.heroku.com/articles/container-registry-and-runtime
- https://vercel.com/kb/guide/docker

Initial repository inspection found FastAPI and React/Vite scaffolds; Tailwind
and Recharts were not yet declared dependencies. No implementation was changed
during the initial review.
