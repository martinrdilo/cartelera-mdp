"""Tests for the offline data verifier (verify/)."""

from __future__ import annotations

import json

import pytest

from lib import dedupe
from lib.schema import Event
from verify import cli, core, duplicates, rebuild, snapshot

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
EVENT_FIELDS = tuple(Event.__dataclass_fields__)


def make_event(**overrides):
    base = {
        "source": "ticketek",
        "source_event_id": "show-1",
        "title": "Hairspray",
        "venue_name": "Teatro Tronador",
        "venue_raw": "Teatro Tronador, Santiago del Estero 1746",
        "date_start": "2026-11-20",
        "date_end": None,
        "occurrences": ["2026-11-20"],
        "recurrence_unknown": False,
        "multi_date_incomplete": False,
        "time": "21:00",
        "is_free": False,
        "price_text": "Desde $20000",
        "price_min": 20000.0,
        "currency": "ARS",
        "ticket_url": "https://www.ticketek.com.ar/hairspray/teatro-tronador",
        "seller": "Ticketek",
        "image_url": None,
        "city": "Mar del Plata",
        "raw_url": "https://www.ticketek.com.ar/hairspray",
        "collected_at": "2026-11-18T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def make_deduped(events, clusters=None):
    clusters = clusters or []
    in_clusters = sum(len(cluster["events"]) for cluster in clusters)
    unique = len(events) - sum(len(cluster["events"]) - 1 for cluster in clusters)
    return {
        "total_normalized": len(events),
        "unique_events": unique,
        "duplicate_clusters": len(clusters),
        "events_in_clusters": in_clusters,
        "clusters": clusters,
    }


def make_cluster(*events, pairs=None):
    return {
        "venue": "teatro-tronador",
        "venue_name": "Teatro Tronador",
        "dates": sorted({day for event in events for day in event["occurrences"]}),
        "events": list(events),
        "pairs": pairs or [],
    }


def refs(findings, severity=None):
    return [finding.check for finding in findings if severity in (None, finding.severity)]


def test_clean_snapshot_has_no_errors():
    event = make_event()
    findings = snapshot.run_snapshot([event], make_deduped([event]))
    assert refs(findings, "error") == []


def test_row_without_the_optional_venue_url_is_still_clean():
    # Rows written before the field existed must keep passing the schema check.
    old_row = make_event()
    assert "venue_url" not in old_row
    findings = snapshot.check_schema([old_row], known_sources={"ticketek"})
    assert "schema.missing_field" not in refs(findings, "error")
    assert refs(findings, "error") == []


def test_present_venue_url_is_still_type_checked():
    broken = make_event(source_event_id="show-2", venue_url=42)
    findings = snapshot.check_schema([broken], known_sources={"ticketek"})
    assert "schema.bad_type" in refs(findings, "error")
    assert "schema.missing_field" not in refs(findings, "error")


def test_schema_missing_field_and_bad_types_are_errors():
    missing = make_event()
    del missing["price_min"]
    broken = make_event(source_event_id="show-2", time="9 PM", date_start="20/11/2026")
    findings = snapshot.check_schema([missing, broken], known_sources={"ticketek"})
    assert "schema.missing_field" in refs(findings, "error")
    assert "schema.bad_time" in refs(findings, "error")
    assert "schema.bad_date" in refs(findings, "error")


def test_empty_required_title_is_its_own_finding():
    untitled = make_event(source_event_id="show-empty", title="")
    findings = snapshot.check_schema([untitled], known_sources={"ticketek"})
    assert "schema.empty_required" in refs(findings, "error")
    assert "schema.bad_type" not in refs(findings, "error")


def test_empty_venue_is_flagged():
    homeless = make_event(source_event_id="show-nowhere", venue_name="", venue_raw="")
    findings = snapshot.check_schema([homeless], known_sources={"ticketek"})
    assert "schema.empty_venue" in refs(findings, "warning")


def test_unknown_source_is_an_error():
    findings = snapshot.check_schema([make_event(source="mystery")], known_sources={"ticketek"})
    assert "schema.unknown_source" in refs(findings, "error")


def test_duplicate_source_event_id_is_an_error():
    events = [make_event(), make_event(title="Hairspray 2")]
    findings = snapshot.check_schema(events, known_sources={"ticketek"})
    assert "id.duplicate_source_event_id" in refs(findings, "error")


def test_occurrence_outside_range_and_start_missing():
    outside = make_event(occurrences=["2026-11-20", "2027-01-05"], date_end="2026-12-01")
    missing_start = make_event(source_event_id="s2", occurrences=["2026-11-21"])
    findings = snapshot.check_occurrences([outside, missing_start])
    assert "occurrence.out_of_range" in refs(findings, "error")
    assert "occurrence.start_not_in_occurrences" in refs(findings, "error")


def test_empty_occurrences_requires_a_reason():
    unexplained = make_event(occurrences=[], date_start=None)
    explained = make_event(
        source_event_id="s2", occurrences=[], date_start=None, recurrence_unknown=True
    )
    findings = snapshot.check_occurrences([unexplained, explained])
    assert len([f for f in findings if f.check == "occurrence.empty_unexplained"]) == 1


def test_price_contradictions_are_errors():
    free_with_price = make_event(is_free=True, price_min=15000.0)
    paid_zero = make_event(source_event_id="s2", is_free=False, price_min=0.0)
    no_currency = make_event(source_event_id="s3", currency=None)
    findings = snapshot.check_price([free_with_price, paid_zero, no_currency])
    assert "price.free_with_positive_price" in refs(findings, "error")
    assert "price.paid_zero" in refs(findings, "error")
    assert "price.currency_missing" in refs(findings, "error")


def test_link_scheme_and_seller_mismatch():
    bad_scheme = make_event(ticket_url="ticketek.com.ar/hairspray")
    mismatch = make_event(source_event_id="s2", seller="Articket")
    unknown_host = make_event(source_event_id="s3", ticket_url="https://example.com/entradas")
    findings = snapshot.check_links([bad_scheme, mismatch, unknown_host])
    assert "link.bad_scheme" in refs(findings, "error")
    assert "link.seller_host_mismatch" in refs(findings, "error")
    assert "link.unknown_host" in refs(findings, "warning")


def test_dedupe_counters_must_match_recomputation():
    event = make_event()
    deduped = make_deduped([event])
    deduped["unique_events"] = 99
    findings = snapshot.check_dedupe([event], deduped)
    assert "dedupe.unique_mismatch" in refs(findings, "error")


def test_dedupe_membership_violations():
    a = make_event(source="articket", source_event_id="a1")
    b = make_event(source="ticketek", source_event_id="t1")
    ghost = make_event(source="ticketek", source_event_id="ghost")
    cluster_one = make_cluster(a, b, pairs=[{"a": "articket:a1", "b": "ticketek:t1", "kind": "slug"}])
    cluster_two = make_cluster(a, ghost)
    events = [a, b, ghost]
    findings = snapshot.check_dedupe(events, make_deduped(events, [cluster_one, cluster_two]))
    assert "dedupe.event_in_multiple_clusters" in refs(findings, "error")


def test_cluster_with_single_member_is_an_error():
    a = make_event()
    cluster = make_cluster(a)
    findings = snapshot.check_dedupe([a], make_deduped([a], [cluster]))
    assert "dedupe.cluster_too_small" in refs(findings, "error")


def test_merge_coherence_flags_price_from_another_seller():
    priced = make_event(
        source="articket",
        source_event_id="a1",
        seller="Articket",
        ticket_url=None,
        price_min=18000.0,
    )
    linked = make_event(
        source="ticketek",
        source_event_id="t1",
        seller="Ticketek",
        price_min=30000.0,
        price_text="Desde $30000",
    )
    findings = snapshot.check_merge_coherence(
        [priced, linked], make_deduped([priced, linked], [make_cluster(priced, linked)])
    )
    assert "merge.price_link_mismatch" in refs(findings, "warning")


def test_merge_coherence_flags_free_paid_conflict():
    free = make_event(source="municipal", source_event_id="m1", is_free=True, price_min=None)
    paid = make_event(is_free=False)
    findings = snapshot.check_merge_coherence(
        [free, paid], make_deduped([free, paid], [make_cluster(free, paid)])
    )
    assert "merge.free_paid_conflict" in refs(findings, "warning")


def test_merge_coherence_accepts_the_same_seller_named_two_ways():
    guessed = make_event(
        source="municipal",
        source_event_id="m1",
        seller="Venti.live",
        ticket_url=None,
        price_min=18000.0,
    )
    linked = make_event(
        source="venti",
        source_event_id="v1",
        seller="Venti",
        price_min=None,
        price_text=None,
        is_free=None,
        ticket_url="https://venti.live/evento/x",
    )
    findings = snapshot.check_merge_coherence(
        [guessed, linked], make_deduped([guessed, linked], [make_cluster(guessed, linked)])
    )
    assert "merge.price_link_mismatch" not in refs(findings)


def test_duplicate_slug_across_clusters_is_an_error():
    first = make_event(source="ticketek", source_event_id="t1")
    second = make_event(
        source="articket",
        source_event_id="a1",
        ticket_url=first["ticket_url"],
        seller="Articket",
    )
    cluster_one = make_cluster(first, make_event(source="municipal", source_event_id="m1"))
    cluster_two = make_cluster(second, make_event(source="colon", source_event_id="c1"))
    events = cluster_one["events"] + cluster_two["events"]
    findings = duplicates.find_candidates(events, make_deduped(events, [cluster_one, cluster_two]))
    assert "duplicates.slug_across_clusters" in refs(findings, "error")


def test_slug_across_clusters_on_disjoint_dates_is_not_an_error():
    # Sellers reuse one ticket page for every function of a show: Club TRI's
    # Cumbia Grande page served the 19/12 and the 22/11 night. Dedupe splits
    # them on purpose, so the verifier must not call that a missed join.
    first = make_event(
        source="articket",
        source_event_id="a1",
        date_start="2026-12-19",
        occurrences=["2026-12-19"],
    )
    second = make_event(
        source="elevenflow",
        source_event_id="e1",
        ticket_url=first["ticket_url"],
        date_start="2026-11-22",
        occurrences=["2026-11-22"],
    )
    cluster_one = make_cluster(
        first,
        make_event(
            source="clubtri",
            source_event_id="c1",
            ticket_url=None,
            seller=None,
            date_start="2026-12-19",
            occurrences=["2026-12-19"],
        ),
    )
    cluster_two = make_cluster(
        second,
        make_event(
            source="punto",
            source_event_id="p1",
            ticket_url=None,
            seller=None,
            date_start="2026-11-22",
            occurrences=["2026-11-22"],
        ),
    )
    events = cluster_one["events"] + cluster_two["events"]
    findings = duplicates.find_candidates(events, make_deduped(events, [cluster_one, cluster_two]))
    assert "duplicates.slug_across_clusters" not in refs(findings, "error")


def test_slug_across_clusters_on_a_shared_night_is_still_an_error():
    # The same page, the same night, two clusters: a real missed join that the
    # date excuse must not hide.
    first = make_event(source="articket", source_event_id="a1")
    second = make_event(
        source="elevenflow",
        source_event_id="e1",
        ticket_url=first["ticket_url"],
    )
    other_night = make_event(
        source="punto",
        source_event_id="p2",
        ticket_url=first["ticket_url"],
        date_start="2026-11-21",
        occurrences=["2026-11-21"],
    )
    cluster_one = make_cluster(first)
    cluster_two = make_cluster(second, other_night)
    events = cluster_one["events"] + cluster_two["events"]
    findings = duplicates.find_candidates(events, make_deduped(events, [cluster_one, cluster_two]))
    assert "duplicates.slug_across_clusters" in refs(findings, "error")
    evidence = [f for f in findings if f.check == "duplicates.slug_across_clusters"][0].evidence
    assert evidence["refs"] == ["articket:a1", "elevenflow:e1"]


# The slug-date verdict belongs to lib.dedupe; the verifier may only add the
# `date_start` fallback around it. Each case carries the verdict lib.dedupe
# reaches on the rows as the pipeline sees them plus the verdict the verifier
# must reach on the same rows, so the two cannot drift apart silently.
DATE_RULE_CASES = [
    # label, first (occurrences, date_start), second, verifier verdict, lib verdict
    ("same_night", (["2026-11-20"], "2026-11-20"), (["2026-11-20"], "2026-11-20"), True, True),
    (
        "disjoint_nights",
        (["2026-12-19"], "2026-12-19"),
        (["2026-11-22"], "2026-11-22"),
        False,
        False,
    ),
    (
        "shared_second_night",
        (["2026-11-20", "2026-11-21"], "2026-11-20"),
        (["2026-11-21"], "2026-11-21"),
        True,
        True,
    ),
    ("both_rows_without_sessions", ([], None), ([], None), True, True),
    (
        "one_row_without_sessions_or_start",
        ([], None),
        (["2026-11-21"], "2026-11-21"),
        True,
        True,
    ),
    (
        "start_only_row_agrees_with_the_known_night",
        ([], "2026-11-20"),
        (["2026-11-20"], "2026-11-20"),
        True,
        True,
    ),
    # The fallback's own cases: a start-date-only row still rules out, or
    # confirms, a night the pipeline can only call unknown.
    (
        "start_only_row_contradicts_the_known_night",
        ([], "2026-11-20"),
        (["2026-11-21"], "2026-11-21"),
        False,
        True,
    ),
    ("start_only_rows_agree", ([], "2026-11-20"), ([], "2026-11-20"), True, True),
    ("start_only_rows_disagree", ([], "2026-11-20"), ([], "2026-11-21"), False, True),
    (
        "start_only_row_against_an_unknown_row",
        ([], "2026-11-20"),
        ([], None),
        True,
        True,
    ),
]


def as_pipeline_event(row):
    """The row as lib.dedupe's rule sees it: sessions exactly as published."""
    return Event(**{field: row.get(field) for field in EVENT_FIELDS})


def slug_split_findings(first, second):
    """The verifier's verdict on two clusters that share one ticket slug."""
    events = [first, second]
    clusters = [make_cluster(first), make_cluster(second)]
    return refs(duplicates.find_candidates(events, make_deduped(events, clusters)))


@pytest.mark.parametrize(
    "first_dates,second_dates,verifier_verdict,lib_verdict",
    [case[1:] for case in DATE_RULE_CASES],
    ids=[case[0] for case in DATE_RULE_CASES],
)
def test_verifier_and_lib_dedupe_agree_on_the_slug_date_rule(
    monkeypatch, first_dates, second_dates, verifier_verdict, lib_verdict
):
    first = make_event(
        source="articket",
        source_event_id="a1",
        occurrences=list(first_dates[0]),
        date_start=first_dates[1],
    )
    second = make_event(
        source="elevenflow",
        source_event_id="e1",
        ticket_url=first["ticket_url"],
        occurrences=list(second_dates[0]),
        date_start=second_dates[1],
        venue_name="Teatro Roxy",
        venue_raw="Teatro Roxy, Buenos Aires 1200",
    )
    # lib.dedupe's own rule, on the rows as the pipeline publishes them.
    assert (
        dedupe._slug_dates_compatible(as_pipeline_event(first), as_pipeline_event(second))
        is lib_verdict
    )
    # The verifier's path reaches the verdict documented for it.
    found = "duplicates.slug_across_clusters" in slug_split_findings(first, second)
    assert found is verifier_verdict
    # One code path: flip lib.dedupe's rule and the verifier has to follow.
    monkeypatch.setattr(dedupe, "_slug_dates_compatible", lambda *_: not verifier_verdict)
    flipped = "duplicates.slug_across_clusters" in slug_split_findings(first, second)
    assert flipped is (not verifier_verdict)


def test_start_date_only_rows_keep_the_fallback_verdict():
    # A row that publishes only its start date still carries one known
    # session, so the verifier can tell two nights apart where the pipeline
    # can only see an unknown side -- and can also confirm a shared night.
    start_only = make_event(
        source="articket",
        source_event_id="a1",
        occurrences=[],
        date_start="2026-11-20",
    )
    other_night = make_event(
        source="elevenflow",
        source_event_id="e1",
        ticket_url=start_only["ticket_url"],
        occurrences=["2026-11-21"],
        date_start="2026-11-21",
        venue_name="Teatro Roxy",
        venue_raw="Teatro Roxy, Buenos Aires 1200",
    )
    assert "duplicates.slug_across_clusters" not in slug_split_findings(start_only, other_night)
    same_night = make_event(
        source="elevenflow",
        source_event_id="e1",
        ticket_url=start_only["ticket_url"],
        occurrences=["2026-11-20"],
        date_start="2026-11-20",
        venue_name="Teatro Roxy",
        venue_raw="Teatro Roxy, Buenos Aires 1200",
    )
    assert "duplicates.slug_across_clusters" in slug_split_findings(start_only, same_night)


def test_similar_titles_same_venue_and_date_are_candidates():
    first = make_event(source="municipal", source_event_id="m1", title="Abel Pintos - Tour 2026")
    second = make_event(
        source="articket",
        source_event_id="a1",
        title="Abel Pintos Tour 2026",
        ticket_url=None,
        seller=None,
    )
    findings = duplicates.find_candidates([first, second], make_deduped([first, second]))
    assert "duplicates.title_candidate" in refs(findings, "warning")


def test_same_source_candidates_are_left_to_dedupe():
    first = make_event(source="municipal", source_event_id="m1", title="Festival de Cine - Film A")
    second = make_event(
        source="municipal",
        source_event_id="m2",
        title="Festival de Cine - Film B",
        ticket_url=None,
        seller=None,
    )
    findings = duplicates.find_candidates([first, second], make_deduped([first, second]))
    assert "duplicates.title_candidate" not in refs(findings)


def test_clean_cross_source_pair_at_eighty_is_not_a_candidate():
    first = make_event(source="municipal", source_event_id="m1", title="Noche de Rock en el Puerto")
    second = make_event(
        source="articket",
        source_event_id="a1",
        title="Noche de Rock del Puerto",
        ticket_url=None,
        seller=None,
    )
    findings = duplicates.find_candidates([first, second], make_deduped([first, second]))
    scores = [finding.evidence["score"] for finding in findings if finding.check == "duplicates.title_candidate"]
    assert all(score >= duplicates.DEFAULT_THRESHOLD for score in scores)


def test_series_entries_are_not_candidates():
    first = make_event(
        source="auditorium",
        source_event_id="a1",
        title="41 Festival Internacional de Cine - Halima",
    )
    second = make_event(
        source="elevenflow",
        source_event_id="e1",
        title="41 Festival Internacional de Cine - Otra Pelicula",
        ticket_url=None,
        seller=None,
    )
    findings = duplicates.find_candidates([first, second], make_deduped([first, second]))
    assert "duplicates.title_candidate" not in refs(findings)


def test_rebuild_compare_reports_missing_extra_and_changed():
    stored = [make_event(), make_event(source_event_id="gone")]
    rebuilt = [make_event(price_min=25000.0, price_text="Desde $25000"), make_event(source_event_id="new")]
    findings = rebuild.compare_events(stored, rebuilt)
    assert "rebuild.missing" in refs(findings, "error")
    assert "rebuild.extra" in refs(findings, "error")
    changed = [f for f in findings if f.check == "rebuild.changed"]
    assert changed and "price_min" in changed[0].evidence["fields"]


def test_rebuild_one_year_shift_is_time_dependent_not_an_error():
    stored = [make_event(date_start="2026-11-14", occurrences=["2026-11-14"])]
    rebuilt = [make_event(date_start="2027-11-14", occurrences=["2027-11-14"])]
    findings = rebuild.compare_events(stored, rebuilt)
    assert "rebuild.time_dependent" in refs(findings, "warning")
    assert "rebuild.changed" not in refs(findings)


def test_rebuild_exempts_network_derived_fields_per_event():
    stored = [make_event(source="articket", source_event_id="a1", date_end="2027-02-18")]
    rebuilt = [make_event(source="articket", source_event_id="a1", date_end="2026-11-05")]
    findings = rebuild.compare_events(
        stored, rebuilt, exempt={"articket:a1": {"date_end", "occurrences", "multi_date_incomplete"}}
    )
    assert findings == []


def test_module_source_map_covers_every_pipeline_module():
    from run_pipeline import MODULES

    assert set(rebuild.MODULE_SOURCES) == {name for name, _ in MODULES}


def test_module_source_map_matches_collector_constants():
    from run_pipeline import MODULES

    for name, module in MODULES:
        if hasattr(module, "SOURCE"):
            declared = {module.SOURCE}
        elif hasattr(module, "SOURCES"):
            declared = {
                entry["source"] if isinstance(entry, dict) else entry for entry in module.SOURCES
            }
        elif hasattr(module, "TENANTS"):
            declared = {tenant.source for tenant in module.TENANTS}
        else:  # pragma: no cover - guards the mapping contract
            raise AssertionError(f"{name} exposes no source declaration")
        assert rebuild.MODULE_SOURCES[name] == declared, name


def test_report_exit_codes_and_json_shape():
    clean = core.Report()
    warn = core.Report([core.Finding("c", "warning", "careful")])
    error = core.Report([core.Finding("c", "error", "broken", {"ref": "x:1"})])
    assert clean.exit_code() == 0
    assert warn.exit_code() == 0
    assert warn.exit_code(strict=True) == 1
    assert error.exit_code() == 1
    payload = error.to_dict()
    assert payload["summary"] == {"errors": 1, "warnings": 0, "findings": 1}
    assert payload["findings"][0]["evidence"] == {"ref": "x:1"}


def test_cli_snapshot_clean_and_broken(tmp_path, capsys):
    event = make_event()
    (tmp_path / "events_normalized.json").write_text(json.dumps([event]), encoding="utf-8")
    (tmp_path / "events_deduped.json").write_text(
        json.dumps(make_deduped([event])), encoding="utf-8"
    )
    assert cli.main(["snapshot", "--json", "--data-dir", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["errors"] == 0

    (tmp_path / "events_normalized.json").write_text(
        json.dumps([event, make_event(title="Otro")]), encoding="utf-8"
    )
    assert cli.main(["snapshot", "--json", "--data-dir", str(tmp_path)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["errors"] >= 1


def test_cli_rejects_unknown_command(tmp_path):
    assert cli.main(["nope", "--data-dir", str(tmp_path)]) == 2


def test_real_snapshot_smoke(capsys):
    code = cli.main(["snapshot", "--json", "--root", str(ROOT)])
    assert code in (0, 1)
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["summary"]["findings"] >= 1
    assert all({"check", "severity", "message", "evidence"} <= set(item) for item in payload["findings"])
