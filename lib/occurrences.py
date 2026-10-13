"""Occurrence expansion for multi-date events (pure logic).

Municipal ranges (rule documented in REPORT.md §3): a schedule is a list of
segments, each one a desde/hasta range plus the weekdays the event runs
(e.g. "sabado 21:00 domingo 21:00"). Rule:

- a segment with weekdays expands to one occurrence per matching weekday
  inside its range;
- a single-day segment is an exact date and is kept even without weekdays;
- a multi-day segment without weekdays has no recurrence info: never invent
  dates, keep the start/end range and flag `recurrence_unknown`.

Articket detail pages list every dated session in the `fechas_evento`
<select>; the JSON-LD block only exposes startDate/endDate, so the select is
the primary source and JSON-LD is the fallback (first date only, flagged
incomplete when endDate differs).
"""

import json
import re
import unicodedata
from datetime import date, timedelta

WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_SELECT_RE = re.compile(r"<select[^>]*name=[\"']fechas_evento[\"'].*?</select>", re.IGNORECASE | re.DOTALL)
_OPTION_RE = re.compile(r"<option[^>]*>(.*?)</option>", re.IGNORECASE | re.DOTALL)
_LD_JSON_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_OPTION_DATE_RE = re.compile(r"(\d{1,2})\s+(\d{1,2})\s+(\d{4})")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _strip_accents(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def parse_weekdays(text):
    """Return the set of weekday indexes (Monday=0) named in text."""
    if not text:
        return set()
    normalized = _strip_accents(text).lower()
    return {index for name, index in WEEKDAYS.items() if re.search(rf"\b{name}\b", normalized)}


def expand_span(start, end, weekdays):
    """One date per matching weekday inside [start, end]."""
    dates = []
    current = start
    while current <= end:
        if current.weekday() in weekdays:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def expand_segments(segments):
    """Expand municipal schedule segments to (occurrences, recurrence_unknown).

    `segments` are dicts with date `start`/`end` and a `weekdays` set of
    indexes (Monday=0). Occurrences come back as sorted ISO strings.
    """
    occurrences = []
    recurrence_unknown = False
    for segment in segments:
        start, end = segment["start"], segment["end"]
        weekdays = segment.get("weekdays") or set()
        if weekdays:
            dates = expand_span(start, end, weekdays)
            if start != end and not dates:
                # The source lists weekdays but none falls inside the range:
                # do not guess, flag the range instead.
                recurrence_unknown = True
            occurrences.extend(dates)
        elif start == end:
            occurrences.append(start)
        else:
            recurrence_unknown = True
    return [value.isoformat() for value in sorted(set(occurrences))], recurrence_unknown


def parse_articket_option(text):
    """Parse an Articket select option ("05 11 2026, 21:00hs") to an ISO date."""
    match = _OPTION_DATE_RE.search(text or "")
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_jsonld_dates(html):
    for block in _LD_JSON_RE.findall(html or ""):
        try:
            payload = json.loads(block)
        except (TypeError, ValueError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            is_event = item_type == "Event" or (isinstance(item_type, list) and "Event" in item_type)
            if not is_event:
                continue
            start_match = _ISO_DATE_RE.search(str(item.get("startDate") or ""))
            if not start_match:
                continue
            start = start_match.group(0)
            end_match = _ISO_DATE_RE.search(str(item.get("endDate") or ""))
            complete = not end_match or end_match.group(0) == start
            return {"dates": [start], "complete": complete}
    return {"dates": [], "complete": False}


def extract_articket_detail(html):
    """Extract every dated session from an Articket detail page.

    Returns `{"dates": sorted ISO list, "complete": bool}`. The select is
    authoritative; JSON-LD is the fallback.
    """
    select_match = _SELECT_RE.search(html or "")
    if select_match:
        dates = []
        for option in _OPTION_RE.findall(select_match.group(0)):
            parsed = parse_articket_option(re.sub(r"<[^>]+>", " ", option))
            if parsed:
                dates.append(parsed)
        if dates:
            return {"dates": sorted(set(dates)), "complete": True}
    return _extract_jsonld_dates(html)
