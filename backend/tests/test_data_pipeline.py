import io
import json
import math
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime, time
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from app.data.cli import fetch_sources
from app.data.client import ElexonClient, FetchError
from app.data.models import DataError, delivery_bounds, normalize, parse_timestamp
from app.data.selection import coverage_report, select_day
from app.data.snapshot import build_snapshot, connect_readonly, digest, metadata


def forecast(start="2026-01-02T00:00:00Z", published="2026-01-01T07:30:00Z", value=100):
    return dict(dataset="WINDFOR", startTime=start, publishTime=published, generation=value)


def actual(start="2026-01-02T00:00:00Z", published="2026-01-02T00:30:00Z", value=80):
    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return dict(dataset="FUELHH", startTime=start, publishTime=published,
                generation=value, fuelType="WIND", settlementDate=dt.date().isoformat(),
                settlementPeriod=dt.hour * 2 + dt.minute // 30 + 1)


def write_sources(directory, forecasts, actuals):
    sources = []
    for dataset, rows in (("WINDFOR", forecasts), ("FUELHH", actuals)):
        raw = json.dumps(rows).encode()
        filename = dataset.lower() + ".json"
        (directory / filename).write_bytes(raw)
        sources.append(dict(dataset=dataset, file=filename, sha256=digest(raw),
                            url="https://data.elexon.co.uk/test", retrieved_at=None))
    (directory / "sources.json").write_text(json.dumps(sources), encoding="utf-8")


class NormalizationTests(unittest.TestCase):
    def test_offsets_normalize_to_same_instant(self):
        self.assertEqual(parse_timestamp("2026-01-01T09:00:00Z"),
                         parse_timestamp("2026-01-01T10:00:00+01:00"))

    def test_naive_and_fractional_timestamps_rejected(self):
        for stamp in ("2026-01-01T09:00:00", "2026-01-01", "2026-01-01T09:00:00.1Z"):
            with self.subTest(stamp=stamp), self.assertRaises(DataError):
                parse_timestamp(stamp)

    def test_zero_valid_but_invalid_values_rejected(self):
        self.assertEqual(normalize(forecast(value=0), "WINDFOR").generation, 0)
        for value in (None, True, "10", -1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(DataError):
                normalize(forecast(value=value), "WINDFOR")

    def test_actual_fuel_filter_and_settlement_validation(self):
        row = actual()
        row["fuelType"] = "CCGT"
        self.assertIsNone(normalize(row, "FUELHH"))
        for field, value in (("settlementPeriod", 2), ("settlementDate", "2026-01-01")):
            row = actual()
            row[field] = value
            with self.assertRaises(DataError):
                normalize(row, "FUELHH")

    def test_off_grid_records_rejected(self):
        with self.assertRaises(DataError):
            normalize(forecast(start="2026-01-02T00:30:00Z"), "WINDFOR")

    def test_delivery_bounds_handle_dst(self):
        for day, hours in ((date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 1, 2), 24)):
            start, end = delivery_bounds(day)
            self.assertEqual((end - start) / 3600, hours)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.snapshot = self.root / "snapshot.sqlite"
        self.forecasts = [forecast()]
        self.actuals = [actual(), actual("2026-01-02T00:30:00Z", "2026-01-02T01:00:00Z", 120)]

    def build(self):
        write_sources(self.root, self.forecasts, self.actuals)
        return build_snapshot(self.root, self.snapshot)

    def test_idempotent_snapshot_and_readonly_access(self):
        first = self.build()
        first_bytes = self.snapshot.read_bytes()
        second = self.build()
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(first_bytes, self.snapshot.read_bytes())
        connection = connect_readonly(self.snapshot)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM records")
        finally:
            connection.close()

    def test_duplicates_collapse_but_conflicts_preserve_old_snapshot(self):
        self.forecasts.append(forecast())
        manifest = self.build()
        self.assertEqual(manifest["counts"]["identical_duplicates"], 1)
        original = self.snapshot.read_bytes()
        self.forecasts.append(forecast(value=900))
        with self.assertRaisesRegex(DataError, "Conflicting"):
            self.build()
        self.assertEqual(self.snapshot.read_bytes(), original)

    def test_checksum_failure_preserves_old_snapshot(self):
        self.build()
        original = self.snapshot.read_bytes()
        (self.root / "windfor.json").write_text("[]")
        with self.assertRaisesRegex(DataError, "checksum"):
            build_snapshot(self.root, self.snapshot)
        self.assertEqual(self.snapshot.read_bytes(), original)

    def test_hindsight_excluded_and_cutoff_inclusive(self):
        self.forecasts += [forecast(published="2026-01-01T09:00:00Z", value=200),
                           forecast(published="2026-01-01T09:00:01Z", value=900)]
        self.build()
        result = select_day(self.snapshot, date(2026, 1, 1))
        self.assertEqual(result["rows"][0]["forecast_mw"], 200)
        self.assertEqual(result["rows"][0]["forecast_age_hours"], 0)
        earlier = select_day(self.snapshot, date(2026, 1, 1), time(8))
        self.assertEqual(earlier["rows"][0]["forecast_mw"], 100)

    def test_actual_average_and_latest_revision_preserved(self):
        self.actuals.append(actual(published="2026-01-03T00:00:00Z", value=180))
        manifest = self.build()
        row = select_day(self.snapshot, date(2026, 1, 1))["rows"][0]
        self.assertEqual(row["actual_mw"], 150)
        self.assertEqual(manifest["counts"]["actual_records"], 3)
        self.assertEqual(row["actual_publish_times"][0], "2026-01-03T00:00:00Z")

    def test_missing_half_hour_is_not_filled_or_zero(self):
        self.actuals.pop()
        self.build()
        selected = select_day(self.snapshot, date(2026, 1, 1))
        self.assertIsNone(selected["rows"][0]["actual_mw"])
        self.assertEqual(selected["coverage"], 0)
        self.assertEqual(len(selected["rows"]), 24)
        self.assertIn("missing_actual_half_hour", selected["rows"][0]["quality_flags"])

    def test_zero_is_paired_and_no_forecast_stays_missing(self):
        self.forecasts = [forecast(value=0)]
        self.build()
        selected = select_day(self.snapshot, date(2026, 1, 1))
        self.assertTrue(selected["rows"][0]["paired"])
        self.assertIsNone(selected["rows"][1]["forecast_mw"])
        self.assertEqual(selected["paired_hours"], 1)

    def test_mixed_publication_fallback_is_visible(self):
        self.forecasts.append(forecast("2026-01-02T01:00:00Z", "2026-01-01T08:30:00Z"))
        self.build()
        selected = select_day(self.snapshot, date(2026, 1, 1))
        self.assertTrue(selected["mixed_forecast_vintages"])
        self.assertIn("older_publication_fallback", selected["rows"][0]["quality_flags"])

    def test_month_boundary_and_scope(self):
        self.build()
        selected = select_day(self.snapshot, date(2026, 1, 31))
        self.assertEqual(selected["delivery_date"], "2026-02-01")
        self.assertEqual(selected["rows"][-1]["end_time"], "2026-02-02T00:00:00Z")
        with self.assertRaises(ValueError):
            select_day(self.snapshot, date(2026, 2, 1))

    def test_publication_window_is_half_open(self):
        self.forecasts.append(forecast(published="2026-01-02T00:00:00Z"))
        write_sources(self.root, self.forecasts, self.actuals)
        path = self.root / "sources.json"
        sources = json.loads(path.read_text())
        sources[0].update(window_start="2026-01-01T00:00:00Z", window_end="2026-01-02T00:00:00Z")
        path.write_text(json.dumps(sources))
        manifest = build_snapshot(self.root, self.snapshot)
        self.assertEqual(manifest["counts"]["forecast_records"], 1)
        self.assertEqual(manifest["counts"]["filtered_publication_boundary"], 1)


class ClientTests(unittest.TestCase):
    def test_retry_after_and_filter_parameters(self):
        error = HTTPError("https://example.test", 429, "busy", {"Retry-After": "2"}, None)
        opener = Mock(side_effect=[error, io.BytesIO(b"[]")])
        sleep = Mock()
        client = ElexonClient(opener=opener, sleep=sleep)
        start, end = parse_timestamp("2026-01-02T00:00:00Z"), parse_timestamp("2026-01-03T00:00:00Z")
        raw, url, _ = client.fetch("FUELHH", start, end)
        sleep.assert_called_once_with(2)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["fuelType"], ["WIND"])
        self.assertEqual(query["publishDateTimeFrom"], ["2026-01-01T23:59:59Z"])
        self.assertEqual(raw, b"[]")

    def test_http_date_retry_after(self):
        client = ElexonClient(now=lambda: datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual(client._delay(0, "Thu, 01 Jan 2026 00:00:05 GMT"), 5)
        with self.assertRaises(FetchError):
            client._delay(0, "120")

    def test_network_retries_are_bounded(self):
        opener = Mock(side_effect=URLError("offline"))
        sleep = Mock()
        with self.assertRaises(FetchError):
            ElexonClient(opener=opener, sleep=sleep, attempts=3).fetch("WINDFOR", 1, 2)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_truncated_response_is_retried(self):
        opener = Mock(side_effect=[IncompleteRead(b"[", 100), io.BytesIO(b"[]")])
        client = ElexonClient(opener=opener, sleep=Mock())
        self.assertEqual(client.fetch("WINDFOR", 1, 2)[0], b"[]")

    def test_malformed_json_is_rejected(self):
        client = ElexonClient(opener=Mock(return_value=io.BytesIO(b"<html>error</html>")))
        with self.assertRaises(DataError):
            client.fetch("WINDFOR", 1, 2)

    def test_nonretryable_status_and_invalid_payload_fail_immediately(self):
        for response in (HTTPError("https://example.test", 400, "bad", {}, None), io.BytesIO(b'{"data":[]}')):
            opener = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
            sleep = Mock()
            with self.assertRaises((FetchError, DataError)):
                ElexonClient(opener=opener, sleep=sleep).fetch("WINDFOR", 1, 2)
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_failed_acquisition_does_not_publish_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "sources.json").write_text('["old manifest"]')
            client = Mock()
            client.fetch.side_effect = FetchError("offline")
            with self.assertRaises(FetchError):
                fetch_sources(path, client)
            self.assertEqual((path / "sources.json").read_text(), '["old manifest"]')


class JanuaryEvidenceTests(unittest.TestCase):
    def test_real_evidence_full_month_and_reproducibility(self):
        evidence = Path(__file__).resolve().parents[2] / "artifacts" / "phase-1"
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "january.sqlite"
            manifest = build_snapshot(evidence, snapshot)
            self.assertEqual(manifest["counts"]["forecast_records"], 18688)
            self.assertEqual(manifest["counts"]["actual_records"], 1493)
            report = coverage_report(snapshot)
            self.assertEqual(report["expected_hours"], 744)
            self.assertEqual(report["paired_hours"], 744)
            self.assertEqual(report["coverage"], 1)
            for day in report["days"]:
                selected = select_day(snapshot, date.fromisoformat(day["decision_date"]))
                for row in selected["rows"]:
                    self.assertLessEqual(row["forecast_publish_time"], selected["cutoff"])
            self.assertEqual(metadata(snapshot)["snapshot_id"], manifest["snapshot_id"])
            rebuilt = build_snapshot(evidence, snapshot)
            self.assertEqual(rebuilt["snapshot_id"], manifest["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
