"""Punto Mar del Plata agenda collector (puntomardelplata.com).

Read-only. The music agenda is open JSON:

    GET /api/actividades?soloVigentes=true&orden=desde&pagina=N&tamano=12&categoria=1

Pagination stops at `totalPaginas` (or MAX_PAGES). Each item links to a
detail page whose `<script id="schema-event">` JSON-LD Event carries an
`offers` entry (object or list) with the ticket URL and sometimes a price;
the seller is derived from the ticket host. A failing detail page never
drops the event: the record keeps `detail=None` and the failure is logged
to stderr.
"""

import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time
from lib.schema import Event
from lib.sellers import seller_from_url

BASE = "https://puntomardelplata.com"
LIST_URL = f"{BASE}/api/actividades"
DETAIL_URL = f"{BASE}/actividades/{{slug}}"
IMAGE_URL = f"{BASE}/recursos/actividades/{{year}}/{{foto}}"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
MAX_PAGES = 20
PAGE_SIZE = 12
CATEGORY_ID = "1"
SOURCE = "punto"

# Ticket host -> seller lives in lib/sellers.py so every collector shares it.
_YEAR_RE = re.compile(r"^\d{4}$")


def _fetch_page(page):
    response = requests.get(
        LIST_URL,
        params={
            "soloVigentes": "true",
            "orden": "desde",
            "pagina": page,
            "tamano": PAGE_SIZE,
            "categoria": CATEGORY_ID,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _fetch_detail(slug):
    response = requests.get(
        DETAIL_URL.format(slug=slug),
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return parse_detail(response.text)


def _parse_price(raw):
    """'25000' / '25.000' / '$ 25.000,50' -> float (es-AR separators)."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^\d.,]", "", str(raw))
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
    """Return (ticket_url, seller, price_min, price_text, currency)."""
    if isinstance(offers, dict):
        offers = [offers]
    offers = [offer for offer in (offers or []) if isinstance(offer, dict)]
    ticket_url = None
    for offer in offers:
        url = str(offer.get("url") or "").strip()
        if url:
            ticket_url = url
            break
    priced = []
    currency = None
    for offer in offers:
        value = _parse_price(offer.get("price"))
        if value is not None:
            priced.append((value, str(offer["price"]).strip()))
        currency = currency or offer.get("priceCurrency")
    price_min = None
    price_text = None
    if priced:
        price_min, raw_text = min(priced, key=lambda item: item[0])
        price_text = raw_text if raw_text.startswith("$") else f"${raw_text}"
        currency = currency or "ARS"
    return ticket_url, seller_from_url(ticket_url), price_min, price_text, currency


def parse_detail(html):
    """Parse the schema-event JSON-LD block into ticket fields (pure, testable)."""
    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.find("script", id="schema-event")
    if node is None:
        raise ValueError("schema-event JSON-LD block not found")
    payload = json.loads(node.get_text())
    if isinstance(payload, list):
        payload = next((entry for entry in payload if isinstance(entry, dict)), {})
    ticket_url, seller, price_min, price_text, currency = _offer_fields(payload.get("offers"))
    return {
        "ticket_url": ticket_url,
        "seller": seller,
        "price_min": price_min,
        "price_text": price_text,
        "currency": currency,
    }


def collect():
    """Fetch every listing page, then enrich each item with its detail page.

    A failure on the first listing page propagates (the pipeline records the
    source as failed); a later page keeps what was already collected. Detail
    failures only drop the ticket fields, never the event.
    """
    records = []
    page = 1
    while page <= MAX_PAGES:
        try:
            payload = _fetch_page(page)
        except Exception as exc:  # network, HTTP, decode or JSON errors
            if not records:
                raise
            print(f"[punto] page {page} failed: {exc!r}", file=sys.stderr)
            break
        items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
        records.extend({"source": SOURCE, **item} for item in items)
        total_pages = payload.get("totalPaginas") or 1
        if not items or page >= total_pages:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    for index, record in enumerate(records):
        if index:
            time.sleep(REQUEST_DELAY)
        slug = (record.get("slug") or "").strip()
        try:
            detail = _fetch_detail(slug)
        except Exception as exc:  # network, HTTP, decode or parse errors
            print(f"[punto] detail {slug} failed: {exc!r}", file=sys.stderr)
            detail = None
        record["detail"] = detail
    return records


def _venue(record):
    """Venue name from locacionNombre, else the first comma segment of `lugar`."""
    raw = (record.get("lugar") or "").strip()
    name = (record.get("locacionNombre") or "").strip()
    if not name:
        name = raw.split(",")[0].strip()
    return name, raw or name


def _image_url(record, date_start):
    foto = (record.get("foto") or "").strip()
    if not foto or not date_start:
        return None
    year = date_start[:4]
    if not _YEAR_RE.match(year):
        return None
    return IMAGE_URL.format(year=year, foto=foto)


def normalize(records):
    events = []
    for record in records:
        detail = record.get("detail") or {}
        ticket_url = detail.get("ticket_url")
        price_min = detail.get("price_min")
        date_start = (record.get("desde") or "").strip() or None
        date_end = (record.get("hasta") or "").strip() or date_start
        single_day = date_start is not None and date_start == date_end
        venue_name, venue_raw = _venue(record)
        codigo = record.get("codigo")
        events.append(
            Event(
                source=SOURCE,
                source_event_id=str(codigo) if codigo is not None else "",
                title=(record.get("titulo") or "").strip(),
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=date_start,
                date_end=date_end,
                # A range carries no recurrence info: never invent daily dates.
                occurrences=[date_start] if single_day else [],
                recurrence_unknown=date_start is not None and date_start != date_end,
                time=extract_time(record.get("horaInicio")),
                is_free=None if price_min is None else price_min == 0,
                price_text=detail.get("price_text"),
                price_min=price_min,
                currency=detail.get("currency"),
                ticket_url=ticket_url,
                seller=detail.get("seller") or seller_from_url(ticket_url),
                image_url=_image_url(record, date_start),
                city="Mar del Plata",
                raw_url=DETAIL_URL.format(slug=(record.get("slug") or "").strip()),
            )
        )
    return events
