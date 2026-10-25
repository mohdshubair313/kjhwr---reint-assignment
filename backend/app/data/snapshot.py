"""Validate source evidence and atomically publish an indexed SQLite snapshot."""

import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from .models import DataError, POLICY_VERSION, SCHEMA_VERSION, normalize, parse_timestamp


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_manifest(directory: Path) -> list[dict]:
    manifest = directory / "sources.json"
    if manifest.exists():
        sources = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(sources, list) or not sources:
            raise DataError("sources.json must be a nonempty source list")
        return sources
    # Explicit compatibility for the retained Phase 1 evidence. Its exact
    # acquisition instant was not recorded; never invent that timestamp.
    requests = json.loads((directory / "requests.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((directory / "audit.json").read_text(encoding="utf-8-sig"))
    return [{
        "dataset": name.upper(), "file": f"{name}.json", "url": requests[name],
        "sha256": audit["files"][name]["sha256"], "retrieved_at": None,
        "retrieved_date": "2026-10-25", "provenance": "phase-1-import",
    } for name in ("windfor", "fuelhh")]


def load_sources(directory: Path) -> tuple[list, list[dict], dict]:
    records = {}
    sources = []
    counts = Counter()
    for item in source_manifest(directory):
        dataset = item.get("dataset")
        if dataset not in {"WINDFOR", "FUELHH"}:
            raise DataError("Source dataset must be WINDFOR or FUELHH")
        path = (directory / item["file"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise DataError("Source file must be inside its evidence directory")
        raw = path.read_bytes()
        checksum = digest(raw)
        if checksum != item.get("sha256"):
            raise DataError(f"Source checksum mismatch: {path.name}")
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise DataError(f"Expected a JSON array in {path.name}")
        start = parse_timestamp(item["window_start"]) if "window_start" in item else None
        end = parse_timestamp(item["window_end"]) if "window_end" in item else None
        if (start is None) != (end is None) or (start is not None and start >= end):
            raise DataError("Source publication window must have increasing start and end")
        for index, row in enumerate(rows):
            counts["source_rows"] += 1
            try:
                record = normalize(row, dataset)
            except DataError as exc:
                raise DataError(f"{path.name} row {index}: {exc}") from exc
            if record is None:
                counts["filtered_non_wind"] += 1
                continue
            if start is not None and not start <= record.published < end:
                counts["filtered_publication_boundary"] += 1
                continue
            previous = records.get(record.key)
            if previous is not None:
                if previous != record:
                    raise DataError(f"Conflicting values for {record.key}; snapshot not replaced")
                counts["identical_duplicates"] += 1
                continue
            records[record.key] = record
        sources.append(dict(item, sha256=checksum, rows=len(rows)))
    if {r.dataset for r in records.values()} != {"WINDFOR", "FUELHH"}:
        raise DataError("Snapshot requires nonempty forecast and WIND actual datasets")
    counts["forecast_records"] = sum(r.dataset == "WINDFOR" for r in records.values())
    counts["actual_records"] = sum(r.dataset == "FUELHH" for r in records.values())
    return sorted(records.values()), sorted(sources, key=canonical), dict(sorted(counts.items()))


def connect_readonly(path: Path) -> sqlite3.Connection:
    # FastAPI may resume one synchronous request on a different pool thread.
    # Each request owns its connection; it is never shared across requests.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise DataError(f"Unsupported snapshot schema version: {version}")
    except Exception:
        connection.close()
        raise
    return connection


def metadata(path: Path) -> dict:
    with closing(connect_readonly(path)) as connection:
        return json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])


def build_snapshot(directory: Path, destination: Path) -> dict:
    records, sources, counts = load_sources(directory)
    normalized_hash = digest(canonical([
        [r.dataset, r.start, r.published, r.generation] for r in records
    ]).encode())
    manifest = {
        "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
        "normalized_sha256": normalized_hash, "sources": sources, "counts": counts,
        "decision_start": "2026-01-01", "decision_end": "2026-01-31",
        "timezone": "Europe/London", "default_cutoff": "09:00", "unit": "MW",
        "resolution_minutes": 60,
        "actual_policy": "latest publication per half-hour within this retrospective snapshot",
        "forecast_policy": "latest publication per delivery hour at or before decision cutoff",
        "interval_assumption": "WINDFOR startTime labels coming hour's mean MW",
    }
    manifest["snapshot_id"] = digest(canonical(manifest).encode())
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=destination.stem + "-", suffix=".tmp", dir=destination.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            with connection:
                connection.executescript("""
                    CREATE TABLE records (
                        dataset TEXT NOT NULL CHECK(dataset IN ('WINDFOR','FUELHH')),
                        start INTEGER NOT NULL,
                        published INTEGER NOT NULL,
                        generation REAL NOT NULL CHECK(generation >= 0),
                        PRIMARY KEY(dataset, start, published)
                    ) WITHOUT ROWID;
                    CREATE INDEX records_publication ON records(dataset, published, start);
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                connection.executemany("INSERT INTO records VALUES (?,?,?,?)", [
                    (r.dataset, r.start, r.published, r.generation) for r in records
                ])
                connection.execute("INSERT INTO metadata VALUES ('manifest', ?)", (canonical(manifest),))
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DataError("SQLite integrity check failed")
        # Atomic rename: readers see the old complete file or the new complete
        # file. A Windows sharing violation also leaves the original intact.
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest
