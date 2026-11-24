"""Venue registry: canonical ids, display names and alias resolution.

`data/venues.json` holds one entry per real venue with the spellings observed
across sources (`aliases`), plus the address when the corpus exposes it.
`resolve()` maps any raw venue string to `(id, name)`:

1. normalized exact match against every alias;
2. fallback to the part before the first comma (raw strings embed addresses);
3. `None` when the venue is unknown.

`resolve_event()` applies that rule to an event: the venue fields first, then
the title when it names the room after "en"/"at"/"@" ("Max Styler en MUTE",
"Max Styler @MUTE", "Max Styler en MUTE - 5 aniversario").
A city, a zone, a bare route, a brand or an artist name is not a venue, so
such a title adds no evidence.

Resolution is cached per raw string; the registry is loaded once per process.
"""

import json
import re
import unicodedata
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "venues.json"

# A title names the room after one of these prepositions: "Max Styler en MUTE".
# The words need a space after them so they are not matched inside a word;
# "@" does not, because people write the handle glued to it ("@MUTE").
_VENUE_PREPOSITION_RE = re.compile(r"(?:^|\s)(?:(?:en|at)\s+|@\s*)", re.IGNORECASE)
# A phrase continues past the room ("MUTE - 5 aniversario"), so the room is
# the part up to one of these.
_VENUE_SEPARATOR_RE = re.compile(r"[-|,/\u00b7]")
# What follows a preposition may name a clock instead of a room ("@ 23:00").
_CLOCK_OR_NUMBER_RE = re.compile(
    r"^(?:\d{1,2}\s*[:.]\s*\d{2}|\d+)\s*(?:h|hs|hrs)?$", re.IGNORECASE
)
_TRAILING_PUNCTUATION = " \t.,;:!?'\"\u00bb\u201d)]}"

_registry = None
_alias_index = None
_resolve_cache = {}


def normalize_name(value):
    """Casefold, strip accents/punctuation, collapse whitespace."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    ascii_text = ascii_text.casefold()
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _load():
    global _registry, _alias_index
    if _registry is None:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        _registry = payload["venues"]
        _alias_index = {}
        for venue in _registry:
            for alias in venue["aliases"]:
                _alias_index[normalize_name(alias)] = venue
    return _registry, _alias_index


def all_venues():
    """Return every registry entry (loaded lazily from data/venues.json)."""
    return list(_load()[0])


def resolve(raw):
    """Return `(id, name)` for a raw venue string, or None when unknown."""
    if not raw:
        return None
    if raw in _resolve_cache:
        return _resolve_cache[raw]
    _, index = _load()
    venue = index.get(normalize_name(raw))
    if venue is None and "," in raw:
        venue = index.get(normalize_name(raw.split(",", 1)[0]))
    result = (venue["id"], venue["name"]) if venue else None
    _resolve_cache[raw] = result
    return result


def venue_key(raw):
    """Canonical fingerprint: registry id when resolvable, else normalized raw."""
    resolved = resolve(raw)
    if resolved:
        return resolved[0]
    return normalize_name(raw)


def _venue_candidates(title):
    """Yield the phrases a title may name a venue with, in reading order.

    Every preposition ("en", "at", "@") starts a phrase that can run past
    the room -- a time, an event suffix or the city ("MUTE @ 23:00", "MUTE -
    5 aniversario", "MUTE en Mar del Plata") -- so each phrase expands into
    progressively shorter candidates: the whole remainder, the remainder cut
    at the first separator, both with trailing punctuation stripped, and its
    first one to four words. The rightmost preposition is tried first, but a
    phrase that names no registered alias falls back to the one before it,
    because a trailing time or city is not the room. A candidate that looks
    like a clock or a bare number is skipped: those are never rooms.
    """
    if not title:
        return
    for match in reversed(list(_VENUE_PREPOSITION_RE.finditer(title))):
        remainder = title[match.end() :].strip()
        if not remainder:
            continue
        words = remainder.split()
        separator = _VENUE_SEPARATOR_RE.search(remainder)
        candidates = [remainder]
        if separator:
            candidates.append(remainder[: separator.start()])
        for size in range(1, min(4, len(words)) + 1):
            candidates.append(" ".join(words[:size]))
        seen = set()
        for candidate in candidates:
            candidate = candidate.strip().rstrip(_TRAILING_PUNCTUATION).strip()
            key = normalize_name(candidate)
            if not key or key in seen:
                continue
            seen.add(key)
            if _CLOCK_OR_NUMBER_RE.match(candidate):
                continue
            yield candidate


def resolve_event(title=None, venue_name=None, venue_raw=None):
    """Return the `(id, name)` of the venue an event happens in, or None.

    The published venue fields are authoritative. When they carry no venue --
    blank, a city, a zone or a bare route -- the title is venue evidence only
    where it names the room after "en"/"at"/"@" and a candidate phrase there
    matches a registered alias exactly ("Max Styler en MUTE", "MASSANO & KEVIN
    DE VRIES at MUTE", "Max Styler en MUTE - 5 aniversario"). Anything less
    stays unresolved: inventing a venue from a route, a party brand or the
    artist name would mislabel the event.
    """
    for candidate in (venue_name, venue_raw):
        resolved = resolve(candidate)
        if resolved:
            return resolved
    for phrase in _venue_candidates(title):
        resolved = resolve(phrase)
        if resolved:
            return resolved
    return None
