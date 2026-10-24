"""Wave-3 acceptance probes: snapshot, festival guard, venue joins and site."""

import collections
import json
import re
from datetime import date
from pathlib import Path

import build_site
import run_pipeline
from collectors import cualpinta, elevenflow, passline

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_wave3_collectors_are_wired_and_contractual():
    wired = {name for name, _ in run_pipeline.MODULES}
    assert {"cualpinta", "elevenflow", "passline"} <= wired
    for module in (cualpinta, elevenflow, passline):
        assert callable(module.collect) and callable(module.normalize)
        assert module.USER_AGENT == "cartelera-mdp-pipeline/0.2 (local research)"
        assert module.normalize([]) == []


def test_wave3_labels_and_order():
    assert {"cualpinta", "elevenflow", "passline"} <= set(build_site.SOURCE_LABELS)
    assert all(
        source in build_site.SOURCE_ORDER
        for source in ("cualpinta", "elevenflow", "passline")
    )


def test_snapshot_totals_and_same_source_clusters():
    normalized = load("events_normalized.json")
    deduped = load("events_deduped.json")
    last = load("last_run.json")

    assert len(normalized) == 550
    assert deduped["total_normalized"] == 550
    assert deduped["unique_events"] == 318
    assert deduped["duplicate_clusters"] == 130
    assert deduped["events_in_clusters"] == 362
    assert last["totals"] == {"raw": 550, "normalized": 550, "unique": 318}

    same_source = [
        cluster
        for cluster in deduped["clusters"]
        if len({event["source"] for event in cluster["events"]}) == 1
    ]
    for cluster in same_source:
        assert cluster["pairs"]
        assert all(
            pair["kind"] == "ticket_slug"
            or (pair["kind"] == "title_fuzzy" and pair["score"] == 100.0)
            for pair in cluster["pairs"]
        )
    counts = collections.Counter(event["source"] for event in normalized)
    assert counts["cualpinta"] == 144
    assert counts["elevenflow"] == 53
    assert counts["passline"] == 4


def test_festival_films_stay_separate_and_join_their_twin():
    normalized = load("events_normalized.json")
    deduped = load("events_deduped.json")

    films = {
        event["title"]
        for event in normalized
        if event["source"] == "auditorium"
        and event["title"].startswith("41° Festival Internacional de Cine")
    }
    assert len(films) == 25

    festival_clusters = [
        cluster
        for cluster in deduped["clusters"]
        if any("Festival Internacional de Cine" in event["title"] for event in cluster["events"])
    ]
    # Each Eleven Flow screening joins exactly its own Auditorium film; the
    # shared "41 Festival..." prefix never merges distinct films.
    assert len(festival_clusters) == 9
    for cluster in festival_clusters:
        assert len(cluster["events"]) == 2
        assert {event["source"] for event in cluster["events"]} == {
            "auditorium",
            "elevenflow",
        }


def test_paren_la_mano_joins_tuentrada_and_cualpinta():
    deduped = load("events_deduped.json")
    matches = [
        cluster
        for cluster in deduped["clusters"]
        if any("paren la mano" in event["title"].lower() for event in cluster["events"])
    ]
    assert len(matches) == 1
    sources = {event["source"] for event in matches[0]["events"]}
    assert {"cualpinta", "tuentrada"} <= sources


def test_site_has_no_duplicate_triples_and_new_labels(tmp_path):
    stats = build_site.build(data_dir=DATA, out_dir=tmp_path, today=date(2026, 10, 24))
    assert stats["upcoming"] == 282
    assert stats["weekend"] == 38
    assert stats["venues"] == 73

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
        >= 25
    )
    assert {"cualpinta", "elevenflow", "passline"} <= set(build_site.SOURCE_LABELS)
