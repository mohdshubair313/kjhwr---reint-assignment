"""Compare independent live acquisition with the Phase 1 baseline, offline.

Run from backend/: uv run python ../scripts/validate_phase2.py
Requires the CLI fetch output at artifacts/phase-2-fetch/.
"""

import json
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data.selection import coverage_report, select_day
from app.data.snapshot import build_snapshot


def main():
    with tempfile.TemporaryDirectory() as temporary:
        baseline_path = Path(temporary) / "baseline.sqlite"
        live_path = Path(temporary) / "live.sqlite"
        baseline = build_snapshot(ROOT / "artifacts" / "phase-1", baseline_path)
        live = build_snapshot(ROOT / "artifacts" / "phase-2-fetch", live_path)
        if baseline["normalized_sha256"] != live["normalized_sha256"]:
            raise RuntimeError("Live acquisition differs from retained baseline; investigate revisions or boundaries")
        coverage = coverage_report(live_path)
        if coverage["paired_hours"] != 744 or coverage["expected_hours"] != 744:
            raise RuntimeError("January does not contain all 744 expected paired delivery hours")
        for day in coverage["days"]:
            selected = select_day(live_path, date.fromisoformat(day["decision_date"]))
            for row in selected["rows"]:
                if row["forecast_publish_time"] is None or row["forecast_publish_time"] > selected["cutoff"]:
                    raise RuntimeError("Selected forecast violates historical cutoff")
        report = {
            "validated_at": datetime.now(UTC).isoformat(),
            "baseline_snapshot_id": baseline["snapshot_id"],
            "live_snapshot_id": live["snapshot_id"],
            "normalized_sha256": live["normalized_sha256"],
            "normalized_records_match": True,
            "live_source_files": len(live["sources"]),
            "live_counts": live["counts"],
            "no_lookahead_for_all_744_hours": True,
            "coverage": coverage,
            "first_delivery_hour": select_day(live_path, date(2026, 1, 1))["rows"][0],
            "last_delivery_hour": select_day(live_path, date(2026, 1, 31))["rows"][-1],
        }
    output = ROOT / "artifacts" / "phase-2-validation.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"coverage", "first_delivery_hour", "last_delivery_hour"}}, indent=2))
    print(f"Coverage: {coverage['paired_hours']}/{coverage['expected_hours']} hours; report: {output}")


if __name__ == "__main__":
    main()
