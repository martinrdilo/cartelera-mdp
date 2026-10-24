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
            or (pair["kind"] == "title_fuzzy" and pair["score"] == 100.0)
            for pair in cluster["pairs"]
        )
    counts = collections.Counter(event["source"] for event in normalized)
    assert counts["auditorium"] >= 37
    assert counts["colon"] >= 28
    assert counts["tuentrada"] >= 1


def test_festival_and_cross_source_joins():
    normalized = load("events_normalized.json")
    deduped = load("events_deduped.json")
    festival = {
        event["title"]
        for event in normalized
        if event["source"] == "auditorium"
        and event["title"].startswith("41° Festival Internacional de Cine")
    }
    assert len(festival) >= 23

    def sources_for(needle):
        return [
            {event["source"] for event in cluster["events"]}
            for cluster in deduped["clusters"]
            if any(needle.lower() in event["title"].lower() for event in cluster["events"])
        ]

    assert any({"auditorium", "municipal"} <= sources for sources in sources_for("Todas en ella"))
    assert any({"auditorium", "punto"} <= sources for sources in sources_for("Amniótika"))
    # The Colón+municipal join ("Banda Sinfónica Municipal") depends on a
    # specific October date; once that date passes it is no longer in the
    # snapshot, so the stable Auditorium joins above are the durable probes.


def test_wave2_venues_resolve():
    assert resolve("Sala Astor Piazzolla")[0] == "teatro-auditorium"
    assert resolve("Sala Jorge Laureti - Puerto")[0] == "auditorium-laureti-puerto"
    assert resolve("Polideportivo Mar De Plata")[0] == "polideportivo-islas-malvinas"
    assert resolve("Teatro Enrique Carreras")[0] == "teatro-enrique-carreras"


def test_site_has_no_duplicate_triples_and_keeps_festival(tmp_path):
    stats = build_site.build(data_dir=DATA, out_dir=tmp_path, today=date(2026, 10, 23))
    assert stats["upcoming"] >= 225
    assert stats["weekend"] >= 36
    assert stats["venues"] >= 42
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
    assert (
        sum(
            1
            for event in events
            if event["title"].startswith("41° Festival Internacional de Cine")
        )
        >= 23
    )
    assert {"auditorium", "colon", "tuentrada"} <= set(build_site.SOURCE_LABELS)
    assert all(
        source in build_site.SOURCE_ORDER for source in ("auditorium", "colon", "tuentrada")
    )
