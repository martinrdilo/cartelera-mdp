#!/usr/bin/env python3
"""Spike runner: collect -> normalize -> dedupe -> write data files + summary."""

import json
import sys
from pathlib import Path

from collectors import clubtri, muchticket, municipal
from lib.dedupe import cluster_events

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MODULES = (("municipal", municipal), ("muchticket", muchticket), ("clubtri", clubtri))


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    raw_by_source = {}
    events = []
    for name, module in MODULES:
        try:
            raw = module.collect()
        except Exception as exc:
            print(f"[warn] {name}: collect failed: {exc!r}")
            raw = []
        try:
            normalized = module.normalize(raw)
        except Exception as exc:
            print(f"[warn] {name}: normalize failed: {exc!r}")
            normalized = []
        for record in raw:
            raw_by_source.setdefault(record.get("source", name), []).append(record)
        events.extend(normalized)

    for source, records in raw_by_source.items():
        _write_json(RAW_DIR / f"{source}.json", records)
    _write_json(DATA_DIR / "events_normalized.json", [event.to_dict() for event in events])

    clusters = cluster_events(events)
    clustered_events = sum(len(cluster["events"]) for cluster in clusters)
    unique_events = len(events) - sum(len(cluster["events"]) - 1 for cluster in clusters)
    _write_json(
        DATA_DIR / "events_deduped.json",
        {
            "total_normalized": len(events),
            "unique_events": unique_events,
            "duplicate_clusters": len(clusters),
            "events_in_clusters": clustered_events,
            "clusters": clusters,
        },
    )

    print("== cartelera-mdp spike ==")
    for source in sorted(raw_by_source):
        raw_count = len(raw_by_source[source])
        normalized_count = sum(1 for event in events if event.source == source)
        print(f"{source:13} raw={raw_count:4} normalized={normalized_count:4}")
    print(f"{'TOTAL':13} normalized={len(events)} unique={unique_events}")
    print(f"duplicate clusters: {len(clusters)} (events involved: {clustered_events})")
    for cluster in clusters:
        title = cluster["events"][0]["title"]
        sources = sorted({event["source"] for event in cluster["events"]})
        kinds = sorted({pair["kind"] for pair in cluster["pairs"]})
        print(f"  - {title[:48]:50} sources={sources} evidence={kinds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
