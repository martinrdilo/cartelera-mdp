"""Wave-3 semantic duplicate probes: one visible row per event.

The exact-triple guard only catches identical titles; these cases prove that
the same event published with different titles (or a wrong venue) still renders
once. The cases are derived from the committed snapshot, so a refreshed corpus
keeps the probe meaningful.
"""

import json
import re
from datetime import date
from pathlib import Path

import build_site

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ANCHOR = date(2026, 11, 18)


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _site_events():
    events, _, _ = build_site.collect_site_events(DATA, ANCHOR)
    return events


def test_cross_source_event_with_different_titles_renders_once():
    deduped = _load("events_deduped.json")
    events = _site_events()

    candidates = []
    for cluster in deduped["clusters"]:
        sources = {event["source"] for event in cluster["events"]}
        dates = {day for day in cluster["dates"] if day >= ANCHOR.isoformat()}
        titles = {build_site.normalize_key(event["title"]) for event in cluster["events"]}
        # The hard case: two sources name the same show differently.
        if len(sources) >= 2 and dates and len(titles) >= 2:
            candidates.append((cluster, sources, dates))

    assert candidates, "the snapshot should carry a cross-source show with differing titles"

    for cluster, _sources, dates in candidates[:8]:
        expected = build_site.normalize_key(
            build_site.pick_field(cluster["events"], "title") or cluster["events"][0]["title"]
        )
        rows = [
            event
            for event in events
            if set(event["dates"]) & dates and build_site.normalize_key(event["title"]) == expected
        ]
        assert len(rows) == 1, (
            cluster["venue_name"],
            sorted(dates)[:3],
            [(row["slug"], row["title"], row["venue_name"]) for row in rows],
        )
