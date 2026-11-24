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
from lib.venues import venue_key

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


def test_cross_venue_slug_join_lands_on_one_shared_night():
    """One ticket page joins one night, never two, across venue spellings.

    The slug join exists because a source can publish the event name in the
    venue field (Ticketek 22/01: "Bendu Arena" against "El Plan de la
    Mariposa"). Sellers reuse the same page for every function of a show
    (Club TRI's Cumbia Grande page served 22/11 and 19/12), so a slug pair must
    still share a session.
    """
    deduped = _load("events_deduped.json")
    by_ref = {
        f"{event['source']}:{event['source_event_id']}": event
        for cluster in deduped["clusters"]
        for event in cluster["events"]
    }

    cross_venue = []
    for cluster in deduped["clusters"]:
        for pair in cluster["pairs"]:
            if pair["kind"] != "ticket_slug":
                continue
            left = by_ref.get(pair["a"])
            right = by_ref.get(pair["b"])
            if left is None or right is None:
                continue
            left_venue = venue_key(left["venue_name"] or left["venue_raw"])
            right_venue = venue_key(right["venue_name"] or right["venue_raw"])
            if left_venue != right_venue:
                cross_venue.append((pair["slug"], left, right))

    assert cross_venue, "the slug join should cross venue spellings at least once"

    for slug, left, right in cross_venue:
        left_dates = set(left["occurrences"] or [])
        right_dates = set(right["occurrences"] or [])
        if left_dates and right_dates:
            assert left_dates & right_dates, (
                slug,
                left["title"],
                sorted(left_dates)[:3],
                right["title"],
                sorted(right_dates)[:3],
            )
