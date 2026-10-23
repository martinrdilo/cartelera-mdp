"""Bombo collector (wearebombo.com) for Mar del Plata electronic events.

The search endpoint returns a JSON list of events; each detail page embeds a
schema.org MusicEvent JSON-LD block with the venue, organizer, image and
offers. The API timestamps already carry the local -03:00 offset, so date and
time are read exactly as published (no UTC conversion).

A detail-page failure never drops an event: the search record is kept with the
search place name, no price and a stderr log.
"""

import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from lib.schema import Event

BASE_URL = "https://wearebombo.com"
SEARCH_URL = f"{BASE_URL}/api/eventos/buscar"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
SOURCE = "bombo"
SELLER = "Bombo"
CITY = "Mar del Plata"
SEARCH_QUERY = "mar del plata"
REQUEST_DELAY = 1.0

MUTE_VENUE = "Mute Club de Mar"
COUNTY_VENUE = "The County Music"
_MUTE_ADDRESS_HINT = "ruta 11 alfar"
_MUTE_ORGANIZER_HINT = "mute"
_COUNTY_HINT = "the county"
# Bombo lists parking as an InStock offer on some events. It is an add-on, not
# admission, so it must not become the event's "Desde" price.
_ADDON_OFFER_HINTS = ("parking", "estacionamiento")
# Ticket bundles are products, not a single dated event. Bombo sells a
# "Poker Pass" for four Mute dates; it must not become a calendar row.
_EXCLUDED_PRODUCT_HINTS = ("poker pass",)

_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2}))?")


def _detail_url(href):
    href = (href or "").strip()
    if href.startswith(("http://", "https://")):
        return href
    return BASE_URL + (href if href.startswith("/") else "/" + href)


def _iter_jsonld(payload):
    """Yield every dict in a JSON-LD payload, including @graph members."""
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_jsonld(item)
        return
    if not isinstance(payload, dict):
        return
    yield payload
    graph = payload.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _iter_jsonld(item)


def _is_event(node):
    node_type = node.get("@type")
    if isinstance(node_type, str):
        node_type = [node_type]
    if not isinstance(node_type, list):
        return False
    return any(value in ("Event", "MusicEvent") for value in node_type)


def _parse_detail_html(html):
    """Return the first Event/MusicEvent JSON-LD object in a detail page."""
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string if script.string is not None else script.get_text()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for node in _iter_jsonld(payload):
            if _is_event(node):
                return node
    return None


