"""Qué Hacemos aggregator collector (api.quehacemos.com.ar).

Read-only. Qué Hacemos indexes events published by many sellers, so it is the
only open route observed to inventory from Plateanet, Dogma, Alpogo and
Bandsintown (spec S2).

Discovery enumerates province windows instead of walking one event at a time:
the list endpoint returns the full record (price, link, address, source) but a
per-event detail request measured 0.1-20s with a ~6s average, which made a
130-event run take ~580s. A four-day window answers in ~1.1s and returns every
province record in that range:

    GET /api/v1/events/?province=Buenos Aires
        &date_from=<start>T00:00:00&date_to=<end>T00:00:00&limit=1000

The endpoint has no city filter and no pagination (`offset`, `page` and every
city parameter are ignored), so each window is fetched once; a window that
hits the 1000-record cap is split in half and re-fetched, down to a single day.
Mar del Plata is filtered in the client on the accent-stripped lowercase
`city`, and records shared by overlapping windows are deduplicated by `id`.

Product filter (wave 4, spec S6): keep `recital`, `festival` and `electronica`.
`otro` is kept only when the record's own `link` points to a music seller
(`passline.com`, `getdogma.app`, `alpogo.com`) because the source event_type is
noisy. Every other type is dropped.

`ticket_url` is always null upstream: the ticket URL is derived from `link`
and the seller from its host (a Bandsintown link is an info page, not a
ticket). The source publishes no reliable show time, so `time` stays None
instead of being invented.
"""

import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from lib.schema import Event
from lib.sellers import seller_from_url

SOURCE = "quehacemos"
API_BASE = "https://api.quehacemos.com.ar/api/v1"
EVENT_URL = API_BASE + "/events/{event_id}"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0

# 180 days / 4 = 45 window requests per run (spec S2).
WINDOW_DAYS = 4
HORIZON_DAYS = 180
WINDOW_LIMIT = 1000

MUSIC_TYPES = frozenset({"recital", "festival", "electronica"})
# Seller hosts that make an `otro` musical (spec S6). Enumerated instead of
# taken from lib.sellers so the whitelist stays a product decision of this
# collector; Bandsintown and Plateanet links deliberately do not qualify.
MUSIC_SELLER_HOSTS = ("passline.com", "getdogma.app", "alpogo.com")
CITY_PREFIX = "mar del plata"


def _fetch_json(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    return response.json()


def _today():
    """UTC today, which anchors the first window of the horizon."""
    return datetime.now(timezone.utc).date()


def _window_url(start, end):
    """Build one window request; `end` is an exclusive date boundary."""
    return (
        f"{API_BASE}/events/?province=Buenos%20Aires"
        f"&date_from={start.isoformat()}T00:00:00"
        f"&date_to={end.isoformat()}T00:00:00"
        f"&limit={WINDOW_LIMIT}"
    )


def _normalize_text(value):
    """Lowercase and strip accents so the city filter tolerates spelling."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def _event_type(record):
    return _normalize_text(record.get("event_type")).strip()


def _is_mdp(record):
    return _normalize_text(record.get("city")).strip().startswith(CITY_PREFIX)


def _host(url):
    """Return the host of a URL without the `www.` prefix, else ""."""
    host = (urlparse(url or "").netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_music_seller(link):
    host = _host(link)
    return any(host == domain or host.endswith("." + domain) for domain in MUSIC_SELLER_HOSTS)


def _keep(record):
    """Product filter (S6): music types plus `otro` from a music seller."""
    event_type = _event_type(record)
    if event_type in MUSIC_TYPES:
        return True
    return event_type == "otro" and _is_music_seller(record.get("link"))


def _as_price(value):
    """Return a JSON price as float; anything else is unknown (None)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def collect():
    """Walk the horizon in four-day windows and return the MDP music events.

    A failing window raises so the pipeline records the source as failed
    instead of silently dropping that date range. A window that returns the
    1000-record cap is split in half and re-fetched, recursively down to one
    day; a single day still at the cap is kept and logged to stderr.
    """
    today = _today()
    horizon = today + timedelta(days=HORIZON_DAYS)
    records = []
    seen = set()
    requests_made = 0

    def fetch(start, end):
        nonlocal requests_made
        if requests_made:
            time.sleep(REQUEST_DELAY)
        requests_made += 1
        payload = _fetch_json(_window_url(start, end))
        if not isinstance(payload, list):
            raise ValueError(f"unexpected window payload for {start}..{end}")
        return payload

    def walk(start, end):
        payload = fetch(start, end)
        span_days = (end - start).days
        if len(payload) >= WINDOW_LIMIT and span_days > 1:
            middle = start + timedelta(days=span_days // 2)
            walk(start, middle)
            walk(middle, end)
            return
        if len(payload) >= WINDOW_LIMIT:
            print(
                f"[quehacemos] window {start} still returns {len(payload)}"
                " records at one day; keeping it truncated",
                file=sys.stderr,
            )
        for record in payload:
            event_id = record.get("id")
            if event_id is None or event_id in seen:
                continue
            seen.add(event_id)
            if not _is_mdp(record) or not _keep(record):
                continue
            # Flat API record; `source` names the collector, not the upstream.
            records.append({**record, "source": SOURCE})

    start = today
    while start < horizon:
        end = min(start + timedelta(days=WINDOW_DAYS), horizon)
        walk(start, end)
        start = end
    return records


def normalize(records):
    """Map flat window records to `Event`s."""
    events = []
    for record in records:
        event_id = record.get("id")
        link = (record.get("link") or "").strip() or None
        price = _as_price(record.get("price"))
        date = (record.get("date") or "")[:10] or None
        venue_name = (record.get("venue") or "").strip()
        address = (record.get("address") or "").strip()
        seller = seller_from_url(link)
        events.append(
            Event(
                source=SOURCE,
                source_event_id="" if event_id is None else str(event_id),
                title=(record.get("title") or "").strip(),
                venue_name=venue_name,
                venue_raw=f"{venue_name}, {address}" if address else venue_name,
                date_start=date,
                date_end=date,
                occurrences=[date] if date else [],
                # The source exposes one date per record with no time.
                recurrence_unknown=False,
                time=None,
                is_free=None if price is None else price == 0,
                price_text=None,
                price_min=price,
                currency="ARS" if price is not None else None,
                # Bandsintown links are info pages, not ticket pages.
                ticket_url=link if seller is not None else None,
                seller=seller,
                image_url=record.get("image_url"),
                city="Mar del Plata",
                raw_url=link or EVENT_URL.format(event_id=event_id),
            )
        )
    return events
