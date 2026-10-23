"""Venti collector (api.venti.live public home feed).

The feed is a paginated JSON list with no price data. Venti groups Mar del
Plata venues under the city name "Costa Argentina", so the city filter cannot
use `venue.city.name`: it filters by venue coordinates and only falls back to
text (place name, address or event title) when coordinates are missing.

`startDate` is ISO-8601 UTC; dates and times are converted to
America/Argentina/Buenos_Aires before they reach the schema.
"""

import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from lib.schema import Event

SOURCE = "venti"
SELLER = "Venti"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
API_URL = "https://api.venti.live/api/home/events"
TICKET_URL = "https://venti.live/evento/{url_name}"
LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
PAGE_SIZE = 100
REQUEST_DELAY = 1.0
MAX_PAGES = 20

# Mar del Plata bounding box (the city spreads along the coast).
LAT_MIN, LAT_MAX = -38.3, -37.8
LON_MIN, LON_MAX = -57.8, -57.2


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _page_url(page):
    return f"{API_URL}?limit={PAGE_SIZE}&page={page}"


def _fetch_page(page):
    response = requests.get(_page_url(page), headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.json()


def _is_mdp(event):
    """Filter by venue coordinates; use text only when coordinates are absent."""
    venue = event.get("venue")
    if not isinstance(venue, dict):
        venue = {}
    latitude = _as_float(venue.get("latitude"))
    longitude = _as_float(venue.get("longitude"))
    if latitude is not None and longitude is not None:
        return LAT_MIN <= latitude <= LAT_MAX and LON_MIN <= longitude <= LON_MAX
    text = " ".join(
        value
        for value in (venue.get("placeName"), venue.get("readableAddress"), event.get("name"))
        if value
    ).lower()
    return "mar del plata" in text or "mdp" in text


def _local_parts(start_date):
    """Convert an ISO UTC timestamp to (date, HH:MM) in Buenos Aires time."""
    if not start_date:
        return None, None
    try:
        parsed = datetime.fromisoformat(str(start_date).replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(LOCAL_TZ)
    return local.date().isoformat(), local.strftime("%H:%M")


def _record(event, page):
    venue = event.get("venue")
    if not isinstance(venue, dict):
        venue = {}
    venue_name = (venue.get("placeName") or "").strip()
    address = (venue.get("readableAddress") or "").strip()
    if venue_name and address:
        venue_raw = f"{venue_name}, {address}"
    else:
        venue_raw = venue_name or address
    local_date, local_time = _local_parts(event.get("startDate"))
    return {
        "source": SOURCE,
        "source_event_id": str(event.get("id")),
        "title": (event.get("name") or "").strip(),
        "startDate": event.get("startDate"),
        "local_date": local_date,
        "local_time": local_time,
        "venue_name": venue_name,
        "venue_raw": venue_raw,
        "venue": venue,
        "urlName": event.get("urlName") or "",
        "bannerImg": event.get("bannerImg"),
        "promoImg": event.get("promoImg"),
        "raw_url": _page_url(page),
    }


def collect():
    """Fetch pages until `totalPages` (capped at MAX_PAGES), deduping by id.

    A failing page logs to stderr and keeps the records collected so far.
    """
    records = []
    seen = set()
    page = 1
    total_pages = 1
    while page <= min(total_pages, MAX_PAGES):
        if page > 1:
            time.sleep(REQUEST_DELAY)
        try:
            payload = _fetch_page(page)
        except Exception as exc:  # requests errors, JSON errors
            print(f"[venti] page {page} failed: {exc!r}", file=sys.stderr)
            break
        events = payload.get("events") or []
        if payload.get("totalPages") is None:
            total_pages = page + 1 if events else page
        else:
            total_pages = _as_int(payload.get("totalPages"), page)
        for event in events:
            event_id = event.get("id")
            if event_id is None or event_id in seen or not _is_mdp(event):
                continue
            seen.add(event_id)
            records.append(_record(event, page))
        page += 1
    return records


def normalize(records):
    events = []
    for record in records:
        local_date = record.get("local_date")
        url_name = (record.get("urlName") or "").strip()
        events.append(
            Event(
                source=SOURCE,
                source_event_id=record["source_event_id"],
                title=record["title"],
                venue_name=record["venue_name"],
                venue_raw=record["venue_raw"],
                date_start=local_date,
                date_end=local_date,
                occurrences=[local_date] if local_date else [],
                time=record.get("local_time"),
                is_free=None,
                price_text=None,
                price_min=None,
                currency=None,
                ticket_url=TICKET_URL.format(url_name=url_name) if url_name else None,
                seller=SELLER,
                image_url=record.get("bannerImg") or record.get("promoImg"),
                city="Mar del Plata",
                raw_url=record.get("raw_url"),
            )
        )
    return events
