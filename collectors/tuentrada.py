"""TuEntrada collector (tuentrada.com).

Read-only. The search page is server-rendered Next.js HTML: every result card
is an anchor whose subtree holds a `div.items-stretch` with the title, image,
date/time and venue/city. The event page embeds the session list in the RSC
flight payload (`self.__next_f.push([1, "..."])`) as an `eventSessions` array;
the public API behind it requires auth, so the page payload is the source.

A failing detail page never drops the event: the record keeps `detail=None`
and the failure is logged to stderr. A failing search page propagates when no
record was collected yet (the pipeline records the source as failed) and only
stops the remaining queries otherwise, mirroring `collectors.punto`.
"""

import json
import re
import sys
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time
from lib.schema import Event
from lib.venues import normalize_name

BASE = "https://www.tuentrada.com"
SEARCH_URL = f"{BASE}/busqueda"
EVENT_URL = f"{BASE}/{{slug}}"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
QUERIES = ("mar del plata",)
MAX_EVENTS = 30
SOURCE = "tuentrada"

# Raw venue spelling -> canonical display name.
_VENUE_NAMES = {
    "polideportivo mar de plata": "Polideportivo Islas Malvinas",
    "teatro enrique carreras": "Teatro Enrique Carreras",
}

_DATE_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
# One RSC flight push: self.__next_f.push([1,"<JSON string literal>"])
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_SESSIONS_MARKER = '"eventSessions":'
_MDP = "mar del plata"


