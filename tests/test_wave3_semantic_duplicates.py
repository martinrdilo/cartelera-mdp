"""Wave-3 semantic duplicate probes: one visible row per event.

The exact-triple guard only catches identical titles; these cases prove that
the same event published with different titles (or a wrong venue) still renders
once.
"""

import json
import re
from datetime import date
from pathlib import Path

import build_site

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _site_events(tmp_path):
    build_site.build(data_dir=DATA, out_dir=tmp_path, today=date(2026, 10, 24))
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads(
        re.search(
            r'<script id="events-data" type="application/json">(.*?)</script>',
            text,
            re.S,
        ).group(1)
    )
    return payload["events"]


def test_same_event_renders_once(tmp_path):
    normalized = json.loads((DATA / "events_normalized.json").read_text(encoding="utf-8"))
    events = _site_events(tmp_path)

    for needle in (
        "Patricia Lucas",
        "Amniótika",
        "Hairspray",
        "Dante Spinetta",
    ):
        days = {
            event["date_start"]
            for event in normalized
            if event["date_start"] and needle.casefold() in event["title"].casefold()
        }
        assert len(days) == 1, (needle, days)
        day = days.pop()
        rows = [
            event
            for event in events
            if day in event["dates"] and needle.casefold() in event["title"].casefold()
        ]
        assert len(rows) == 1, (needle, day, [(row["slug"], row["venue_id"]) for row in rows])
