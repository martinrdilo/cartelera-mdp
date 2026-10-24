"""Cual Pinta (cualpinta.com) Mar del Plata event collector.

Read-only. `robots.txt` allows the site and points at the sitemap, while the
JSON API and `/_next/` are disallowed, so enumeration goes through the
sitemap:

    GET /sitemap.xml -> every /mar-del-plata/eventos/<slug> URL

Each detail page carries eight `ld+json` blocks; the one whose `@type` is
`Event` holds the dates, venue, price and image. The visible page adds the
category chip (`span.cp-chip`) and the single outbound ticket link (Articket,
Plateanet or the venue's own site). A failing detail is logged to stderr and
skipped; a sitemap failure propagates so the pipeline records the source as
failed.
"""

import json
import re
import sys
import time
from html import unescape
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time
from lib.schema import Event
from lib.sellers import seller_from_url

BASE = "https://www.cualpinta.com"
SITEMAP_URL = f"{BASE}/sitemap.xml"
EVENT_PATH = "/mar-del-plata/eventos/"
SOURCE = "cualpinta"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0

# Categories that are activities, not shows. The site is a cartelera, not a
# community noticeboard, so these are dropped at collect time.
BLOCKED_CATEGORIES = frozenset(
    {
        "Deportes",
        "Gastronomía",
        "Feria",
        "Feria gastronómica",
        "Feria del libro",
        "Seminario",
        "Cursos",
        "Taller",
        "Charlas",
        "Convención y cosplay",
        "Encuentro comunitario",
        "Social",
        "Playa & Outdoor",
        "Cine",
        "Festival de cine",
        "Preestreno",
        "Stand-up",
        "Danza",
        "Teatro",
        "Teatro infantil",
        "Fiesta",
    }
)

# Hosts that are never a ticket vendor: the source itself plus social and
# utility links that appear on every detail page.
_UTILITY_HOSTS = (
    "instagram.com",
    "facebook.com",
    "wa.me",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "google.com",
)
_CANCEL_MARKER = "cancel"
_WHITESPACE_RE = re.compile(r"\s+")
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_TICKET_TEXT_RE = re.compile(r"comprar|entrada|ticket|reserv", re.IGNORECASE)
# The JSON-LD sometimes points at the Auditorium complex while the description
# names the hall ("en la sala Jorge Laureti del Teatro Auditorium").
_SALA_RE = re.compile(
    r"\bsala\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w\s.'’-]{2,40}?)\s+(?:del|de\s+la|de)\b",
    re.IGNORECASE,
)


def _collapsed(node):
    """Whitespace-collapsed text of a BeautifulSoup node."""
    return _WHITESPACE_RE.sub(" ", node.get_text(" ", strip=True)).strip()


