"""Venue registry: canonical ids, display names and alias resolution.

`data/venues.json` holds one entry per real venue with the spellings observed
across sources (`aliases`), plus the address when the corpus exposes it.
`resolve()` maps any raw venue string to `(id, name)`:

1. normalized exact match against every alias;
2. fallback to the part before the first comma (raw strings embed addresses);
3. `None` when the venue is unknown.

`resolve_event()` applies that rule to an event: the venue fields first, then
the title when it names the room after "en"/"at"/"@" ("Max Styler en MUTE").
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
_VENUE_PREPOSITION_RE = re.compile(r"(?:^|\s)(?:en|at|@)\s+(?=\S)", re.IGNORECASE)

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


def _title_venue_mention(title):
    """Return the phrase a title attributes the show to ("... en MUTE")."""
    if not title:
        return None
    mention = None
    for match in _VENUE_PREPOSITION_RE.finditer(title):
        mention = title[match.end() :].strip()
    return mention or None


def resolve_event(title=None, venue_name=None, venue_raw=None):
    """Return the `(id, name)` of the venue an event happens in, or None.

    The published venue fields are authoritative. When they carry no venue --
    blank, a city, a zone or a bare route -- the title is venue evidence only
    where it names the room after "en"/"at"/"@" and that phrase matches a
    registered alias exactly ("Max Styler en MUTE", "MASSANO & KEVIN DE VRIES
    at MUTE"). Anything less stays unresolved: inventing a venue from a route,
    a party brand or the artist name would mislabel the event.
    """
    for candidate in (venue_name, venue_raw):
        resolved = resolve(candidate)
        if resolved:
            return resolved
    return resolve(_title_venue_mention(title))
