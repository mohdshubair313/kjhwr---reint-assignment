# Phase 1: Elexon data contract and January audit

Status: Phase 1 audit completed on 25 October 2026. No application ingestion,
analytics endpoints or dashboard have been implemented in this phase.

Subsequent progress: ingestion and selection were implemented in Phase 2; see
[phase-2.md](phase-2.md). This document retains the original Phase 1 findings.

## Evidence and reproduction

Public API base: https://data.elexon.co.uk/bmrs/api/v1

Actual responses and exact requests are saved in `artifacts/phase-1/`:
- `requests.json`: acquisition URLs, including encoded timestamps.
- `windfor.json`: original forecast JSON response.
- `fuelhh.json`: original actual JSON response, filtered by WIND server-side.
- `audit.json`: reproducible counts, SHA-256 checksums and per-day coverage.

Run from the repository root with Python 3.14 (no extra dependencies):

```powershell
backend/.venv/Scripts/python.exe scripts/audit_phase1.py
```

The audit reads saved responses, writes only `audit.json`, and does not call the
network. These files are research evidence; Phase 2 will create the normalized,
versioned application snapshot and a resilient ingestion command.

## Verified endpoint behavior

| Dataset | Endpoint | Accepted query parameters |
| --- | --- | --- |
| Forecasts | `/datasets/WINDFOR/stream` | `publishDateTimeFrom`, `publishDateTimeTo` |
| Actuals | `/datasets/FUELHH/stream` | `publishDateTimeFrom`, `publishDateTimeTo`, `fuelType=WIND` |

Both responses are top-level JSON arrays, not objects containing a `data` array.
No API key was needed. Requests without filters returned current data.

Forecast fields observed: `dataset`, `publishTime`, `startTime`, `generation`.
Actual fields observed: those four plus `settlementDate`, `settlementPeriod`,
`fuelType`. All sampled timestamps have explicit UTC Z suffixes.

The FUELHH result contains records exactly at both requested publication bounds,
so inclusive bounds were observed there. Do not assume WINDFOR has identical
boundary behavior without a boundary probe. Internal windows must remain
half-open, with deduplication across request chunks.

Publication filtering is not delivery filtering. FUELHH publication at midnight
can describe the previous day's 23:30 interval. WINDFOR publications contain
multiple delivery dates, including delivery timestamps before publication.
Never use those later publications for historical decision forecasts.

## January audit results

| Check | Result |
| --- | ---: |
| Forecast records retrieved | 18,688 |
| Actual records retrieved | 1,493 |
| Conflicting or duplicate composite keys | 0 |
| Negative/non-numeric generation values | 0 |
| Forecast step inside every publication | 60 minutes |
| Expected delivery hours, 2 Jan–1 Feb | 744 |
| Hours with eligible forecasts at assumed cutoff | 744 |
| Hours with both required half-hour actuals | 744 |
| Actual delivery timestamps with multiple records | 0 |

Thus all 31 decision dates have 24 eligible hourly forecasts and 24 complete
actual-hour pairs under the initial policy. This is a completeness result, not
an accuracy result. The actual request deliberately includes boundary records;
only 1,488 of the 1,493 half-hours belong to the target delivery window.

Forecast publication range retrieved: 31 December 2025 02:30Z through 31 January
2026 22:30Z. Actual publication range: 2 January 00:00Z through 2 February 02:00Z.
Forecast delivery range extends beyond the evaluation window and must be trimmed.

Observed forecast publication UTC times: 02:30, 04:30, 07:30, 09:30, 11:30,
12:25, 15:30, 18:30 and 22:30. In particular, do not hard-code publication times
from the website's illustrative schedule: a nonstandard 12:25 publication exists.
Always select by actual `publishTime`.

## Implementation contract

1. Decision dates are 1–31 January 2026 in Europe/London. Delivery is the next
   local calendar day, from midnight inclusive to following midnight exclusive.
2. Initial cutoff is **09:00 Europe/London**, configurable. This is an explicit
   pilot assumption, not a verified exchange gate closure or client deadline.
3. For each delivery hour, select the greatest publication timestamp no later
   than the cutoff. Store the selected timestamp on every result row.
4. Evaluate at hourly resolution. Adopt the explicit modeling convention that
   forecast `startTime` labels the coming hour's mean MW; actual MW is the mean
   of the two FUELHH observations at t and t+30 minutes. Require both.
5. Timestamp cadence is verified; the interval-average interpretation is a
   modeling assumption, not something JSON timestamps alone prove. Retain it in
   methodology and confirm against authoritative field definitions if available.
6. Never multiply forecast MW by two to align resolution. For one-hour results,
   energy error in MWh equals signed MW error times one hour.
7. Forecast primary identity: dataset, startTime, publishTime. Actual identity
   retains dataset, fuelType, startTime and publishTime; resolved actual series
   must have one selected value per delivery half-hour.
8. Identical duplicates may collapse. Conflicting records require a documented
   revision rule or explicit failure/quality flag, never arbitrary averaging.
9. If no eligible forecast exists, preserve a gap. If different delivery hours
   select different publication vintages, expose that fact and staleness.
10. Use UTC internally; Europe/London in UI; never browser-default timezone.
11. Error = forecast - actual. Calculate MAE, bias, RMSE, P90 absolute error
    (linear interpolation convention), signed MWh error, count and coverage.
12. Zero matched observations means null metrics and zero coverage, not perfect
    accuracy. All metrics use the same paired observations.
13. A historical snapshot of actuals is retrospective and may include revisions.
    No claim is made that these actual values were available at decision time.

## Remaining uncertainties and next phase

- No numerical Elexon rate limit or latency SLA was established. Use conservative
  concurrency, bounded retries, timeout handling and Retry-After in Phase 2.
- Exact WINDFOR bound inclusivity and hourly mean semantics remain documented
  uncertainties. They do not justify silently changing or inventing data.
- The 09:00 cutoff remains a user-adjustable assumption.
- The full January dataset passes the observed coverage audit; this is not a
  guarantee about other months or subsequent upstream revisions.

Phase 2 should implement reusable fetching, validation, snapshot provenance,
normalization, deterministic forecast selection and focused correctness tests.
See [architecture-review.md](architecture-review.md) for the complete roadmap,
product boundaries and submission deliverables.
