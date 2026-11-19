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

    # The snapshot grows with every wave; assert internal consistency plus the
    # wave-3 sources' counts instead of pinning historical totals.
    assert len(normalized) > 0
    assert last["totals"]["raw"] == len(normalized)
    assert last["totals"]["normalized"] == len(normalized)
    assert deduped["total_normalized"] == len(normalized)
    assert 0 < deduped["unique_events"] <= len(normalized)
    assert deduped["duplicate_clusters"] == len(deduped["clusters"])

    same_source = [
        cluster
        for cluster in deduped["clusters"]
        if len({event["source"] for event in cluster["events"]}) == 1
    ]
    for cluster in same_source:
        assert cluster["pairs"]
        assert all(
            pair["kind"] == "ticket_slug"
            or (pair["kind"] in {"title_fuzzy", "title_core"} and pair["score"] == 100.0)
            for pair in cluster["pairs"]
        )
    counts = collections.Counter(event["source"] for event in normalized)
    # Counts follow the rolling agenda window; presence is the durable probe.
    assert counts["cualpinta"] > 0
    assert counts["elevenflow"] > 0
    assert counts["passline"] > 0


def test_no_cluster_merges_two_distinct_auditorium_titles():
    deduped = load("events_deduped.json")
    for cluster in deduped["clusters"]:
        auditorium = [
            event for event in cluster["events"] if event["source"] == "auditorium"
        ]
        titles = {build_site.normalize_key(event["title"]) for event in auditorium}
        # A festival prints many screenings under one prefix; two different
        # auditorium titles in the same cluster mean the prefix guard failed.
        assert len(titles) <= 1, (cluster["venue_name"], titles)


def _date_connected(members) -> bool:
    """True when every member shares a session with some other member."""
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


def test_wave3_sources_join_with_shared_sessions():
    deduped = load("events_deduped.json")
    wave3 = {"cualpinta", "elevenflow", "passline"}
    joined = [
        cluster
        for cluster in deduped["clusters"]
        if len({event["source"] for event in cluster["events"]} & wave3) >= 2
    ]
    assert joined, "wave-3 sources should join at least one show with another source"
    for cluster in joined:
        assert _date_connected(cluster["events"]), cluster["venue_name"]


def test_site_has_no_duplicate_triples_and_new_labels(tmp_path):
    stats = build_site.build(data_dir=DATA, out_dir=tmp_path, today=date(2026, 11, 18))
    # Counts depend on the snapshot; the duplicate-free invariant below is the
    # real regression guard.
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
    assert {"cualpinta", "elevenflow", "passline"} <= set(build_site.SOURCE_LABELS)
