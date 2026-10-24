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
    "venti.live",
    "wearebombo.com",
    "tuentrada.com",
    "plateanet.com",
    "unica-cartelera.com.ar",
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
    """Return "<host>:<event-slug>" for known ticket hosts, else None.

    Ticketek puts the event first and the venue second
    (`/hairspray/teatro-tronador`), so its event slug is the first segment;
    the other sellers end their URLs with the event slug.
    """
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not any(known in host for known in TICKET_HOSTS):
        return None
    segments = [segment for segment in parsed.path.strip("/").split("/") if segment]
    if not segments:
        return None
    if "ticketek.com.ar" in host:
        slug = segments[0]
    else:
        slug = segments[-1]
    return f"{host}:{slug.lower()}"


# Standalone numeric date tokens ("22.10", "31/10", "16-10-2026") appear in
# Bombo/Venti/Articket titles. Remove them anywhere in the title for matching;
# the source title itself stays untouched in the output.
_DATE_TOKEN_RE = re.compile(r"(?<!\d)\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?(?!\d)")
# Edition markers ("Vol. 3", "Volumen III", "Edición 2") name the same event's
# edition, not a different show; strip them for matching only.
_EDITION_RE = re.compile(
    r"\b(?:vol(?:umen)?|edici[oó]n)\.?\s*(?:[ivxlcdm]+|\d+)\b",
    re.IGNORECASE,
)


def strip_title_noise(title):
    """Remove date/city noise (prefix, standalone dates, separators) before matching."""
    cleaned = _TITLE_DATE_PREFIX_RE.sub("", title or "")
    cleaned = _DATE_TOKEN_RE.sub(" ", cleaned)
    cleaned = _EDITION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[|]+", " ", cleaned)
    return " ".join(cleaned.split()).strip(" -–,:|")


def title_similarity(title_a, title_b):
    """token_set_ratio over normalized titles (0-100)."""
    return fuzz.token_set_ratio(
        normalize_text(strip_title_noise(title_a)),
        normalize_text(strip_title_noise(title_b)),
    )


# Connectors and venue words do not identify an event. Removing them lets
# "Diego Torres - Mi Norte y Mi Sur" match "Diego Torres en Arena Mardel Plata"
# once the venue+date gate already holds.
_TITLE_STOPWORDS = {
    "a", "al", "and", "con", "de", "del", "el", "en", "la", "las", "lo",
    "los", "o", "para", "por", "presenta", "presentan", "the", "u", "un",
    "una", "y", "vs", "mar", "plata", "mardel", "mdp",
}


def _venue_tokens(event):
    raw = event.venue_name or event.venue_raw or ""
    if "," in raw:
        raw = raw.split(",", 1)[0]
    return set(normalize_text(raw).split())


def _significant_tokens(event):
    """Title tokens with connectors and the event's own venue removed."""
    tokens = normalize_text(strip_title_noise(event.title)).split()
    venue = _venue_tokens(event)
    return [token for token in tokens if token not in _TITLE_STOPWORDS and token not in venue]


def _all_tokens_match(shorter, longer, threshold=85.0):
    """True when every token of `shorter` has a close token in `longer`."""
    if len(shorter) < 2 or len(longer) < 2:
        return None
    scores = []
    for token in shorter:
        score = max(fuzz.ratio(token, other) for other in longer)
        if score < threshold:
            return None
        scores.append(score)
    return round(float(min(scores)), 1)


def _core_title_match(event_a, event_b):
    """One title's significant tokens are contained in the other's."""
    tokens_a = _significant_tokens(event_a)
    tokens_b = _significant_tokens(event_b)
    if len(tokens_a) <= len(tokens_b):
        return _all_tokens_match(tokens_a, tokens_b)
    return _all_tokens_match(tokens_b, tokens_a)


def _prefix_title_match(event_a, event_b):
    """The first two significant tokens (usually the artist) fuzzy-match."""
    tokens_a = _significant_tokens(event_a)
    tokens_b = _significant_tokens(event_b)
    if len(tokens_a) < 2 or len(tokens_b) < 2:
        return None
    scores = [fuzz.ratio(tokens_a[index], tokens_b[index]) for index in range(2)]
    if min(scores) < 88:
        return None
    return round(float(min(scores)), 1)


def _single_token_match(event_a, event_b):
    """A one-token title (e.g. "DANTE") inside the other title's tokens."""
    tokens_a = _significant_tokens(event_a)
    tokens_b = _significant_tokens(event_b)
    if len(tokens_a) == 1 and len(tokens_b) > 1:
        short, longer = tokens_a[0], tokens_b
    elif len(tokens_b) == 1 and len(tokens_a) > 1:
        short, longer = tokens_b[0], tokens_a
    else:
        return None
    if len(short) < 4:
        return None
    score = max(fuzz.ratio(short, token) for token in longer)
    return round(float(score), 1) if score >= 90 else None


