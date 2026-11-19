"""Wave-2 acceptance probes: committed snapshot, site and source contracts."""

import collections
import json
import re
from datetime import date
from pathlib import Path

import build_site
import run_pipeline
from collectors import auditorium, colon, tuentrada
from lib.venues import resolve

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_wave2_collectors_are_wired_and_contractual():
    wired = {name for name, _ in run_pipeline.MODULES}
    assert {"auditorium", "colon", "tuentrada"} <= wired
    for module in (auditorium, colon, tuentrada):
        assert callable(module.collect) and callable(module.normalize)
        assert module.USER_AGENT == "cartelera-mdp-pipeline/0.2 (local research)"
        assert module.normalize([]) == []


def test_snapshot_totals_and_same_source_clusters():
    normalized = load("events_normalized.json")
    deduped = load("events_deduped.json")
    last = load("last_run.json")
    # The snapshot grows with every wave; assert internal consistency and the
    # wave-2 sources' presence instead of pinning historical totals.
    assert len(normalized) > 0
    assert last["totals"]["normalized"] == len(normalized)
    assert deduped["total_normalized"] == len(normalized)
    assert 0 < deduped["unique_events"] <= len(normalized)
    same_source = [
        cluster
        for cluster in deduped["clusters"]
        if len({event["source"] for event in cluster["events"]}) == 1
    ]
    # A same-source cluster is only legitimate when the members share a ticket
    # slug or an exact normalized title (two listings of one show), never from
    # fuzzy/prefix similarity (the festival false-positive class).
    for cluster in same_source:
        assert cluster["pairs"]
        assert all(
            pair["kind"] == "ticket_slug"
            or (pair["kind"] in {"title_fuzzy", "title_core"} and pair["score"] == 100.0)
            for pair in cluster["pairs"]
        )
    counts = collections.Counter(event["source"] for event in normalized)
    # Counts depend on the rolling agenda window; presence is the durable probe.
    assert counts["auditorium"] > 0
    assert counts["colon"] > 0
    assert counts["tuentrada"] > 0


def _date_connected(members) -> bool:
    """True when every member shares a session with some other member.

    Dedupe is transitive (A~B, B~C), so a whole cluster need not share one
    global date; each member must still hang off another by date.
    """
    dates = [
        set(event["occurrences"]) or ({event["date_start"]} if event["date_start"] else set())
        for event in members
    ]
    seen = {0}
    stack = [0]
    while stack:
        current = stack.pop()
        for index, other in enumerate(dates):
            if index not in seen and dates[current] & other:
                seen.add(index)
                stack.append(index)
    return len(seen) == len(dates)


def test_cross_source_joins_are_real():
    normalized = load("events_normalized.json")
    deduped = load("events_deduped.json")

    multi_source = [
        cluster
        for cluster in deduped["clusters"]
        if len({event["source"] for event in cluster["events"]}) >= 2
    ]
    assert multi_source, "dedupe should join at least one show across sources"
    # A cross-source join is only legitimate when the members hang together by
    # session date.
    for cluster in multi_source:
        assert _date_connected(cluster["events"]), cluster["venue_name"]
    # Wave 2 must still contribute at least one joined show.
    assert any(
        "auditorium" in {event["source"] for event in cluster["events"]}
        for cluster in multi_source
    )
    assert len(normalized) > 0


def test_wave2_venues_resolve():
    assert resolve("Sala Astor Piazzolla")[0] == "teatro-auditorium"
    assert resolve("Sala Jorge Laureti - Puerto")[0] == "auditorium-laureti-puerto"
    assert resolve("Polideportivo Mar De Plata")[0] == "polideportivo-islas-malvinas"
    assert resolve("Teatro Enrique Carreras")[0] == "teatro-enrique-carreras"


def test_site_has_no_duplicate_triples(tmp_path):
    stats = build_site.build(data_dir=DATA, out_dir=tmp_path, today=date(2026, 10, 23))
    assert stats["upcoming"] > 0
    assert 0 < stats["weekend"] <= stats["upcoming"]
    assert stats["venues"] > 0
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads(
        re.search(
            r'<script id="events-data" type="application/json">(.*?)</script>',
            html,
            re.S,
        ).group(1)
    )
    events = payload["events"]
    triples = [
        (event["venue_id"], build_site.normalize_key(event["title"]), day)
        for event in events
        for day in event["dates"]
    ]
    duplicates = {
        triple: count for triple, count in collections.Counter(triples).items() if count > 1
    }
    assert duplicates == {}
    assert {"auditorium", "colon", "tuentrada"} <= set(build_site.SOURCE_LABELS)
    assert all(
        source in build_site.SOURCE_ORDER for source in ("auditorium", "colon", "tuentrada")
    )
