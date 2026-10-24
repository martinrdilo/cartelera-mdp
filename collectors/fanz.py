"""Fanz white-label ticketing collector (entradas.chauvin.com.ar and siblings).

Fanz hosts one Next.js storefront per tenant. Discovery is one request per
tenant: the home page embeds the whole upcoming inventory in
`__NEXT_DATA__` (`props.pageProps.events`). The listing carries no usable
price (`cheapestVisibleTicket` is null on every Chauvin event), so each event
page is fetched for the JSON-LD `Event` block that holds `offers.price`.

`Dates[].start` is UTC even though the tenant timezone is ART, so every start
is converted to UTC-3 before it becomes an occurrence; the human
`Dates[].name` ("viernes, 30 de octubre, 21:00") is the cross-check.

Tenants are curated: adding one is a single `Tenant` entry in `TENANTS`.
A failing tenant home is logged to stderr and skipped; a failing detail keeps
the event with an unknown price. Only a run where every tenant home failed
raises, so the pipeline can record the source as failed.
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import requests
from bs4 import BeautifulSoup

from lib.schema import Event

USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
ART = timezone(timedelta(hours=-3))
DEFAULT_CURRENCY = "ARS"
CITY = "Mar del Plata"

# Keys that can hold a price inside a JSON-LD `offers` value (number, list of
# offers, or a nested object such as {"value": 15000}).
_PRICE_KEYS = ("price", "lowPrice", "value", "amount", "priceSpecification", "offers")


class Tenant(NamedTuple):
    """One Fanz white-label storefront."""

    source: str
    base_url: str
    seller: str
    default_venue: str

    @property
    def home_url(self):
        return self.base_url.rstrip("/") + "/"

    def event_url(self, slug):
        return f"{self.base_url.rstrip('/')}/event/{slug}"


# Curated on 2026-10-24: Chauvin is the only Fanz tenant whose Mar del Plata
# inventory is mostly music. septimofuego.com and espaciocuatroelementos.com
# were measured and are almost entirely theatre, so they stay out of scope.
TENANTS = (
    Tenant(
        source="chauvin",
        base_url="https://entradas.chauvin.com.ar",
        seller="Chauvin",
        default_venue="Chauvin Centro de creación",
    ),
)


def _fetch(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def _script_json(script):
    text = script.string if script.string is not None else script.get_text()
    return json.loads(text)


def _next_data(html):
    """Return the parsed Next.js payload of a page, or raise ValueError."""
    soup = BeautifulSoup(html or "", "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        raise ValueError("__NEXT_DATA__ script not found")
    try:
        return _script_json(script)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc


def parse_home(html):
    """Return the tenant's upcoming event nodes from its home page (pure)."""
    payload = _next_data(html)
    page_props = {}
    if isinstance(payload, dict):
        page_props = (payload.get("props") or {}).get("pageProps") or {}
    events = page_props.get("events") if isinstance(page_props, dict) else None
    if not isinstance(events, list):
        raise ValueError("pageProps.events is missing or not a list")
    return events


def _event_json_ld(html):
    """Return the first JSON-LD node typed `Event`, or raise ValueError."""
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = _script_json(script)
        except (TypeError, ValueError):
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Event" in types:
                return node
    raise ValueError("Event JSON-LD not found")


