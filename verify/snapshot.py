"""Offline invariants over the committed data snapshot.

Covers schema, occurrences, price, links, dedupe structure and the multi-source
merge the site performs. No network access and no writes.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from lib.schema import Event
from lib.sellers import seller_from_url

from .core import Finding, event_dict, event_ref, parse_iso_date
from .rebuild import KNOWN_SOURCES

EVENT_FIELDS = tuple(Event.__dataclass_fields__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Municipal guesses a seller from free text ("Venti.live"), while the host map
# says "Venti". Both name the same store; comparison uses a canonical key.
_SELLER_ALIASES = {"venti live": "venti"}

_REQUIRED_STR = {"source", "source_event_id", "title", "city"}
# Fields the schema gained after the first snapshots were written. A row from
# before the field existed is still valid: absence is not an error, but a
# present value is type-checked like any other nullable string.
_OPTIONAL_FIELDS = {"venue_url"}
_NULLABLE_STR = {
    "venue_name",
    "venue_raw",
    "date_start",
    "date_end",
    "time",
    "price_text",
    "currency",
    "ticket_url",
    "seller",
    "image_url",
    "raw_url",
    "collected_at",
    "venue_url",
}
_BOOL_FIELDS = {"recurrence_unknown", "multi_date_incomplete"}
_DATE_FIELDS = ("date_start", "date_end")

_COUNTER_CHECKS = {
    "total_normalized": "dedupe.total_mismatch",
    "unique_events": "dedupe.unique_mismatch",
    "duplicate_clusters": "dedupe.clusters_mismatch",
    "events_in_clusters": "dedupe.members_mismatch",
}


def _date(value):
    return parse_iso_date(value)


def _seller_key(value):
    if not value:
        return None
    key = " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())
    return _SELLER_ALIASES.get(key, key)


def _is_iso_datetime(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_ok(field, value) -> bool:
    if field in _REQUIRED_STR:
        return isinstance(value, str)
    if field in _NULLABLE_STR:
        return value is None or isinstance(value, str)
    if field in _BOOL_FIELDS:
        return isinstance(value, bool)
    if field == "is_free":
        return value is None or isinstance(value, bool)
    if field == "price_min":
        return value is None or _is_number(value)
    if field == "occurrences":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return True


def check_schema(events, known_sources=None) -> list[Finding]:
    """Field presence, types, date/time formats, known sources and unique ids."""
    known = set(KNOWN_SOURCES if known_sources is None else known_sources)
    findings: list[Finding] = []
    seen: dict[tuple, list[str]] = {}

    for event in events:
        row = event_dict(event)
        reference = event_ref(event)

        missing = [
            field for field in EVENT_FIELDS if field not in row and field not in _OPTIONAL_FIELDS
        ]
        if missing:
            findings.append(
                Finding(
                    "schema.missing_field",
                    "error",
                    f"{reference} lacks {', '.join(missing)}",
                    {"ref": reference, "fields": missing},
                )
            )
        unexpected = sorted(set(row) - set(EVENT_FIELDS))
        if unexpected:
            findings.append(
                Finding(
                    "schema.unexpected_field",
                    "warning",
                    f"{reference} carries unknown field(s): {', '.join(unexpected)}",
                    {"ref": reference, "fields": unexpected},
                )
            )
        bad_types = [field for field, value in row.items() if field in EVENT_FIELDS and not _type_ok(field, value)]
        if bad_types:
            findings.append(
                Finding(
                    "schema.bad_type",
                    "error",
                    f"{reference} has wrong type for {', '.join(bad_types)}",
                    {"ref": reference, "fields": bad_types},
                )
            )
        empty = [
            field
            for field in _REQUIRED_STR
            if isinstance(row.get(field), str) and not row.get(field).strip()
        ]
        if empty:
            findings.append(
                Finding(
                    "schema.empty_required",
                    "error",
                    f"{reference} has an empty {', '.join(sorted(empty))}",
                    {"ref": reference, "fields": sorted(empty)},
                )
            )
        if not (row.get("venue_name") or "").strip():
            findings.append(
                Finding(
                    "schema.empty_venue",
                    "warning",
                    f"{reference} has no venue and would fall back to the city name",
                    {"ref": reference, "venue_raw": row.get("venue_raw")},
                )
            )

        for field in _DATE_FIELDS:
            value = row.get(field)
            if value is not None and _date(value) is None:
                findings.append(
                    Finding(
                        "schema.bad_date",
                        "error",
                        f"{reference} has invalid {field}={value!r}",
                        {"ref": reference, "field": field, "value": value},
                    )
                )
        time_value = row.get("time")
        if time_value is not None and not (isinstance(time_value, str) and _TIME_RE.match(time_value)):
            findings.append(
                Finding(
                    "schema.bad_time",
                    "error",
                    f"{reference} has invalid time={time_value!r}",
                    {"ref": reference, "value": time_value},
                )
            )
        collected = row.get("collected_at")
        if collected is not None and not _is_iso_datetime(collected):
            findings.append(
                Finding(
                    "schema.bad_collected_at",
                    "error",
                    f"{reference} has invalid collected_at={collected!r}",
                    {"ref": reference, "value": collected},
                )
            )
        source = row.get("source")
        if source not in known:
            findings.append(
                Finding(
                    "schema.unknown_source",
                    "error",
                    f"{reference} has unknown source {source!r}",
                    {"ref": reference, "source": source},
                )
            )

        key = (source, row.get("source_event_id"))
        seen.setdefault(key, []).append(reference)

    for (source, source_id), refs in seen.items():
        if len(refs) > 1 and source and source_id:
            findings.append(
                Finding(
                    "id.duplicate_source_event_id",
                    "error",
                    f"{source}:{source_id} appears {len(refs)} times",
                    {"ref": f"{source}:{source_id}", "count": len(refs)},
                )
            )
    return findings


def check_occurrences(events) -> list[Finding]:
    """Occurrence set ordering, uniqueness, bounds and unexplained emptiness."""
    findings: list[Finding] = []
    for event in events:
        row = event_dict(event)
        reference = event_ref(event)
        occurrences = row.get("occurrences")
        if not isinstance(occurrences, list):
            continue

        bad = [value for value in occurrences if _date(value) is None]
        if bad:
            findings.append(
                Finding(
                    "occurrence.bad_date",
                    "error",
                    f"{reference} has invalid occurrence date(s): {bad[:5]}",
                    {"ref": reference, "dates": bad[:20]},
                )
            )
        if len(set(occurrences)) != len(occurrences):
            findings.append(
                Finding(
                    "occurrence.duplicate_date",
                    "error",
                    f"{reference} repeats an occurrence date",
                    {"ref": reference},
                )
            )
        if occurrences != sorted(occurrences):
            findings.append(
                Finding(
                    "occurrence.unsorted",
                    "warning",
                    f"{reference} lists occurrences out of order",
                    {"ref": reference},
                )
            )

        start = _date(row.get("date_start"))
        end = _date(row.get("date_end"))
        if not occurrences:
            if not (row.get("recurrence_unknown") or row.get("multi_date_incomplete")):
                findings.append(
                    Finding(
                        "occurrence.empty_unexplained",
                        "error",
                        f"{reference} has no occurrences and no reason flag",
                        {"ref": reference},
                    )
                )
            continue

        if row.get("date_start") is None:
            findings.append(
                Finding(
                    "occurrence.start_missing",
                    "error",
                    f"{reference} has occurrences but no date_start",
                    {"ref": reference},
                )
            )
        elif row.get("date_start") not in occurrences:
            findings.append(
                Finding(
                    "occurrence.start_not_in_occurrences",
                    "error",
                    f"{reference} date_start is not in its occurrences",
                    {"ref": reference, "date_start": row.get("date_start")},
                )
            )

        if start and end and end < start:
            findings.append(
                Finding(
                    "occurrence.end_before_start",
                    "error",
                    f"{reference} ends before it starts",
                    {"ref": reference, "date_start": row.get("date_start"), "date_end": row.get("date_end")},
                )
            )
        if start:
            outside = []
            for value in occurrences:
                parsed = _date(value)
                if parsed is None:
                    continue
                if parsed < start or (end and parsed > end):
                    outside.append(value)
            if outside:
                findings.append(
                    Finding(
                        "occurrence.out_of_range",
                        "error",
                        f"{reference} lists {len(outside)} date(s) outside its range",
                        {
                            "ref": reference,
                            "dates": outside[:20],
                            "date_start": row.get("date_start"),
                            "date_end": row.get("date_end"),
                        },
                    )
                )
    return findings


def check_price(events) -> list[Finding]:
    """Price/free contradictions and missing currency."""
    findings: list[Finding] = []
    for event in events:
        row = event_dict(event)
        reference = event_ref(event)
        price = row.get("price_min")
        is_free = row.get("is_free")

        if _is_number(price):
            if price < 0:
                findings.append(
                    Finding("price.negative", "error", f"{reference} has a negative price", {"ref": reference, "price": price})
                )
            if row.get("currency") is None:
                findings.append(
                    Finding(
                        "price.currency_missing",
                        "error",
                        f"{reference} has price_min without currency",
                        {"ref": reference, "price": price},
                    )
                )
        if is_free is True and _is_number(price) and price != 0:
            findings.append(
                Finding(
                    "price.free_with_positive_price",
                    "error",
                    f"{reference} is free but carries price_min={price}",
                    {"ref": reference, "price": price},
                )
            )
        if is_free is False and _is_number(price) and price == 0:
            findings.append(
                Finding(
                    "price.paid_zero",
                    "error",
                    f"{reference} is paid but carries price_min=0",
                    {"ref": reference},
                )
            )
    return findings


def check_links(events) -> list[Finding]:
    """URL scheme validity and seller/host agreement on ticket links."""
    findings: list[Finding] = []
    for event in events:
        row = event_dict(event)
        reference = event_ref(event)
        for field in ("ticket_url", "raw_url"):
            value = row.get(field)
            if value is None:
                continue
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                findings.append(
                    Finding(
                        "link.bad_scheme",
                        "error",
                        f"{reference} has a non-http {field}: {value!r}",
                        {"ref": reference, "field": field, "url": value},
                    )
                )
        ticket_url = row.get("ticket_url")
        seller = row.get("seller")
        if ticket_url and seller:
            host_seller = seller_from_url(ticket_url)
            if host_seller is None:
                findings.append(
                    Finding(
                        "link.unknown_host",
                        "warning",
                        f"{reference} ticket host is not in the seller map",
                        {"ref": reference, "url": ticket_url},
                    )
                )
            elif host_seller != seller:
                findings.append(
                    Finding(
                        "link.seller_host_mismatch",
                        "error",
                        f"{reference} says seller={seller} but the host belongs to {host_seller}",
                        {"ref": reference, "seller": seller, "host_seller": host_seller, "url": ticket_url},
                    )
                )
    return findings


def check_dedupe(events, deduped) -> list[Finding]:
    """Declared counters and cluster membership integrity."""
    findings: list[Finding] = []
    clusters = deduped.get("clusters") or []
    rows = [event_dict(event) for event in events]
    known_refs = {event_ref(event) for event in events}

    members_total = sum(len(cluster.get("events") or []) for cluster in clusters)
    recomputed = {
        "total_normalized": len(rows),
        "unique_events": len(rows) - sum(len(cluster.get("events") or []) - 1 for cluster in clusters),
        "duplicate_clusters": len(clusters),
        "events_in_clusters": members_total,
    }
    for field, computed in recomputed.items():
        declared = deduped.get(field)
        if declared != computed:
            findings.append(
                Finding(
                    _COUNTER_CHECKS[field],
                    "error",
                    f"dedupe {field} declares {declared!r} but recomputes to {computed}",
                    {"field": field, "declared": declared, "recomputed": computed},
                )
            )

    cluster_of: dict[str, int] = {}
    conflicts: dict[str, set[int]] = {}
    for index, cluster in enumerate(clusters):
        members = cluster.get("events") or []
        member_refs = [event_ref(member) for member in members]
        if len(members) < 2:
            findings.append(
                Finding(
                    "dedupe.cluster_too_small",
                    "error",
                    f"cluster #{index} has {len(members)} member(s)",
                    {"cluster": index, "refs": member_refs},
                )
            )
        if len(set(member_refs)) != len(member_refs):
            findings.append(
                Finding(
                    "dedupe.member_duplicated",
                    "error",
                    f"cluster #{index} lists the same event twice",
                    {"cluster": index, "refs": member_refs},
                )
            )
        for reference in set(member_refs):
            if reference not in known_refs:
                findings.append(
                    Finding(
                        "dedupe.member_missing",
                        "error",
                        f"cluster #{index} references {reference}, absent from the snapshot",
                        {"cluster": index, "ref": reference},
                    )
                )
            if reference in cluster_of and cluster_of[reference] != index:
                conflicts.setdefault(reference, {cluster_of[reference]}).add(index)
            cluster_of.setdefault(reference, index)

        member_set = set(member_refs)
        for pair in cluster.get("pairs") or []:
            for side in ("a", "b"):
                value = pair.get(side)
                if value and value not in member_set:
                    findings.append(
                        Finding(
                            "dedupe.pair_member_missing",
                            "error",
                            f"cluster #{index} pair evidence names {value}, not a member",
                            {"cluster": index, "ref": value},
                        )
                    )

    for reference, indexes in sorted(conflicts.items()):
        findings.append(
            Finding(
                "dedupe.event_in_multiple_clusters",
                "error",
                f"{reference} appears in clusters {sorted(indexes)}",
                {"ref": reference, "clusters": sorted(indexes)},
            )
        )
    return findings


def check_last_run(last_run, events, deduped) -> list[Finding]:
    """Cross-check the run summary against the snapshot it describes."""
    if not last_run:
        return []
    findings: list[Finding] = []
    totals = last_run.get("totals") or {}
    expected_normalized = len(events)
    if totals.get("normalized") != expected_normalized:
        findings.append(
            Finding(
                "last_run.normalized_mismatch",
                "warning",
                f"last_run totals.normalized={totals.get('normalized')!r} but the snapshot has {expected_normalized}",
                {"declared": totals.get("normalized"), "actual": expected_normalized},
            )
        )
    if totals.get("unique") != deduped.get("unique_events"):
        findings.append(
            Finding(
                "last_run.unique_mismatch",
                "warning",
                f"last_run totals.unique={totals.get('unique')!r} but dedupe declares {deduped.get('unique_events')!r}",
                {"declared": totals.get("unique"), "actual": deduped.get("unique_events")},
            )
        )
    counts = Counter(event_dict(event).get("source") for event in events)
    mismatched = []
    for source, entry in sorted((last_run.get("sources") or {}).items()):
        declared = (entry or {}).get("normalized")
        if declared is not None and declared != counts.get(source, 0):
            mismatched.append({"source": source, "declared": declared, "actual": counts.get(source, 0)})
    if mismatched:
        findings.append(
            Finding(
                "last_run.source_mismatch",
                "warning",
                f"last_run per-source counts disagree for {len(mismatched)} source(s)",
                {"sources": mismatched[:20]},
            )
        )
    return findings


def _owner(members, field, site):
    """Mirror build_site.pick_field, keeping the winning member."""
    for source in site.SOURCE_ORDER:
        for member in members:
            if member.get("source") == source and site.is_usable(member.get(field)):
                return member
    return None


def check_merge_coherence(events, deduped) -> list[Finding]:
    """Reproduce the site merge and flag cross-source price/link/free mixing."""
    import build_site as site

    findings: list[Finding] = []
    for index, cluster in enumerate(deduped.get("clusters") or []):
        members = [event_dict(member) for member in (cluster.get("events") or [])]
        if len(members) < 2:
            continue
        label = f"cluster #{index} ({cluster.get('venue_name') or 'unknown venue'})"
        refs = sorted(event_ref(member) for member in members)

        free_flags = {bool(member.get("is_free")) for member in members if member.get("is_free") is not None}
        if free_flags == {True, False}:
            findings.append(
                Finding(
                    "merge.free_paid_conflict",
                    "warning",
                    f"{label} mixes free and paid sources",
                    {"cluster": index, "refs": refs},
                )
            )

        picked_price = site.pick_field(members, "price_min")
        picked_link = site.pick_field(members, "ticket_url")
        if picked_price is None or not picked_link or not site.is_usable(picked_price):
            continue
        price_owner = _owner(members, "price_min", site)
        link_owner = _owner(members, "ticket_url", site)
        if price_owner is None or link_owner is None:
            continue
        price_seller = _seller_key(
            seller_from_url(price_owner.get("ticket_url") or "") or price_owner.get("seller")
        )
        link_seller = _seller_key(seller_from_url(picked_link) or link_owner.get("seller"))
        if price_seller and link_seller and price_seller != link_seller:
            findings.append(
                Finding(
                    "merge.price_link_mismatch",
                    "warning",
                    f"{label} shows a {price_owner.get('seller') or price_seller} price next to a "
                    f"{seller_from_url(picked_link) or link_owner.get('seller')} link",
                    {
                        "cluster": index,
                        "refs": refs,
                        "price": {"ref": event_ref(price_owner), "value": picked_price, "seller": price_seller},
                        "link": {"ref": event_ref(link_owner), "value": picked_link, "seller": link_seller},
                    },
                )
            )
    return findings


def run_snapshot(normalized, deduped, last_run=None, known_sources=None) -> list[Finding]:
    """Every offline invariant over one snapshot."""
    findings: list[Finding] = []
    findings.extend(check_schema(normalized, known_sources))
    findings.extend(check_occurrences(normalized))
    findings.extend(check_price(normalized))
    findings.extend(check_links(normalized))
    findings.extend(check_dedupe(normalized, deduped))
    findings.extend(check_merge_coherence(normalized, deduped))
    findings.extend(check_last_run(last_run, normalized, deduped))
    return findings