def _fetch_search():
    response = requests.get(
        SEARCH_URL,
        params={"q": SEARCH_QUERY},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _fetch_detail(href):
    url = _detail_url(href)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    detail = _parse_detail_html(response.text)
    if detail is None:
        raise ValueError(f"no Event JSON-LD at {url}")
    return detail


def _is_mdp(place_name):
    return "mar del plata" in (place_name or "").lower()


def collect():
    """Fetch the search list, then each MDP detail; detail errors are tolerated."""
    records = []
    first_detail = True
    for item in _fetch_search():
        if not isinstance(item, dict) or not _is_mdp(item.get("placeName")):
            continue
        name = (item.get("name") or "").lower()
        if any(hint in name for hint in _EXCLUDED_PRODUCT_HINTS):
            continue
        href = (item.get("href") or "").strip()
        detail = None
        if href:
            if not first_detail:
                time.sleep(REQUEST_DELAY)
            first_detail = False
            try:
                detail = _fetch_detail(href)
            except Exception as exc:  # network, HTTP, JSON-LD or decode errors
                print(f"[bombo] detail {href} failed: {exc!r}", file=sys.stderr)
            else:
                if detail is None:
                    print(f"[bombo] detail {href} returned no Event JSON-LD", file=sys.stderr)
        record = dict(item)
        record["source"] = SOURCE
        record["detail"] = detail
        records.append(record)
    return records


def _as_text(value):
    return str(value).strip() if value is not None else ""


def _name_of(value):
    """Return a schema.org name from a dict, list or plain string."""
    if isinstance(value, dict):
        return _as_text(value.get("name"))
    if isinstance(value, list):
        return " ".join(name for name in (_name_of(item) for item in value) if name)
    return _as_text(value)


def _street_address(detail):
    location = detail.get("location")
    if isinstance(location, list):
        location = next((item for item in location if isinstance(item, dict)), None)
    if not isinstance(location, dict):
        return None
    address = location.get("address")
    if isinstance(address, dict):
        return _as_text(address.get("streetAddress")) or None
    if isinstance(address, str):
        return address.strip() or None
    return None


def _venue(title, organizer, street):
    if _MUTE_ADDRESS_HINT in (street or "").lower() or _MUTE_ORGANIZER_HINT in organizer.lower():
        return MUTE_VENUE
    haystack = f"{title} {organizer}".lower()
    if _COUNTY_HINT in haystack:
        return COUNTY_VENUE
    return organizer or "Mar del Plata"


def _to_price(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        digits = re.sub(r"[^\d]", "", text)
        return float(digits) if digits else None


def _is_addon(offer):
    name = _as_text(offer.get("name")).lower()
    return any(hint in name for hint in _ADDON_OFFER_HINTS)


def _select_offer(offers):
    """Pick the cheapest available admission offer.

    InStock wins; when nothing is in stock the contract falls back to all
    offers. Parking add-ons only win when there is no admission offer at all.
    """
    if isinstance(offers, dict):
        offers = [offers]
    parsed = []
    for offer in offers or []:
        if not isinstance(offer, dict):
            continue
        price = _to_price(offer.get("price"))
        if price is None:
            continue
        parsed.append((price, offer))
    in_stock = [
        pair for pair in parsed if "instock" in _as_text(pair[1].get("availability")).lower()
    ]
    admission = [pair for pair in parsed if not _is_addon(pair[1])]
    in_stock_admission = [pair for pair in in_stock if not _is_addon(pair[1])]
    candidates = in_stock_admission or in_stock or admission or parsed
    if not candidates:
        return None, None
    price, offer = min(candidates, key=lambda pair: pair[0])
    currency = _as_text(offer.get("priceCurrency")) or "ARS"
    return price, currency


def _local_date_time(value):
    """Split an ISO timestamp into its published local date and HH:MM."""
    match = _TIMESTAMP_RE.match(_as_text(value))
    if not match:
        return None, None
    date_part, hour, minute = match.groups()
    time_part = f"{hour}:{minute}" if hour is not None and minute is not None else None
    return date_part, time_part


def _image_url(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            url = _image_url(item)
            if url:
                return url
        return None
    if isinstance(value, dict):
        return _image_url(value.get("url") or value.get("contentUrl"))
    return None


def normalize(records):
    events = []
    for record in records:
        detail = record.get("detail")
        if not isinstance(detail, dict):
            detail = None
        search_title = _as_text(record.get("name"))
        title = (_as_text(detail.get("name")) if detail else "") or search_title
        href = _as_text(record.get("href"))
        ticket_url = _detail_url(href) if href else None
        place_name = _as_text(record.get("placeName")) or "Mar del Plata"

        if detail:
            organizer = _name_of(detail.get("organizer"))
            street = _street_address(detail)
            venue_name = _venue(title, organizer, street)
            venue_raw = street
            date_start, time_value = _local_date_time(
                detail.get("startDate") or record.get("dateTime")
            )
            image_url = _image_url(detail.get("image")) or _image_url(record.get("imageUrl"))
            price_min, currency = _select_offer(detail.get("offers"))
        else:
            # Detail failed: keep the search record, with no price or venue detail.
            venue_name = place_name
            venue_raw = None
            date_start, time_value = _local_date_time(record.get("dateTime"))
            image_url = _image_url(record.get("imageUrl"))
            price_min, currency = None, None

        price_text = f"Desde ${int(price_min)}" if price_min is not None else None
        is_free = price_min == 0 if price_min is not None else None
        events.append(
            Event(
                source=SOURCE,
                source_event_id=_as_text(record.get("id")),
                title=title,
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=date_start,
                date_end=date_start,
                occurrences=[date_start] if date_start else [],
                time=time_value,
                is_free=is_free,
                price_text=price_text,
                price_min=price_min,
                currency=currency,
                ticket_url=ticket_url,
                seller=SELLER,
                image_url=image_url,
                city=CITY,
                raw_url=ticket_url,
            )
        )
    return events
