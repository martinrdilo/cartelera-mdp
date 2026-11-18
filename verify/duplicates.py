"""Duplicates the dedupe pass left behind.

`lib.dedupe` clusters what it can prove; this layer searches for pairs that
stayed apart while sharing a strong identity signal (same ticket slug, or same
venue and session with near-identical titles).
"""

from __future__ import annotations

from collections import defaultdict

from lib.dedupe import extract_slug, series_prefix_conflict, title_similarity
from lib.schema import Event
from lib.venues import venue_key

from .core import Finding, event_dict, event_ref

DEFAULT_THRESHOLD = 85


def _dates(row) -> set[str]:
    values = list(row.get("occurrences") or [])
    if not values and row.get("date_start"):
        values = [row.get("date_start")]
    return {value for value in values if isinstance(value, str)}


def _cluster_index(deduped) -> dict[str, int]:
    mapping = {}
    for index, cluster in enumerate(deduped.get("clusters") or []):
        for member in cluster.get("events") or []:
            mapping[event_ref(member)] = index
    return mapping


def _same_cluster(first: str, second: str, cluster_of: dict[str, int]) -> bool:
    index = cluster_of.get(first)
    return index is not None and index == cluster_of.get(second)


def _as_event(row) -> Event:
    return Event(**{field: row.get(field) for field in Event.__dataclass_fields__})


def _slug_findings(events, cluster_of) -> list[Finding]:
    by_slug: dict[str, dict[str, dict]] = defaultdict(dict)
    for event in events:
        row = event_dict(event)
        slug = extract_slug(row.get("ticket_url"))
        if slug:
            by_slug[slug][event_ref(event)] = row

    findings = []
    for slug, rows in sorted(by_slug.items()):
        if len(rows) < 2:
            continue
        groups: dict[object, list[str]] = defaultdict(list)
        for reference in rows:
            groups[cluster_of.get(reference, f"unclustered:{reference}")].append(reference)
        if len(groups) > 1:
            findings.append(
                Finding(
                    "duplicates.slug_across_clusters",
                    "error",
                    f"{slug} belongs to {len(groups)} separate groups",
                    {"slug": slug, "refs": sorted(rows), "groups": [sorted(group) for group in groups.values()]},
                )
            )
    return findings


def _title_findings(events, cluster_of, threshold) -> list[Finding]:
    buckets: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
    for event in events:
        row = event_dict(event)
        key = venue_key(row.get("venue_raw") or row.get("venue_name") or "")
        if not key:
            continue
        for day in _dates(row):
            buckets[(key, day)].append((event_ref(event), row))

    findings = []
    seen: set[frozenset] = set()
    for (key, day), items in sorted(buckets.items()):
        if len(items) < 2:
            continue
        for index, (first_ref, first_row) in enumerate(items):
            for second_ref, second_row in items[index + 1 :]:
                if first_ref == second_ref:
                    continue
                # Same-source pairs are already governed by lib.dedupe's strict
                # rules; flagging them again only adds noise (a festival runs
                # several different films in the same venue on the same day).
                if first_row.get("source") == second_row.get("source"):
                    continue
                pair = frozenset((first_ref, second_ref))
                if pair in seen:
                    continue
                seen.add(pair)
                if _same_cluster(first_ref, second_ref, cluster_of):
                    continue
                if series_prefix_conflict(_as_event(first_row), _as_event(second_row)):
                    continue
                score = title_similarity(first_row.get("title"), second_row.get("title"))
                if score < threshold:
                    continue
                findings.append(
                    Finding(
                        "duplicates.title_candidate",
                        "warning",
                        f"{first_ref} and {second_ref} look like the same event (score {score:.0f})",
                        {
                            "venue": key,
                            "date": day,
                            "score": round(float(score), 1),
                            "a": {"ref": first_ref, "title": first_row.get("title"), "source": first_row.get("source")},
                            "b": {"ref": second_ref, "title": second_row.get("title"), "source": second_row.get("source")},
                        },
                    )
                )
    return findings


def find_candidates(normalized, deduped, threshold: float = DEFAULT_THRESHOLD) -> list[Finding]:
    """Same slug across clusters, plus same venue/date with similar titles."""
    cluster_of = _cluster_index(deduped)
    findings = _slug_findings(normalized, cluster_of)
    findings.extend(_title_findings(normalized, cluster_of, threshold))
    return findings
