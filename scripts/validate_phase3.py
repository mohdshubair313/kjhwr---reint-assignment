"""Build baseline evidence and export API validation results and OpenAPI.

Run from backend/: uv run python ../scripts/validate_phase3.py
"""

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app.api import create_app
from app.data.snapshot import build_snapshot


def main():
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "baseline.sqlite"
        build_snapshot(ROOT / "artifacts" / "phase-1", snapshot)
        with TestClient(create_app(snapshot)) as client:
            responses = {name: client.get(path) for name, path in {
                "health": "/health", "metadata": "/api/metadata",
                "forecast": "/api/forecast?decision_date=2026-01-01&cutoff=09:00",
                "evaluation": "/api/evaluation", "openapi": "/openapi.json",
            }.items()}
            for name, response in responses.items():
                if response.status_code != 200:
                    raise RuntimeError(f"{name} failed: {response.status_code}")
            data = responses["evaluation"].json()
            if data["summary"]["paired_hours"] != 744:
                raise RuntimeError("Expected all 744 paired delivery hours")
            report = {
                "validated_at": datetime.now(UTC).isoformat(),
                "transport": "FastAPI TestClient (in-process ASGI)",
                "snapshot_id": data["snapshot_id"],
                "http_statuses": {key: response.status_code for key, response in responses.items()},
                "decision_start": data["decision_start"], "decision_end": data["decision_end"],
                "cutoff_local": data["cutoff_local"], "timezone": data["timezone"],
                "evaluation_mode": data["evaluation_mode"], "summary": data["summary"],
                "daily_results": len(data["days"]), "hourly_results": len(data["rows"]),
            }
            (ROOT / "artifacts" / "openapi.json").write_text(
                json.dumps(responses["openapi"].json(), indent=2) + "\n", encoding="utf-8")
    (ROOT / "artifacts" / "phase-3-validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
