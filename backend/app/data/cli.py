"""Run via uv run python -m app.data.cli from backend/."""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, time
from pathlib import Path

from .client import ElexonClient, FetchError
from .models import DataError, iso, parse_timestamp
from .selection import coverage_report, select_day
from .snapshot import build_snapshot, digest, metadata

DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "january-2026.sqlite"


def atomic_write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(raw)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, value):
    atomic_write(path, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def fetch_sources(destination: Path, client=None):
    client = client or ElexonClient()
    destination.mkdir(parents=True, exist_ok=True)
    sources = []
    # Lookback for early January decisions; actual publication buffer after
    # the final delivery hour. These windows do not guarantee all future revisions.
    windows = [
        ("WINDFOR", "2025-12-31T00:00:00Z", "2026-02-01T00:00:00Z"),
        ("FUELHH", "2026-01-02T00:00:00Z", "2026-02-02T02:00:01Z"),
    ]
    for dataset, first, last in windows:
        start, stop = parse_timestamp(first), parse_timestamp(last)
        while start < stop:
            end = min(start + 86400, stop)
            print(f"Fetching {dataset} {iso(start)} to {iso(end)}", file=sys.stderr)
            raw, url, retrieved_at = client.fetch(dataset, start, end)
            checksum = digest(raw)
            filename = f"{dataset.lower()}-{checksum}.json"
            # Content-addressed raw evidence is immutable and reusable.
            path = destination / filename
            if not path.exists():
                atomic_write(path, raw)
            elif digest(path.read_bytes()) != checksum:
                raise DataError(f"Corrupt cached source: {filename}")
            sources.append({
                "dataset": dataset, "file": filename, "sha256": checksum,
                "url": url, "retrieved_at": retrieved_at,
                "window_start": iso(start), "window_end": iso(end),
            })
            start = end
    # A failed fetch never replaces the last complete acquisition manifest.
    atomic_json(destination / "sources.json", sources)
    return {"source_files": len(sources), "directory": str(destination)}


def cutoff_argument(value):
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use HH:MM in London time") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise argparse.ArgumentTypeError("Use HH:MM in London time")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Acquire public January data in daily chunks")
    fetch.add_argument("--output-dir", type=Path, required=True)
    build = commands.add_parser("build", help="Validate saved sources and atomically build SQLite")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    inspect = commands.add_parser("inspect", help="Report snapshot provenance and monthly coverage")
    inspect.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    inspect.add_argument("--cutoff", type=cutoff_argument, default=time(9))
    select = commands.add_parser("select", help="Show next-day forecast known at a decision cutoff")
    select.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    select.add_argument("--decision-date", type=date.fromisoformat, required=True)
    select.add_argument("--cutoff", type=cutoff_argument, default=time(9))
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            result = fetch_sources(args.output_dir)
        elif args.command == "build":
            result = build_snapshot(args.source_dir, args.snapshot)
        elif args.command == "inspect":
            result = {"metadata": metadata(args.snapshot), "coverage": coverage_report(args.snapshot, args.cutoff)}
        else:
            result = select_day(args.snapshot, args.decision_date, args.cutoff)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, FetchError, sqlite3.Error, KeyError) as exc:
        print(f"Data pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
