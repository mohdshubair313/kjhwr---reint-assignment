import json
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.analytics import summarize, with_error
from app.api import create_app
from app.data.snapshot import build_snapshot
from test_data_pipeline import actual, forecast, write_sources


def error_row(forecast_mw, actual_mw):
    return with_error({"start_time": "2026-01-02T00:00:00Z", "end_time": "2026-01-02T01:00:00Z",
                       "forecast_mw": forecast_mw, "actual_mw": actual_mw})


class MetricTests(unittest.TestCase):
    def test_known_errors_sign_units_and_percentile(self):
        result = summarize([error_row(90, 100), error_row(100, 100), error_row(130, 100), error_row(None, 100)])
        self.assertEqual(result["paired_hours"], 3)
        self.assertEqual(result["coverage"], .75)
        self.assertAlmostEqual(result["mae_mw"], 40 / 3)
        self.assertAlmostEqual(result["bias_mw"], 20 / 3)
        self.assertAlmostEqual(result["rmse_mw"], math.sqrt(1000 / 3))
        self.assertAlmostEqual(result["p90_absolute_error_mw"], 26)
        self.assertEqual(result["signed_energy_error_mwh"], 20)

    def test_no_pairs_has_null_metrics(self):
        for rows in ([], [error_row(None, 100)], [error_row(100, None)]):
            result = summarize(rows)
            self.assertEqual(result["paired_hours"], 0)
            self.assertEqual(result["coverage"], 0)
            for key in ("mae_mw", "bias_mw", "rmse_mw", "p90_absolute_error_mw", "signed_energy_error_mwh"):
                self.assertIsNone(result[key])

    def test_zero_pair_and_singleton_percentile(self):
        result = summarize([error_row(0, 0)])
        self.assertEqual(result["coverage"], 1)
        self.assertEqual(result["p90_absolute_error_mw"], 0)
        self.assertEqual(result["mae_mw"], 0)
        self.assertEqual(summarize([error_row(10, 30)])["p90_absolute_error_mw"], 20)

    def test_non_hourly_data_rejected(self):
        with self.assertRaises(ValueError):
            with_error({"forecast_mw": 100, "actual_mw": 80, "start_time": "2026-01-02T00:00:00Z",
                        "end_time": "2026-01-02T00:30:00Z"})


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "data.sqlite"
        forecasts = [forecast(value=110), forecast("2026-01-02T01:00:00Z", value=70),
                     forecast(published="2026-01-01T09:01:00Z", value=999)]
        actuals = [actual(value=80), actual("2026-01-02T00:30:00Z", value=120),
                   actual("2026-01-02T01:00:00Z", value=80), actual("2026-01-02T01:30:00Z", value=100)]
        write_sources(self.root, forecasts, actuals)
        self.manifest = build_snapshot(self.root, self.path)
        self.client = TestClient(create_app(self.path))
        self.addCleanup(self.client.close)

    def test_health_and_metadata(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        response = self.client.get("/api/metadata")
        self.assertEqual(response.status_code, 200)
        info = response.json()
        self.assertEqual(info["delivery_end"], "2026-02-01")
        self.assertEqual(info["snapshot_id"], self.manifest["snapshot_id"])
        self.assertEqual(info["generation_unit"], "MW")
        self.assertTrue(info["methodology"])
        self.assertNotIn(str(self.path), response.text)

    def test_forecast_has_no_actuals_and_obeys_cutoff(self):
        response = self.client.get("/api/forecast", params={"decision_date": "2026-01-01"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["forecast_coverage"], 2 / 24)
        self.assertEqual(data["rows"][0]["forecast_mw"], 110)
        self.assertEqual(len(data["rows"]), 24)
        self.assertNotIn("actual_mw", data["rows"][0])
        self.assertNotIn("missing_actual_half_hour", data["rows"][2]["quality_flags"])
        later = self.client.get("/api/forecast", params={"decision_date": "2026-01-01", "cutoff": "09:01"}).json()
        self.assertEqual(later["rows"][0]["forecast_mw"], 999)

    def test_evaluation_matches_known_values_and_preserves_gaps(self):
        response = self.client.get("/api/evaluation", params={"decision_start": "2026-01-01", "decision_end": "2026-01-01"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        summary = data["summary"]
        self.assertEqual(summary["mae_mw"], 15)
        self.assertEqual(summary["bias_mw"], -5)
        self.assertAlmostEqual(summary["rmse_mw"], math.sqrt(250))
        self.assertEqual(summary["p90_absolute_error_mw"], 19)
        self.assertEqual(summary["signed_energy_error_mwh"], -10)
        self.assertEqual(summary["paired_hours"], 2)
        self.assertEqual(data["days"][0]["metrics"], summary)
        self.assertEqual(data["rows"][0]["error_mw"], 10)
        self.assertIsNone(data["rows"][2]["error_mw"])
        self.assertEqual(data["evaluation_mode"], "retrospective")

    def test_empty_delivery_day_is_200_with_null_metrics(self):
        data = self.client.get("/api/evaluation", params={"decision_start": "2026-01-31", "decision_end": "2026-01-31"}).json()
        self.assertEqual(data["summary"]["coverage"], 0)
        self.assertIsNone(data["summary"]["mae_mw"])
        self.assertEqual(data["rows"][-1]["end_time"], "2026-02-02T00:00:00Z")

    def test_monthly_metrics_pool_observations(self):
        forecasts = [forecast(value=150)]
        actuals = [actual(value=100), actual("2026-01-02T00:30:00Z", value=100)]
        for hour in range(3):
            forecasts.append(forecast(f"2026-01-03T{hour:02d}:00:00Z", "2026-01-02T07:30:00Z", 90))
            for minute in (0, 30):
                actuals.append(actual(f"2026-01-03T{hour:02d}:{minute:02d}:00Z", "2026-01-04T00:00:00Z", 100))
        write_sources(self.root, forecasts, actuals)
        build_snapshot(self.root, self.path)
        response = self.client.get("/api/evaluation", params={"decision_start": "2026-01-01", "decision_end": "2026-01-02"})
        summary = response.json()["summary"]
        self.assertEqual(summary["paired_hours"], 4)
        self.assertEqual(summary["bias_mw"], 5)  # Not (50 + -10) / 2 = 20.
        self.assertEqual(summary["mae_mw"], 20)
        self.assertAlmostEqual(summary["rmse_mw"], math.sqrt(700))

    def test_invalid_dates_and_cutoffs_are_422(self):
        cases = [("/api/forecast", {}), ("/api/forecast", {"decision_date": "2026-02-01"}),
                 ("/api/forecast", {"decision_date": "bad"}),
                 ("/api/evaluation", {"decision_start": "2026-01-02", "decision_end": "2026-01-01"}),
                 ("/api/evaluation", {"decision_start": "2025-12-31"})]
        cases += [("/api/forecast", {"decision_date": "2026-01-01", "cutoff": cutoff})
                  for cutoff in ("24:00", "9:00", "09:00:01", "09:00Z", "abc")]
        for route, params in cases:
            with self.subTest(route=route, params=params):
                self.assertEqual(self.client.get(route, params=params).status_code, 422)

    def test_missing_corrupt_or_wrong_version_snapshot_returns_503(self):
        for mode in ("missing", "corrupt", "wrong_version"):
            bad = self.root / (mode + ".sqlite")
            if mode == "corrupt":
                bad.write_text("broken database")
            elif mode == "wrong_version":
                with closing(sqlite3.connect(bad)) as db:
                    db.execute("PRAGMA user_version=999")
            with TestClient(create_app(bad)) as client:
                for route in ("/health", "/api/metadata", "/api/forecast?decision_date=2026-01-01", "/api/evaluation"):
                    with self.subTest(mode=mode, route=route):
                        response = client.get(route)
                        self.assertEqual(response.status_code, 503)
                        self.assertNotIn(str(bad), response.text)

    def test_no_upstream_requests_and_openapi_contract(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")):
            self.assertEqual(self.client.get("/api/evaluation").status_code, 200)
        spec = self.client.get("/openapi.json").json()
        self.assertIn("EvaluationResponse", spec["components"]["schemas"])
        self.assertIn("/api/forecast", spec["paths"])

    def test_cors_allows_configured_dev_origin_only(self):
        good = self.client.get("/health", headers={"Origin": "http://localhost:5173"})
        bad = self.client.get("/health", headers={"Origin": "https://unlisted.example"})
        self.assertEqual(good.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertNotIn("access-control-allow-origin", bad.headers)


class JanuaryAPITest(unittest.TestCase):
    def test_full_month_endpoint_and_row_reconciliation(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.sqlite"
            build_snapshot(root / "artifacts" / "phase-1", path)
            with TestClient(create_app(path)) as client:
                response = client.get("/api/evaluation")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(len(data["days"]), 31)
                self.assertEqual(len(data["rows"]), 744)
                self.assertEqual(data["summary"]["coverage"], 1)
                errors = [row["forecast_mw"] - row["actual_mw"] for row in data["rows"]]
                self.assertAlmostEqual(data["summary"]["mae_mw"], sum(abs(e) for e in errors) / 744)
                self.assertAlmostEqual(data["summary"]["bias_mw"], sum(errors) / 744)
                self.assertAlmostEqual(data["summary"]["signed_energy_error_mwh"], sum(errors))
                self.assertEqual(data["rows"][-1]["delivery_date"], "2026-02-01")


if __name__ == "__main__":
    unittest.main()