def _text(value):
    """Stripped string value, or None when empty/not a string."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _host(url):
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_utility_host(host):
    if host == "cualpinta.com" or host.endswith(".cualpinta.com"):
        return True
    return any(host == blocked or host.endswith("." + blocked) for blocked in _UTILITY_HOSTS)


def parse_sitemap(xml):
    """Return every event URL listed in the sitemap, in document order."""
    urls = []
    for match in _LOC_RE.finditer(xml or ""):
        url = unescape(match.group(1).strip())
        if EVENT_PATH in url:
            urls.append(url)
    return urls


def _json_ld_event(soup):
    """Return the first `ld+json` block whose type is Event."""
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(node.get_text())
        except (TypeError, ValueError):
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("@type")
            if kind == "Event" or (isinstance(kind, list) and "Event" in kind):
                return entry
    return None


def _first_image(image):
    """First URL of a schema.org image value (string, list or ImageObject)."""
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    return _text(image)


def _offer(offers):
    if isinstance(offers, list):
        return next((entry for entry in offers if isinstance(entry, dict)), {})
    return offers if isinstance(offers, dict) else {}


def _category(soup):
    """First category chip that is not a `+18`-style qualifier."""
    for chip in soup.select("span.cp-chip"):
        text = _collapsed(chip)
        if text and not text.startswith("+"):
            return text
    return None


def _ticket_url(soup):
    """Pick the outbound ticket link.

    Priority: a known ticket seller (Articket, Plateanet, Venti, ...), then an
    anchor whose text is a ticket CTA ("Comprar entrada"), then the first
    outbound link that is neither Cual Pinta nor a utility host. The order
    matters because a detail page can carry an artist link (Spotify, the
    venue's site) before the ticket button.
    """
    candidates = []
    for anchor in soup.find_all("a", href=True):
        url = (anchor.get("href") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if _is_utility_host(_host(url)):
            continue
        candidates.append((_collapsed(anchor), url))
    for _, url in candidates:
        if seller_from_url(url):
            return url
    for text, url in candidates:
        if _TICKET_TEXT_RE.search(text):
            return url
    return candidates[0][1] if candidates else None


def parse_detail(html):
    """Parse one event detail page into a JSON-serializable raw record.

    `offers.url` is deliberately ignored: it always points back to the Cual
    Pinta page, so the ticket link only comes from the visible anchors.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    event = _json_ld_event(soup)
    if event is None:
        raise ValueError("Event JSON-LD block not found")

    location = event.get("location")
    location = location if isinstance(location, dict) else {}
    address = location.get("address")
    address = address if isinstance(address, dict) else {}
    offer = _offer(event.get("offers"))

    return {
        "name": _text(event.get("name")) or "",
        "start_date": _text(event.get("startDate")),
        "end_date": _text(event.get("endDate")),
        "event_status": _text(event.get("eventStatus")),
        "venue_name": _text(location.get("name")),
        "street_address": _text(address.get("streetAddress")),
        "description": _text(event.get("description")),
        "price": offer.get("price"),
        "currency": _text(offer.get("priceCurrency")),
        "image_url": _first_image(event.get("image")),
        "url": _text(event.get("url")),
        "category": _category(soup),
        "ticket_url": _ticket_url(soup),
    }


def _fetch_sitemap():
    response = requests.get(
        SITEMAP_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _fetch_detail(url):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return parse_detail(response.text)


def _is_cancelled(status):
    return _CANCEL_MARKER in (status or "").lower()


def collect():
    """Fetch the sitemap, then every detail page at one request per second.

    A sitemap failure propagates (the pipeline records the source as failed).
    A failing detail or a cancelled event is skipped and never drops the rest.
    """
    urls = parse_sitemap(_fetch_sitemap())
    records = []
    skipped = 0
    for index, url in enumerate(urls):
        if index:
            time.sleep(REQUEST_DELAY)
        try:
            record = _fetch_detail(url)
        except Exception as exc:  # network, HTTP, decode or parse errors
            print(f"[cualpinta] detail {url} failed: {exc!r}", file=sys.stderr)
            continue
        if _is_cancelled(record.get("event_status")):
            continue
        if record.get("category") in BLOCKED_CATEGORIES:
            skipped += 1
            continue
        record["source"] = SOURCE
        record["detail_url"] = url
        records.append(record)
    if skipped:
        print(f"[cualpinta] skipped {skipped} non-show categories", file=sys.stderr)
    return records


def _iso_date(value):
    """YYYY-MM-DD prefix of an ISO date-time, or None."""
    value = _text(value)
    return value[:10] if value and len(value) >= 10 else None


def _event_time(start_date):
    value = _text(start_date)
    if not value or "T" not in value:
        return None
    return extract_time(value.split("T", 1)[1])


def _price_value(price):
    if price is None or isinstance(price, bool):
        return None
    if isinstance(price, (int, float)):
        return float(price)
    try:
        return float(str(price).strip())
    except ValueError:
        return None


def _venue_name(record):
    """Prefer the hall named in the description when JSON-LD points at the complex."""
    name = _text(record.get("venue_name")) or ""
    if name.casefold() == "teatro auditorium":
        match = _SALA_RE.search(_text(record.get("description")) or "")
        if match:
            return f"Sala {match.group(1).strip()}"
    return name


def _venue(record):
    """Return (venue_name, venue_raw), appending the street when present."""
    name = _venue_name(record)
    street = _text(record.get("street_address"))
    if name and street:
        return name, f"{name}, {street}"
    if name:
        return name, name
    return "", street or ""


def normalize(records):
    events = []
    for record in records:
        detail_url = _text(record.get("detail_url"))
        date_start = _iso_date(record.get("start_date"))
        date_end = _iso_date(record.get("end_date"))
        # A range only exists when the end date is strictly later; never
        # invent daily occurrences from a range.
        if date_end is None or date_start is None or date_end <= date_start:
            date_end = date_start
        single_day = date_start is not None and date_start == date_end
        price_min = _price_value(record.get("price"))
        ticket_url = _text(record.get("ticket_url"))
        venue_name, venue_raw = _venue(record)
        events.append(
            Event(
                source=SOURCE,
                source_event_id=detail_url.rstrip("/").rsplit("/", 1)[-1] if detail_url else "",
                title=_text(record.get("name")) or "",
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=date_start,
                date_end=date_end,
                occurrences=[date_start] if single_day else [],
                recurrence_unknown=date_start is not None and date_end != date_start,
                time=_event_time(record.get("start_date")),
                is_free=None if price_min is None else price_min == 0,
                price_text=None,
                price_min=price_min,
                currency=_text(record.get("currency")) or ("ARS" if price_min is not None else None),
                ticket_url=ticket_url,
                seller=seller_from_url(ticket_url),
                image_url=_text(record.get("image_url")),
                city="Mar del Plata",
                raw_url=detail_url,
            )
        )
    return events
