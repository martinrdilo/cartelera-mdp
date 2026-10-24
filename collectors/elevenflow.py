"""Eleven Flow (elevenflow.app) Mar del Plata concert agenda collector.

Read-only. The listing is server rendered and carries one anchor per event
(`/events/<slug>`); its two `ItemList` JSON-LD blocks are incomplete (33 of
the 53 events), so the anchors are the enumeration source. Every detail page
carries a `MusicEvent` JSON-LD block next to a `BreadcrumbList`; the event
block supplies the date, venue, price and the canonical page URL, while the
first non-social external anchor supplies the ticket link.

The source sometimes emits an `endDate` earlier than `startDate` (a 20:00
show that "ends" at 00:00 or 01:00 on the same calendar day). `normalize`
trusts `endDate` only when its date is strictly later than the start date;
it never invents daily occurrences for a range.

A failing detail page is logged to stderr and skipped: it never fails the
whole source. A failing listing propagates so the pipeline records the source
as failed.
"""

import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time
from lib.schema import Event
from lib.sellers import seller_from_url

BASE = "https://elevenflow.app"
LIST_URL = f"{BASE}/recitales-en-mar-del-plata"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
SOURCE = "elevenflow"

_EVENT_PATH_RE = re.compile(r"^/events/([^/]+)$")
_SOCIAL_HOSTS = (
    "instagram.com",
    "facebook.com",
    "wa.me",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "google.com",
)


def _text(value):
    """Trim a JSON-LD scalar to a non-empty string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _host_is(url, domain):
    host = (urlparse(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def _is_cancelled(status):
    return bool(status) and "cancel" in str(status).lower()


def parse_listing(html):
    """Return every unique event URL in listing order (query/fragment dropped)."""
    soup = BeautifulSoup(html or "", "html.parser")
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(BASE, href)
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not _EVENT_PATH_RE.match(path):
            continue
        host = (parsed.hostname or "").lower()
        if host not in ("elevenflow.app", "www.elevenflow.app"):
            continue
        canonical = f"{parsed.scheme}://{parsed.netloc}{path}"
        if canonical in seen:
            continue
        seen.add(canonical)
        urls.append(canonical)
    return urls


def _music_event(soup):
    """Pick the MusicEvent payload among a page's JSON-LD blocks."""
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(node.get_text())
        except (TypeError, ValueError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            types = candidate.get("@type")
            types = types if isinstance(types, list) else [types]
            if "MusicEvent" in types:
                return candidate
    raise ValueError("MusicEvent JSON-LD block not found")


def _first_image(value):
    if isinstance(value, dict):
        value = value.get("url")
    if isinstance(value, list):
        value = next((entry for entry in value if isinstance(entry, str) and entry.strip()), None)
    return _text(value)


def _parse_price(value):
    """JSON-LD prices are numbers; tolerate es-AR style numeric strings too."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.,]", "", str(value))
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _offer_fields(offers):
    """Return (lowest price, currency) from a dict or list of offers."""
    if isinstance(offers, dict):
        offers = [offers]
    elif not isinstance(offers, list):
        offers = []
    prices = []
    currency = None
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        currency = currency or _text(offer.get("priceCurrency"))
        price = _parse_price(offer.get("price"))
        if price is not None:
            prices.append(price)
    return (min(prices) if prices else None), currency


def _external_ticket_url(soup):
    """First http(s) anchor that is neither Eleven Flow nor a social/utility host."""
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        if _host_is(href, "elevenflow.app"):
            continue
        if any(_host_is(href, domain) for domain in _SOCIAL_HOSTS):
            continue
        return href
    return None


def parse_detail(html):
    """Parse a detail page into a JSON-serializable raw record (pure)."""
    soup = BeautifulSoup(html or "", "html.parser")
    payload = _music_event(soup)
    location = payload.get("location")
    location = location if isinstance(location, dict) else {}
    address = location.get("address")
    address = address if isinstance(address, dict) else {}
    price, currency = _offer_fields(payload.get("offers"))
    return {
        "name": _text(payload.get("name")),
        "startDate": _text(payload.get("startDate")),
        "endDate": _text(payload.get("endDate")),
        "eventStatus": _text(payload.get("eventStatus")),
        "venue_name": _text(location.get("name")),
        "street_address": _text(address.get("streetAddress")),
        "price": price,
        "currency": currency,
        "image": _first_image(payload.get("image")),
        "url": _text(payload.get("url")),
        "ticket_url": _external_ticket_url(soup),
    }


def _fetch_listing():
    response = requests.get(
        LIST_URL,
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


def collect():
    """Fetch the listing, then each detail page.

    The listing failure propagates (the pipeline marks the source failed).
    A detail failure is logged and skipped without dropping the rest.
    """
    html = _fetch_listing()
    records = []
    for index, url in enumerate(parse_listing(html)):
        if index:
            time.sleep(REQUEST_DELAY)
        try:
            record = _fetch_detail(url)
        except Exception as exc:  # network, HTTP, decode or parse errors
            print(f"[elevenflow] detail {url} failed: {exc!r}", file=sys.stderr)
            continue
        if _is_cancelled(record.get("eventStatus")):
            continue
        record["source"] = SOURCE
        record["raw_url"] = url
        records.append(record)
    return records


def _slug_from_url(url):
    path = urlparse(url or "").path.rstrip("/")
    match = _EVENT_PATH_RE.match(path)
    return match.group(1) if match else ""


def _date_part(value):
    text = (value or "").strip()
    if not text:
        return None
    return text[:10]


def _end_date(start, raw_end):
    """Trust endDate only when its date is strictly later than start."""
    end = _date_part(raw_end)
    if start and end and end > start:
        return end
    return start


def normalize(records):
    events = []
    for record in records:
        if _is_cancelled(record.get("eventStatus")):
            continue
        date_start = _date_part(record.get("startDate"))
        date_end = _end_date(date_start, record.get("endDate"))
        single_day = date_start is not None and date_end == date_start
        venue_name = (record.get("venue_name") or "").strip()
        street = (record.get("street_address") or "").strip()
        if venue_name and street:
            venue_raw = f"{venue_name}, {street}"
        else:
            venue_raw = venue_name or street
        price = _parse_price(record.get("price"))
        # The live corpus emits offers.price = 0 on every event as a
        # placeholder (the page only shows "Comprar entradas"), so a zero is
        # unknown, never free.
        if price == 0:
            price = None
        currency = _text(record.get("currency")) if price is not None else None
        ticket_url = record.get("ticket_url") or None
        raw_url = record.get("raw_url") or record.get("url")
        events.append(
            Event(
                source=SOURCE,
                source_event_id=_slug_from_url(raw_url),
                title=(record.get("name") or "").strip(),
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=date_start,
                date_end=date_end,
                # A real range carries no recurrence info: never invent dates.
                occurrences=[date_start] if single_day else [],
                recurrence_unknown=bool(date_start and date_end and date_start != date_end),
                time=extract_time(record.get("startDate")),
                is_free=None if price is None else price == 0,
                price_text=None,
                price_min=price,
                currency=currency,
                ticket_url=ticket_url,
                seller=seller_from_url(ticket_url),
                image_url=_first_image(record.get("image")),
                city="Mar del Plata",
                raw_url=raw_url,
            )
        )
    return events
