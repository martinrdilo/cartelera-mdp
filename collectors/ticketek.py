"""Ticketek Argentina collector.

Ticketek exposes a JSON search endpoint plus one CMS "node" per artist page.
The search result groups several shows under one artist, so the Mar del Plata
filter runs per show. Each show's node carries schema.org Event objects in
`google_structured_data`, which is where prices and every session date live.
"""

import re
import sys
import time
import unicodedata
from datetime import date
from urllib.parse import quote

import requests

from lib.schema import Event

SOURCE = "ticketek"
SELLER = "Ticketek"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
SEARCH_URL = "https://prod-cms-search.ticketek.com.ar/api/1.1/search/mar%20del%20plata"
NODE_URL = "https://prod-cms-api.ticketek.com.ar/api/1.0/"
CITY = "Mar del Plata"
_START_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?")


def _slug(value):
    """Lowercase, accent-stripped, hyphenated slug used in node paths."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _node_path(result_url, venue):
    """Build the CMS node path from a search result.

    Artist URLs with a slash already identify the venue (`dillom/bendu-arena`);
    a bare artist slug needs the venue appended (`abel-pintos` +
    `Teatro Tronador` -> `abel-pintos--teatro-tronador`).
    """
    result_url = (result_url or "").strip().strip("/")
    if "/" in result_url:
        return result_url.replace("/", "--")
    if result_url:
        venue_slug = _slug(venue)
        return f"{result_url}--{venue_slug}" if venue_slug else result_url
    return _slug(venue)


def _fetch_search():
    response = requests.get(SEARCH_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.json()


def _fetch_node(path):
    node = quote(f"node?path={path}", safe="")
    response = requests.get(NODE_URL + node, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.json()


def _offers(item):
    offers = item.get("offers")
    if isinstance(offers, list):
        return offers[0] if offers and isinstance(offers[0], dict) else {}
    return offers if isinstance(offers, dict) else {}


def _ticket_url(node):
    items = node.get("google_structured_data") or []
    if not items or not isinstance(items[0], dict):
        return None
    url = _offers(items[0]).get("url")
    return url.strip() if isinstance(url, str) and url.strip() else None


def _page_url(result_url):
    result_url = (result_url or "").strip().strip("/")
    return f"https://www.ticketek.com.ar/{result_url}" if result_url else SEARCH_URL


def collect():
    """Fetch the search page and one node per MDP show path.

    Nodes are cached by path (several shows can share an artist page) and
    fetched politely at ~1 req/s. A failing node only drops its own show.
    """
    payload = _fetch_search()
    nodes = {}
    records = []
    made_request = True
    for result in payload.get("resultados") or []:
        result_url = result.get("url") or ""
        for show in result.get("shows") or []:
            if (show.get("lugar") or "").strip() != CITY:
                continue
            path = _node_path(result_url, show.get("venue") or "")
            if not path:
                continue
            if path not in nodes:
                if made_request:
                    time.sleep(REQUEST_DELAY)
                try:
                    nodes[path] = _fetch_node(path)
                except Exception as exc:  # network, HTTP or decode errors
                    print(f"[ticketek] node {path} failed: {exc!r}", file=sys.stderr)
                    nodes[path] = None
                made_request = True
            node = nodes[path]
            if node is None:
                continue
            ticket_url = _ticket_url(node)
            records.append(
                {
                    "source": SOURCE,
                    "seller": SELLER,
                    "search": result,
                    "show": show,
                    "node_path": path,
                    "node": node,
                    "raw_url": ticket_url or _page_url(result_url),
                }
            )
    return records


def _parse_start(value):
    """Return (ISO local date, HH:MM) from a schema.org startDate."""
    match = _START_RE.match((value or "").strip())
    if not match:
        return None, None
    day_text, time_text = match.groups()
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        return None, None
    if time_text:
        hour, minute = (int(part) for part in time_text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            time_text = None
    return day.isoformat(), time_text


def _parse_price(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _image_url(value):
    """schema.org image can be a string, a list or an ImageObject."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        return next((url for item in value if (url := _image_url(item))), None)
    if isinstance(value, dict):
        return _image_url(value.get("url") or value.get("contentUrl"))
    return None


def normalize(records):
    """Turn raw search+node records into Events; drop records without dates."""
    events = []
    for record in records:
        node = record.get("node") or {}
        items = node.get("google_structured_data") or []
        if not items:
            continue
        dated = []
        for item in items:
            if not isinstance(item, dict):
                continue
            day, _ = _parse_start(item.get("startDate"))
            if day:
                dated.append((day, item))
        if not dated:
            continue

        occurrences = sorted({day for day, _ in dated})
        first = dated[0][1]
        search = record.get("search") or {}
        show = record.get("show") or {}

        location = first.get("location") if isinstance(first.get("location"), dict) else {}
        address = location.get("address") if isinstance(location.get("address"), dict) else {}
        venue_name = (location.get("name") or show.get("venue") or "").strip()
        street = (address.get("streetAddress") or "").strip()
        venue_raw = ", ".join(part for part in (venue_name, street) if part)

        prices = []
        currency = None
        for item in items:
            if not isinstance(item, dict):
                continue
            offers = _offers(item)
            price = _parse_price(offers.get("price"))
            if price is not None:
                prices.append(price)
            if currency is None and offers.get("priceCurrency"):
                currency = offers["priceCurrency"]
        price_min = min(prices) if prices else None

        ticket_url = _offers(first).get("url")
        ticket_url = ticket_url.strip() if isinstance(ticket_url, str) and ticket_url.strip() else None
        image_url = _image_url(search.get("imagenHorizontal") or search.get("imagen") or first.get("image"))
        if image_url and image_url.startswith("//"):
            image_url = "https:" + image_url
        _, time_text = _parse_start(first.get("startDate"))

        events.append(
            Event(
                source=SOURCE,
                source_event_id=node.get("showcode") or show.get("showcode") or "",
                title=(first.get("name") or node.get("title") or search.get("titulo") or "").strip(),
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=occurrences[0],
                date_end=occurrences[-1],
                occurrences=occurrences,
                time=time_text,
                is_free=None if price_min is None else price_min == 0,
                price_text=f"Desde ${int(price_min)}" if price_min is not None else None,
                price_min=price_min,
                currency=currency or "ARS",
                ticket_url=ticket_url,
                seller=SELLER,
                image_url=image_url,
                city=CITY,
                raw_url=record.get("raw_url") or ticket_url,
            )
        )
    return events