def _series_prefix_conflict(event_a, event_b):
    """True when two titles share a long series prefix but differ in the entry.

    A film festival publishes every screening under the same prefix
    ("41° Festival Internacional de Cine: <film>"). The shared prefix inflates
    token_set_ratio, so two different films look alike. When the common
    leading tokens are long and the remaining tails are dissimilar, the titles
    are different entries of the same series.
    """
    tokens_a = _significant_tokens(event_a)
    tokens_b = _significant_tokens(event_b)
    common = 0
    for token_a, token_b in zip(tokens_a, tokens_b):
        if fuzz.ratio(token_a, token_b) < 90:
            break
        common += 1
    if common < 3:
        return False
    tail_a = " ".join(tokens_a[common:])
    tail_b = " ".join(tokens_b[common:])
    if not tail_a or not tail_b:
        return False
    return fuzz.token_set_ratio(tail_a, tail_b) < 85


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
    if event_a.source == event_b.source:
        # Fuzzy matching is for the same event published by different sources.
        # Within one source, near titles usually mean different shows that
        # share a venue, date or series prefix (e.g. film-festival screenings).
        # Only an exact normalized title is evidence of a duplicate there.
        title_a = normalize_text(strip_title_noise(event_a.title))
        title_b = normalize_text(strip_title_noise(event_b.title))
        if title_a and title_a == title_b:
            return {"kind": "title_fuzzy", "score": 100.0}
        # Municipal truncations ("Patricia Luca - Ahora Solo Faltas Tú." vs
        # "Patricia Lucas") are the same show: accept core-token containment.
        core_score = _core_title_match(event_a, event_b)
        if core_score is not None:
            return {"kind": "title_core", "score": core_score}
        single_score = _single_token_match(event_a, event_b)
        if single_score is not None:
            return {"kind": "title_core", "score": single_score}
        return None
    if _series_prefix_conflict(event_a, event_b):
        return None
    score = title_similarity(event_a.title, event_b.title)
    if score >= threshold:
        return {"kind": "title_fuzzy", "score": round(float(score), 1)}
    core_score = _core_title_match(event_a, event_b)
    if core_score is not None:
        return {"kind": "title_core", "score": core_score}
    prefix_score = _prefix_title_match(event_a, event_b)
    if prefix_score is not None:
        return {"kind": "title_prefix", "score": prefix_score}
    return None


def _event_ref(event):
    return f"{event.source}:{event.source_event_id}"


def cluster_events(events, threshold=DEFAULT_THRESHOLD):
    """Cluster duplicate events; returns a list of clusters with evidence.

    Venue groups gate title matching, but a shared ticket slug joins events
    across venues: the same ticket page is the same event even when one source
    publishes the wrong venue.

    Each cluster: {"venue": canonical id or normalized name,
    "venue_name": display name, "dates": known session dates (union of the
    members), "events": [...], "pairs": [...]}.
    """
    indexed = [
        (position, event) for position, event in enumerate(events) if event.date_start
    ]
    if not indexed:
        return []

    parent = list(range(len(indexed)))
    # A cluster may hold at most one title per source: the same-source rule
    # must also hold transitively, or a cross-source bridge can merge two
    # distinct shows of one source (e.g. two Halloween shows). Strong identity
    # signals (shared ticket slug, core-token containment) still allow the
    # legitimate truncated variants of one show.
    titles = {
        index: {event.source: (normalize_text(strip_title_noise(event.title)), event)}
        for index, event in indexed
    }
    slugs = {
        index: {slug for slug in (extract_slug(event.ticket_url),) if slug}
        for index, event in indexed
    }

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def compatible(left_root, right_root):
        if slugs[left_root] & slugs[right_root]:
            return True
        for source, (title, event) in titles[left_root].items():
            if source not in titles[right_root]:
                continue
            other_title, other_event = titles[right_root][source]
            if other_title == title:
                continue
            slug_left = extract_slug(event.ticket_url)
            slug_right = extract_slug(other_event.ticket_url)
            if slug_left and slug_left == slug_right:
                continue
            if _core_title_match(event, other_event) is not None:
                continue
            if _single_token_match(event, other_event) is not None:
                continue
            return False
        return True

    def union(left, right):
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return True
        if not compatible(root_left, root_right):
            return False
        parent[root_right] = root_left
        titles[root_left] = {**titles[root_left], **titles[root_right]}
        slugs[root_left] = slugs[root_left] | slugs[root_right]
        return True

    pairs = []

    # Cross-venue slug edges: a shared ticket page is the same event.
    by_slug = {}
    for index, event in indexed:
        slug = extract_slug(event.ticket_url)
        if slug:
            by_slug.setdefault(slug, []).append(index)
    for slug, positions in by_slug.items():
        for other in positions[1:]:
            union(positions[0], other)
            pairs.append(
                {
                    "a": _event_ref(indexed[positions[0]][1]),
                    "b": _event_ref(indexed[other][1]),
                    "kind": "ticket_slug",
                    "score": 100.0,
                    "slug": slug,
                }
            )

    # Venue edges: title evidence inside the same canonical venue.
    groups = {}
    for index, event in indexed:
        groups.setdefault(venue_group_key(event), []).append(index)
    for group in groups.values():
        for left_position, left in enumerate(group):
            for right in group[left_position + 1 :]:
                if not _dates_match(indexed[left][1], indexed[right][1]):
                    continue
                evidence = _pair_evidence(indexed[left][1], indexed[right][1], threshold)
                if evidence is None:
                    continue
                if not union(left, right):
                    continue
                pairs.append(
                    {
                        "a": _event_ref(indexed[left][1]),
                        "b": _event_ref(indexed[right][1]),
                        **evidence,
                    }
                )

    components = {}
    for index, event in indexed:
        components.setdefault(find(index), []).append(event)
    clusters = []
    for members in components.values():
        if len(members) < 2:
            continue
        refs = {_event_ref(event) for event in members}
        dates = sorted({date for event in members for date in occurrences_of(event)})
        clusters.append(
            {
                "venue": venue_group_key(members[0]),
                "venue_name": _display_venue(members[0]),
                "dates": dates,
                "events": [event.to_dict() for event in members],
                "pairs": [p for p in pairs if p["a"] in refs and p["b"] in refs],
            }
        )
    return clusters
