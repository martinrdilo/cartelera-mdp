#!/usr/bin/env python3
"""Pipeline runner: collect -> normalize -> enrich -> dedupe -> write outputs.

Failure policy: every source is collected before anything is written. If any
source fails, the runner writes data/raw/<source>.error.json, leaves
data/events_normalized.json and data/events_deduped.json untouched and exits
non-zero. On success it writes outputs atomically (tmp + rename) plus
data/last_run.json with the run summary.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from collectors import (
    auditorium,
    bombo,
    clubtri,
    colon,
    cualpinta,
    elevenflow,
    fanz,
    muchticket,
    municipal,
    passline,
    punto,
    quehacemos,
    ticketek,
    tuentrada,
    venti,
)
from lib.dedupe import cluster_events
from lib.venues import resolve

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODULES = (
    ("municipal", municipal),
    ("muchticket", muchticket),
    ("clubtri", clubtri),
    ("venti", venti),
    ("ticketek", ticketek),
    ("bombo", bombo),
    ("punto", punto),
    ("auditorium", auditorium),
    ("colon", colon),
    ("tuentrada", tuentrada),
    ("cualpinta", cualpinta),
    ("elevenflow", elevenflow),
    ("passline", passline),
    ("quehacemos", quehacemos),
    ("fanz", fanz),
)


def _write_json_atomic(path, payload):
    """Write JSON to a sibling tmp file, then rename over the target.

    A source can emit a lone surrogate (a broken JSON-LD escape) that cannot
    be encoded as UTF-8; replace it instead of failing the whole run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    text = text.encode("utf-8", "replace").decode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _collect_all(modules):
    """Run every collector concurrently; keep going so one failure does not hide others.

    Sources live on different domains and each collector keeps its own ~1 req/s
    pacing, so overlapping them cuts the wall time to the slowest source. The
    returned mapping preserves MODULES order for deterministic outputs.
    """
    modules = tuple(modules)
    raw_by_module = {}
    errors = {}
    if not modules:
        return raw_by_module, errors
    with ThreadPoolExecutor(max_workers=len(modules)) as pool:
        futures = {pool.submit(module.collect): name for name, module in modules}
        for future in as_completed(futures):
            name = futures[future]
            try:
                raw_by_module[name] = future.result()
            except Exception as exc:  # network, HTTP, decode or parse errors
                errors[name] = exc
    ordered = {name: raw_by_module[name] for name, _ in modules if name in raw_by_module}
    return ordered, errors


def _normalize_all(modules, raw_by_module):
    normalized_by_module = {}
    errors = {}
    for name, module in modules:
        try:
            normalized_by_module[name] = module.normalize(raw_by_module[name])
        except Exception as exc:
            errors[name] = exc
    return normalized_by_module, errors


def _write_errors(errors, raw_dir, failed_at):
    for name, exc in errors.items():
        _write_json_atomic(
            raw_dir / f"{name}.error.json",
            {
                "source": name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failed_at": failed_at,
            },
        )


def _venue_stats(events):
    resolved = sum(
        1 for event in events if resolve(event.venue_name) or resolve(event.venue_raw)
    )
    return {"resolved": resolved, "unknown": len(events) - resolved}


def run(modules=MODULES, data_dir=DATA_DIR):
    """Execute the pipeline end to end. Returns the process exit code."""
    started = time.monotonic()
    raw_dir = data_dir / "raw"

    raw_by_module, errors = _collect_all(modules)
    if not errors:
        normalized_by_module, errors = _normalize_all(modules, raw_by_module)
    if errors:
        _write_errors(errors, raw_dir, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        for name, exc in errors.items():
            print(f"[fail] {name}: {exc!r}", file=sys.stderr)
        print("[fail] outputs not overwritten; evidence in data/raw/*.error.json", file=sys.stderr)
        return 1

    raw_records = [record for records in raw_by_module.values() for record in records]
    events = [event for module_events in normalized_by_module.values() for event in module_events]
    enriched = muchticket.enrich_occurrences(events, raw_records)

    raw_by_source = {}
    for name, records in raw_by_module.items():
        for record in records:
            raw_by_source.setdefault(record.get("source", name), []).append(record)
    for source, records in raw_by_source.items():
        _write_json_atomic(raw_dir / f"{source}.json", records)

    clusters = cluster_events(events)
    clustered_events = sum(len(cluster["events"]) for cluster in clusters)
    unique_events = len(events) - sum(len(cluster["events"]) - 1 for cluster in clusters)
    duration = round(time.monotonic() - started, 1)

    occurrence_stats = {
        "multi_date_events": sum(1 for event in events if len(event.occurrences) > 1),
        "recurrence_unknown": sum(1 for event in events if event.recurrence_unknown),
        "multi_date_incomplete": sum(1 for event in events if event.multi_date_incomplete),
        "enriched_from_detail": enriched,
    }
    venue_stats = _venue_stats(events)

    _write_json_atomic(data_dir / "events_normalized.json", [event.to_dict() for event in events])
    _write_json_atomic(
        data_dir / "events_deduped.json",
        {
            "total_normalized": len(events),
            "unique_events": unique_events,
            "duplicate_clusters": len(clusters),
            "events_in_clusters": clustered_events,
            "clusters": clusters,
        },
    )
    _write_json_atomic(
        data_dir / "last_run.json",
        {
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_seconds": duration,
            "sources": {
                source: {
                    "raw": len(records),
                    "normalized": sum(1 for event in events if event.source == source),
                }
                for source, records in sorted(raw_by_source.items())
            },
            "totals": {"raw": len(raw_records), "normalized": len(events), "unique": unique_events},
            "duplicates": {"clusters": len(clusters), "events_in_clusters": clustered_events},
            "occurrences": occurrence_stats,
            "venues": venue_stats,
        },
    )

    print("== cartelera-mdp pipeline ==")
    for source in sorted(raw_by_source):
        raw_count = len(raw_by_source[source])
        normalized_count = sum(1 for event in events if event.source == source)
        print(f"{source:13} raw={raw_count:4} normalized={normalized_count:4}")
    print(f"{'TOTAL':13} normalized={len(events)} unique={unique_events}")
    print(f"duplicate clusters: {len(clusters)} (events involved: {clustered_events})")
    print(
        "multi-date events: {multi_date_events} (enriched from detail: {enriched_from_detail},"
        " incomplete: {multi_date_incomplete}, recurrence unknown: {recurrence_unknown})".format(**occurrence_stats)
    )
    print(f"venues resolved: {venue_stats['resolved']}/{len(events)}")
    print(f"duration: {duration}s")
    for cluster in clusters:
        title = cluster["events"][0]["title"]
        sources = sorted({event["source"] for event in cluster["events"]})
        kinds = sorted({pair["kind"] for pair in cluster["pairs"]})
        print(f"  - {title[:48]:50} sources={sources} evidence={kinds}")
    return 0


def main():
    return run()


if __name__ == "__main__":
    sys.exit(main())
