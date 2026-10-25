# Phase 2: ingestion, normalization and forecast selection

Status: completed and validated on 25 October 2026.

## Components

- `models.py`: strict record validation, timezone conversion and delivery bounds.
- `client.py`: sequential HTTP acquisition with a 30-second timeout, four total
  attempts, exponential backoff/jitter, Retry-After seconds/date parsing, and a
  32 MiB response cap. Retry only transient HTTP/network/incomplete-read failures.
  If Retry-After exceeds 30 seconds, fail with an actionable message rather than
  retrying too early. Invalid JSON and other HTTP errors fail immediately.
- `snapshot.py`: verified source hashes, normalization, duplicate/conflict rules,
  deterministic IDs, indexed SQLite generation, integrity check, atomic replacement.
- `selection.py`: read-only historical forecast selection and complete hourly grid.
- `cli.py`: explicit `fetch`, `build`, `inspect` and `select` commands.

Run commands from `backend/`; see the root README for examples. The application
request path never fetches Elexon data. This phase does not implement HTTP
analytics endpoints, metrics, frontend features or deployment.

## Acquisition and reproducibility

Acquisition uses daily publication windows and a one-second overlap at each lower
bound. This protects against exclusive lower bounds without guessing the API's
exact inclusivity. Normalization applies explicit half-open source windows.

Forecast publications span `[2025-12-31T00:00Z, 2026-02-01T00:00Z)`.
Actual publications span `[2026-01-02T00:00Z, 2026-02-02T02:00:01Z)`; the extra
second retains the exact 02:00 actual publication from the original audit.
These windows are a bounded historical extract, not all subsequent revisions.

Every successful acquisition saves immutable content-addressed raw JSON and a
`sources.json` manifest containing request URL, publication bounds, acquisition
timestamp and SHA-256. Files and manifests are published with atomic replacement.
A failed acquisition leaves the prior complete manifest available; orphaned raw
files from incomplete runs are harmless. Fetch currently restarts its request
sequence rather than resuming partially completed requests.

Offline import supports the original Phase 1 artifacts. Their exact acquisition
time was not recorded, so imported provenance records only the known date and
explicitly leaves `retrieved_at` null.

The SQLite manifest stores schema/policy versions, source provenance, record
counts, a normalized-record hash and a snapshot ID. Snapshot ID covers provenance
and policy as well as data; a new acquisition can have a different snapshot ID
even when normalized values are unchanged. The normalized hash allows comparison
across independently acquired evidence. Rebuilding the same sources is deterministic.

Snapshots are generated locally and excluded from Git; retained Phase 1 evidence
is the reproducible baseline. A future Docker build can generate and bundle the
snapshot without making startup depend on upstream availability.

## Validation and selection rules

- Accept aware, whole-second ISO timestamps and normalize to UTC epoch seconds.
- Require valid finite nonnegative numeric wind generation; reject booleans,
  strings, null, NaN and infinity. Zero remains a valid observation.
- Filter non-WIND actual rows; require hourly forecasts and half-hour actual grid.
- Cross-check actual settlement date/period against Europe/London startTime.
- Preserve all distinct publication vintages. Collapse identical duplicates;
  fail on conflicting values for the same normalized identity.
- Do not silently skip malformed wind rows or overwrite an existing good
  snapshot after validation fails.
- Actual revision rule: latest retained publication for each half-hour. This is
  retrospective; publication timestamps remain in the selected result.
- Forecast rule: latest eligible publication per delivery hour at or before the
  selected January decision cutoff. Equality at cutoff is allowed.
- If a newer eligible publication covers other hours but omits an hour, retain
  its older eligible forecast and expose `older_publication_fallback`.
- Every expected delivery hour is returned, including null gaps, actual half-hour
  publication times, forecast age, lead time, paired status and quality flags.
- Expose mixed forecast vintages. No arbitrary stale threshold is imposed;
  forecast age is available for a later, explicit product rule.
- Coverage is paired hours / expected hours. Partial datasets can be built and
  inspected; coverage is never inferred from the number of returned records alone.

## Scope and assumptions

Public selection is deliberately restricted to January 2026 decision dates.
Europe/London delivery-bound calculation supports DST, but this does not imply
the rest of the application has been validated for other months. Explicit
`tzdata` supports Windows and minimal deployment environments.

The 09:00 cutoff and the hourly mean interpretation remain modeling assumptions.
No exchange deadline or procurement strategy is implied. Forecast `publishTime`
is the availability proxy; actual receipt latency cannot be reconstructed here.

## Verification

The unittest suite exercises source corruption, conflicting duplicates, atomic
replacement, readonly access, deterministic rebuilds, zero/missing values,
publication windows, inclusive decision cutoff, hindsight exclusion, revised
actuals, incomplete actual pairs, mixed vintages, month boundaries, DST bounds,
bounded retries, Retry-After and malformed responses.

An integration test rebuilds the full retained January evidence, checks all 744
delivery hours and verifies that every selected forecast publication is no later
than its decision cutoff. Live acquisition and baseline comparison results are
recorded in `artifacts/phase-2-validation.json` after the verification run.

Validation outcome:
- 24 automated tests passed, with resource warnings treated as errors.
- Live acquisition completed 64 daily requests and returned 20,212 source rows.
- Half-open normalization excluded 31 overlapping boundary rows, retaining
  18,688 forecasts and 1,493 actual records.
- The live normalized-record SHA-256 exactly matches the Phase 1 baseline:
  `773bc84dcb7054d82d730d7d86cee8c6d8621dcc0993b91dd6750e0ce4644b4a`.
- All 744/744 target delivery hours are paired at 09:00 London, and every selected
  forecast satisfies the decision cutoff.
- The default generated snapshot uses the retained Phase 1 baseline for easy
  offline reproduction. The separately acquired live sources remain local evidence.

To repeat the offline comparison after fetching:

```powershell
uv run python ../scripts/validate_phase2.py
```

Next phase: backend metrics and API contracts. The original cutoff and interval
interpretation assumptions remain explicit; this validation does not resolve them.