def _numeric_prices(value):
    """Yield every numeric price found inside a JSON-LD `offers` value."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for key in _PRICE_KEYS:
            if key in value:
                yield from _numeric_prices(value[key])
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _numeric_prices(item)


def _currency(value):
    """Return the first `priceCurrency` declared inside `offers`, if any."""
    if isinstance(value, dict):
        currency = value.get("priceCurrency")
        if isinstance(currency, str) and currency.strip():
            return currency.strip().upper()
        for key in ("offers", "priceSpecification"):
            found = _currency(value.get(key))
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _currency(item)
            if found:
                return found
    return None


def parse_detail(html):
    """Return {"price", "currency"} from an event page's JSON-LD (pure).

    `price` is the cheapest numeric price found; None when the page exposes
    no offer, which is a valid "price unknown" result and not a parse error.
    """
    offers = _event_json_ld(html).get("offers")
    prices = list(_numeric_prices(offers))
    return {
        "price": min(prices) if prices else None,
        "currency": _currency(offers),
    }


def _slug(event):
    return str(event.get("slug") or "").strip()


def _date_record(node):
    if not isinstance(node, dict):
        return {
            "start": None,
            "end": None,
            "name": None,
            "sold_out": False,
            "tickets_left": None,
        }
    return {
        "start": node.get("start"),
        "end": node.get("end"),
        "name": node.get("name"),
        "sold_out": bool(node.get("isSoldOut")),
        "tickets_left": node.get("ticketsLeft"),
    }


def _record(event, tenant, url, detail):
    """Merge one listing node with its detail payload into a raw record."""
    location = event.get("Location") or {}
    category = event.get("Category") or {}
    return {
        "source": tenant.source,
        "event_id": event.get("id"),
        "slug": _slug(event),
        "title": (event.get("title") or "").strip(),
        "category": (category.get("name") or "").strip() or None,
        "dates": [_date_record(node) for node in (event.get("Dates") or [])],
        "venue_name": (location.get("locationName") or "").strip(),
        "tenant_venue": tenant.default_venue,
        "seller": tenant.seller,
        "image_url": event.get("banner") or None,
        "ticket_url": url,
        "raw_url": url,
        "detail": detail,
    }


def collect():
    """Fetch every curated tenant home, then every event page it lists.

    Tenant and detail failures are logged to stderr and skipped; a detail
    failure still yields the event, with `detail=None` (price unknown). When
    every tenant home fails the last error is raised so the pipeline can mark
    the source as failed; a tenant with no events is a valid result.
    """
    records = []
    fetched = 0
    last_error = None
    requests_made = 0
    for tenant in TENANTS:
        if requests_made:
            time.sleep(REQUEST_DELAY)
        requests_made += 1
        try:
            events = parse_home(_fetch(tenant.home_url))
        except Exception as exc:  # network, HTTP, decode or payload errors
            last_error = exc
            print(f"[fanz] tenant {tenant.source} home failed: {exc!r}", file=sys.stderr)
            continue
        fetched += 1
        for event in events:
            slug = _slug(event) if isinstance(event, dict) else ""
            if not slug:
                print("[fanz] listing entry without a slug skipped", file=sys.stderr)
                continue
            url = tenant.event_url(slug)
            time.sleep(REQUEST_DELAY)
            requests_made += 1
            detail = None
            try:
                detail = parse_detail(_fetch(url))
            except Exception as exc:  # network, HTTP, decode or parse errors
                print(f"[fanz] detail {url} failed: {exc!r}", file=sys.stderr)
            records.append(_record(event, tenant, url, detail))
    if not fetched and last_error is not None:
        raise last_error
    return records


def _local_start(value):
    """Parse an ISO-8601 start and return it in ART, or None when invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ART)


def _label(record):
    return record.get("event_id") or record.get("slug") or record.get("title") or "?"


def _local_starts(record):
    """Return every start in ART, or None after logging why the event is skipped."""
    dates = record.get("dates")
    if not dates:
        print(f"[fanz] event {_label(record)} skipped: no dates", file=sys.stderr)
        return None
    starts = []
    for node in dates:
        start = node.get("start") if isinstance(node, dict) else None
        local = _local_start(start)
        if local is None:
            print(
                f"[fanz] event {_label(record)} skipped: unparseable start {start!r}",
                file=sys.stderr,
            )
            return None
        starts.append(local)
    return starts


def _price(record):
    detail = record.get("detail") or {}
    value = detail.get("price")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_event_id(record):
    event_id = record.get("event_id")
    if event_id is not None and str(event_id).strip():
        return str(event_id).strip()
    return str(record.get("slug") or "").strip()


def normalize(records):
    """Turn raw Fanz records into Events; events without usable dates are skipped."""
    events = []
    for record in records:
        starts = _local_starts(record)
        if starts is None:
            continue
        occurrences = sorted({start.date().isoformat() for start in starts})
        earliest = min(starts)
        price = _price(record)
        detail = record.get("detail") or {}
        venue_name = (
            record.get("venue_name") or record.get("tenant_venue") or ""
        ).strip()
        url = record.get("ticket_url") or record.get("raw_url")
        events.append(
            Event(
                source=record.get("source") or "",
                source_event_id=_source_event_id(record),
                title=(record.get("title") or "").strip(),
                venue_name=venue_name,
                venue_raw=venue_name,
                date_start=occurrences[0],
                date_end=occurrences[-1],
                occurrences=occurrences,
                recurrence_unknown=False,
                time=earliest.strftime("%H:%M"),
                is_free=None if price is None else price == 0,
                price_text=None,
                price_min=price,
                currency=(
                    (detail.get("currency") or DEFAULT_CURRENCY)
                    if price is not None
                    else None
                ),
                ticket_url=url,
                seller=record.get("seller"),
                image_url=record.get("image_url"),
                city=CITY,
                raw_url=record.get("raw_url") or url,
            )
        )
    return events
