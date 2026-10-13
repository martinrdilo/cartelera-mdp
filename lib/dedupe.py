"""Cross-source dedupe.

Strategy:
1. Gate: events only compare inside the same canonical venue (registry id,
   normalized raw name fallback).
2. Date match: occurrence sets must intersect; when either side has no
   known occurrences (range without recurrence info, parse failure), fall
   back to start-date equality.
3. Exact join: same ticket slug (host + slug) on both sides wins outright.
4. Fuzzy fallback: rapidfuzz token_set_ratio over normalized titles,
   threshold ~85 (tuned against the live corpus; see REPORT.md).

Returns clusters of >= 2 events with per-pair evidence.
"""

import re
from urllib.parse import urlparse

from rapidfuzz import fuzz

from lib.venues import normalize_name, resolve, venue_key

# Hosts whose URL path ends in a stable event slug (exact join signal).
TICKET_HOSTS = (
    "articket.com.ar",
    "cultutickets.com",
    "passline.com",
    "ticketmas.ar",
    "ticketek.com.ar",
)

DEFAULT_THRESHOLD = 85

# CultuTickets embeds date and city prefixes in titles ("VIER 16 DE OKTUBRE
# MDP UNA OBRA REDONDA"). They are stripped before title comparison so they
# neither create nor block matches. Source titles stay untouched in output.
_WEEKDAY = r"(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)[a-záéíóú]*\.?"
_MONTH = r"(?:ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|okt|nov|dic)[a-záéíóú]*"
_TITLE_DATE_PREFIX_RE = re.compile(
    rf"^(?:{_WEEKDAY}\s+)?"
    rf"(?:\d{{1,2}}\s*-\s*\d{{1,2}}(?:\s*-\s*\d{{2,4}})?"
    rf"|\d{{1,2}}\s+de\s+{_MONTH}(?:\s+\d{{4}})?"
    rf"|\d{{1,2}}\s*-\s*{_MONTH}(?:\s*-\s*\d{{2,4}})?"
    rf"|\d{{1,2}}\s+{_MONTH})"
    rf"(?:\s+(?:mdp|mar\s+del\s+plata)\b)?\s*[-–:]?\s*",
    re.IGNORECASE,
)


# Venue fingerprint: the registry (data/venues.json via lib.venues) resolves
# every known spelling to a canonical id; unknown venues fall back to their
# normalized raw name. See REPORT.md for the venue inventory.
def canonical_venue(value):
    """Canonical fingerprint: registry id when resolvable, else normalized raw."""
    return venue_key(value)


def normalize_text(value):
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    return normalize_name(value)


def extract_slug(url):
    """Return "<host>:<slug>" for known ticket hosts, else None."""
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not any(known in host for known in TICKET_HOSTS):
        return None
    path = parsed.path.strip("/")
    if not path:
        return None
    return f"{host}:{path.split('/')[-1].lower()}"


def strip_title_noise(title):
    """Remove a leading date/city prefix (CultuTickets style) before matching."""
    return _TITLE_DATE_PREFIX_RE.sub("", title or "").strip()


def title_similarity(title_a, title_b):
    """token_set_ratio over normalized titles (0-100)."""
    return fuzz.token_set_ratio(
        normalize_text(strip_title_noise(title_a)),
        normalize_text(strip_title_noise(title_b)),
    )


def venue_group_key(event):
    """Grouping key: canonical venue fingerprint."""
    return canonical_venue(event.venue_name or event.venue_raw)


def occurrences_of(event):
    """Known session dates; falls back to the start date when none are known."""
    if event.occurrences:
        return set(event.occurrences)
    return {event.date_start} if event.date_start else set()


def _dates_match(event_a, event_b):
    """Occurrence sets must intersect; empty sets fall back to date_start."""
    occurrences_a = set(event_a.occurrences or [])
    occurrences_b = set(event_b.occurrences or [])
    if occurrences_a and occurrences_b:
        return bool(occurrences_a & occurrences_b)
    return bool(event_a.date_start) and event_a.date_start == event_b.date_start


def _display_venue(event):
    """Registry display name when resolvable, else the source's own name."""
    raw = event.venue_name or event.venue_raw
    resolved = resolve(raw)
    return resolved[1] if resolved else raw


def _pair_evidence(event_a, event_b, threshold):
    slug_a = extract_slug(event_a.ticket_url)
    slug_b = extract_slug(event_b.ticket_url)
    if slug_a and slug_a == slug_b:
        return {"kind": "ticket_slug", "score": 100.0, "slug": slug_a}
    score = title_similarity(event_a.title, event_b.title)
    if score >= threshold:
        return {"kind": "title_fuzzy", "score": round(float(score), 1)}
    return None


def _event_ref(event):
    return f"{event.source}:{event.source_event_id}"


def cluster_events(events, threshold=DEFAULT_THRESHOLD):
    """Cluster duplicate events; returns a list of clusters with evidence.

    Each cluster: {"venue": canonical id or normalized name,
    "venue_name": display name, "dates": known session dates (union of the
    members), "events": [...], "pairs": [...]}.
    """
    groups = {}
    for event in events:
        if not event.date_start:
            continue
        groups.setdefault(venue_group_key(event), []).append(event)

    clusters = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        parent = list(range(len(group)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        pairs = []
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if not _dates_match(group[i], group[j]):
                    continue
                evidence = _pair_evidence(group[i], group[j], threshold)
                if evidence is None:
                    continue
                union(i, j)
                pairs.append(
                    {
                        "a": _event_ref(group[i]),
                        "b": _event_ref(group[j]),
                        **evidence,
                    }
                )
        components = {}
        for index, event in enumerate(group):
            components.setdefault(find(index), []).append(event)
        for members in components.values():
            if len(members) < 2:
                continue
            refs = {_event_ref(event) for event in members}
            dates = sorted({date for event in members for date in occurrences_of(event)})
            clusters.append(
                {
                    "venue": key,
                    "venue_name": _display_venue(members[0]),
                    "dates": dates,
                    "events": [event.to_dict() for event in members],
                    "pairs": [p for p in pairs if p["a"] in refs and p["b"] in refs],
                }
            )
    return clusters