def _fetch_search(query):
    response = requests.get(
        SEARCH_URL,
        params={"q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _fetch_event(slug):
    response = requests.get(
        EVENT_URL.format(slug=slug),
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return parse_event(response.text)


def _text(node):
    """Whitespace-collapsed text of a node ('' when the node is missing)."""
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _icon_span(card, icon):
    """Descendant span whose svg class list contains `icon` (e.g. 'calendar')."""
    for span in card.find_all("span"):
        svg = span.find("svg")
        if svg is None:
            continue
        if any(icon in name for name in svg.get("class") or []):
            return span
    return None


def _valid_date(match):
    day, month, year = (int(part) for part in match.groups())
    try:
        # Validate through datetime so 31-02 never becomes 2026-02-31.
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_when(text):
    """Return (date_start, date_end, time) for 'DD-MM-YYYY HH:MM hs' ranges."""
    collapsed = " ".join((text or "").split())
    matches = list(_DATE_RE.finditer(collapsed))
    date_start = _valid_date(matches[0]) if matches else None
    date_end = None
    if len(matches) > 1 and " al " in f" {collapsed.lower()} ":
        date_end = _valid_date(matches[1])
    return date_start, date_end, extract_time(collapsed)


def parse_search(html):
    """Parse the server-rendered search page into card records (pure)."""
    soup = BeautifulSoup(html or "", "html.parser")
    records = []
    for anchor in soup.find_all("a", href=True):
        containers = [
            div
            for div in anchor.find_all("div")
            if any("items-stretch" in name for name in div.get("class") or [])
        ]
        if not containers:
            continue
        slug = (anchor.get("href") or "").strip().strip("/")
        if not slug or "/" in slug or slug.startswith("http"):
            continue

        title = _text(anchor.find("h2"))
        date_text = _text(_icon_span(anchor, "calendar"))
        date_start, date_end, time_text = _parse_when(date_text)

        venue_text = _text(_icon_span(anchor, "map-pin"))
        venue, city = venue_text, ""
        if "," in venue_text:
            venue, city = (part.strip() for part in venue_text.rsplit(",", 1))

        image = anchor.find("img")
        records.append(
            {
                "source": SOURCE,
                "slug": slug,
                "title": title,
                "date": date_start,
                "date_end": date_end,
                "time": time_text,
                "venue": venue,
                "city": city,
                "image_url": image.get("src") if image else None,
                "raw_url": EVENT_URL.format(slug=slug),
            }
        )
    return records


def _rsc_text(html):
    """Join every RSC flight push after decoding its JSON string literal."""
    parts = []
    for literal in _PUSH_RE.findall(html or ""):
        try:
            chunk = json.loads(literal)
        except ValueError:
            continue
        if isinstance(chunk, str):
            parts.append(chunk)
    return "".join(parts)


def parse_event(html):
    """Extract the `eventSessions` array from the Next.js RSC payload (pure)."""
    joined = _rsc_text(html)
    marker_at = joined.find(_SESSIONS_MARKER)
    if marker_at == -1:
        return {"sessions": []}
    payload = joined[marker_at + len(_SESSIONS_MARKER) :].lstrip()
    try:
        sessions, _ = json.JSONDecoder().raw_decode(payload)
    except ValueError:
        return {"sessions": []}
    if not isinstance(sessions, list):
        return {"sessions": []}
    return {"sessions": [session for session in sessions if isinstance(session, dict)]}


def _is_mdp(record):
    """Keep cards whose city is Mar del Plata, or whose venue name says so."""
    if normalize_name(record.get("city") or "") == _MDP:
        return True
    return _MDP in normalize_name(record.get("venue") or "")


def collect():
    """Search every query, dedupe by slug, then enrich each card with its detail.

    A search failure on the first query propagates; a later one logs and stops.
    Detail failures only drop the sessions, never the event.
    """
    records = []
    seen = set()
    for index, query in enumerate(QUERIES):
        try:
            html = _fetch_search(query)
        except Exception as exc:  # network, HTTP, decode or parse errors
            if not records:
                raise
            print(f"[tuentrada] search {query!r} failed: {exc!r}", file=sys.stderr)
            break
        for record in parse_search(html):
            slug = record["slug"]
            if slug in seen:
                continue
            seen.add(slug)
            if not _is_mdp(record):
                continue
            records.append(record)
            if len(records) >= MAX_EVENTS:
                break
        if len(records) >= MAX_EVENTS:
            break
        if index < len(QUERIES) - 1:
            time.sleep(REQUEST_DELAY)

    for index, record in enumerate(records):
        if index:
            time.sleep(REQUEST_DELAY)
        slug = record["slug"]
        try:
            detail = _fetch_event(slug)
        except Exception as exc:  # network, HTTP, decode or parse errors
            print(f"[tuentrada] detail {slug} failed: {exc!r}", file=sys.stderr)
            detail = None
        record["detail"] = detail
    return records


def normalize(records):
    """Turn card + RSC sessions into normalized events (one row per date)."""
    events = []
    for record in records:
        detail = record.get("detail") or {}
        sessions = [
            session
            for session in detail.get("sessions") or []
            if isinstance(session, dict)
            and normalize_name(session.get("city") or "") in ("", _MDP)
        ]
        dates = sorted(
            {session["date"][:10] for session in sessions if session.get("date")}
        )
        if dates:
            sessions = sorted(sessions, key=lambda session: session.get("date") or "")
            date = sessions[0].get("date") or ""
            date_time = date[11:16] if len(date) >= 16 else None
            venue = sessions[0].get("venue") or record.get("venue") or ""
            city = sessions[0].get("city") or record.get("city") or ""
            title = record.get("title") or sessions[0].get("name") or ""
            date_start, date_end = dates[0], dates[-1]
            occurrences = dates
            recurrence_unknown = False
        else:
            # The card exposes at most a start/end range; without a detail
            # page there is no recurrence info, so never invent daily dates.
            date_start = record.get("date")
            if not date_start:
                continue
            card_end = record.get("date_end")
            if card_end and card_end != date_start:
                date_end = card_end
                occurrences = []
                recurrence_unknown = True
            else:
                date_end = card_end or date_start
                occurrences = [date_start]
                recurrence_unknown = False
            date_time = record.get("time")
            venue = record.get("venue") or ""
            city = record.get("city") or ""
            title = record.get("title") or ""

        venue_name = _VENUE_NAMES.get(normalize_name(venue), venue)
        venue_raw = f"{venue}, {city}" if city else venue
        events.append(
            Event(
                source=SOURCE,
                source_event_id=record["slug"],
                title=title,
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=date_start,
                date_end=date_end,
                occurrences=occurrences,
                recurrence_unknown=recurrence_unknown,
                time=date_time,
                is_free=None,
                price_text=None,
                price_min=None,
                currency=None,
                ticket_url=record["raw_url"],
                seller="TuEntrada",
                image_url=record.get("image_url"),
                city="Mar del Plata",
                raw_url=record["raw_url"],
            )
        )
    return events
