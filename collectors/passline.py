"""Passline venue-agenda collector (passline.com).

Read-only. Passline's own listing (`/eventos`, `/eventos-presencial.php`)
sits behind a Queue-it waiting room, so discovery goes through a curated
list of venue slugs whose pages are server-rendered:

    GET /venue/<slug>  ->  anchors to /eventos/<slug>

Each event page is the seller page itself: it carries the Spanish date
("Viernes 30 de Octubre 2026 - 23:30 hrs."), the venue name + address, the
ticket table with es-AR prices, and a canonical URL. A failing venue or
detail is logged to stderr and skipped; only a run where every venue failed
raises, so the pipeline can record the source as failed.
"""

import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time, parse_spanish_date, to_iso
from lib.schema import Event
from lib.sellers import seller_from_url

BASE = "https://www.passline.com"
VENUE_URL = BASE + "/venue/{slug}"
EVENT_URL = BASE + "/eventos/{slug}"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
SOURCE = "passline"

# Curated on 2026-10-23: every slug returns 200 and belongs to Mar del Plata.
# Passline has no city filter that is reachable without Queue-it, so a new
# venue must be added here by hand.
VENUE_SLUGS = (
    "roomie-club",
    "zwan",
    "mr-jones",
    "la-caseta",
    "centro-cultural-victoria-ocampo-villa-victoria",
)

_EVENT_PATH_RE = re.compile(r"^/eventos/([^/]+)/?$")
_PRICE_RE = re.compile(r"\$\s*(\d[\d.,]*)")
# Passline writes "30 de Octubre 2026" (no second "de"); parse_spanish_date
# only reads an explicit year from "30 de Octubre de 2026".
_YEAR_RE = re.compile(r"\bde\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+(\d{4})\b")
_SOLD_OUT_RE = re.compile(r"SOLD\s*OUT|AGOTADO", re.IGNORECASE)


def _fetch(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def _site_host(url):
    """Return the passline.com host of a URL (www stripped), else ""."""
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def parse_venue_page(html):
    """Return the unique event URLs linked from a venue page, in page order."""
    soup = BeautifulSoup(html or "", "html.parser")
    links = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE + "/", anchor["href"].strip())
        if _site_host(url) != "passline.com":
            continue
        match = _EVENT_PATH_RE.match(urlparse(url).path)
        if match is None:
            continue
        event_url = EVENT_URL.format(slug=match.group(1))
        if event_url in seen:
            continue
        seen.add(event_url)
        links.append(event_url)
    return links


def _parse_price(raw):
    """Parse an es-AR amount ("20.000" / "$ 20.000,50"); None when invalid."""
    if not raw:
        return None
    text = raw.replace("$", "").replace(" ", "").strip()
    if "," in text:
        integer, _, decimal = text.rpartition(",")
        text = f"{integer.replace('.', '')}.{decimal}" if decimal else integer.replace(".", "")
    else:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _cheapest_price(soup):
    """Return (minimum amount, the cell text that produced it) of the ticket table."""
    table = soup.select_one("#tabla_tickets_sin_codigo")
    price_min = None
    price_text = None
    for cell in (table or soup).select("td.td-modify"):
        text = cell.get_text(" ", strip=True)
        for match in _PRICE_RE.finditer(text):
            value = _parse_price(match.group(1))
            if value is None:
                continue
            if price_min is None or value < price_min:
                price_min = value
                price_text = text
    return price_min, price_text


def _venue(node):
    """Return (name, address) from the venue block, address without the region line."""
    if node is None:
        return "", ""
    strong = node.find("strong")
    name = strong.get_text(" ", strip=True) if strong else ""
    lines = [
        line.strip()
        for line in node.get_text("\n", strip=True).split("\n")
        if line.strip()
    ]
    if not name and lines:
        name = lines[0]
    address = next((line for line in lines if line != name), "")
    return name, address


def _image_url(soup):
    image = soup.find("meta", property="og:image")
    if image is None:
        return None
    return (image.get("content") or "").strip() or None


def _sold_out(soup):
    table = soup.select_one("#tabla_tickets_sin_codigo")
    return bool(_SOLD_OUT_RE.search((table or soup).get_text(" ")))


def _slug(url):
    path = urlparse(url or "").path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def parse_event_page(html, url=None):
    """Parse one event page into a JSON-serializable raw record (pure)."""
    soup = BeautifulSoup(html or "", "html.parser")
    heading = soup.select_one("h1.titulo_evento")
    if heading is None:
        raise ValueError("event heading not found")
    canonical = soup.find("link", rel="canonical")
    canonical_href = canonical.get("href") if canonical else None
    raw_url = (canonical_href or "").strip() or url
    if raw_url:
        raw_url = urljoin(BASE + "/", raw_url.strip())
    date_node = soup.select_one("#li_fecha_inicio")
    venue_name, venue_address = _venue(soup.select_one("#segundo_contenedor"))
    price_min, price_text = _cheapest_price(soup)
    return {
        "source": SOURCE,
        "slug": _slug(raw_url),
        "title": heading.get_text(" ", strip=True),
        "date_text": date_node.get_text(" ", strip=True) if date_node else "",
        "venue_name": venue_name,
        "venue_address": venue_address,
        "price_min": price_min,
        "price_text": price_text,
        "currency": "ARS" if price_min is not None else None,
        "ticket_url": raw_url,
        "image_url": _image_url(soup),
        # Informational only: a sold-out page is still a valid event.
        "sold_out": _sold_out(soup),
        "raw_url": raw_url,
    }


def collect():
    """Fetch every curated venue page, then every event page it links to.

    Venue and detail failures are logged to stderr and skipped. When every
    venue request fails the last error is raised so the pipeline can mark the
    source as failed; a venue that answers with no events is a valid result.
    """
    records = []
    seen = set()
    fetched = 0
    last_error = None
    for index, slug in enumerate(VENUE_SLUGS):
        if index:
            time.sleep(REQUEST_DELAY)
        try:
            html = _fetch(VENUE_URL.format(slug=slug))
        except Exception as exc:  # network, HTTP or decode errors
            last_error = exc
            print(f"[passline] venue {slug} failed: {exc!r}", file=sys.stderr)
            continue
        fetched += 1
        for event_url in parse_venue_page(html):
            if event_url in seen:
                continue
            seen.add(event_url)
            time.sleep(REQUEST_DELAY)
            try:
                event_html = _fetch(event_url)
                record = parse_event_page(event_html, event_url)
            except Exception as exc:  # network, HTTP, decode or parse errors
                print(f"[passline] detail {event_url} failed: {exc!r}", file=sys.stderr)
                continue
            records.append(record)
    if not fetched and last_error is not None:
        raise last_error
    return records


def _explicit_year(text):
    """Add the missing "de" before the year so lib.dates reads it."""
    return _YEAR_RE.sub(r"de \1 de \2", text or "")


def _venue_fields(record):
    name = (record.get("venue_name") or "").strip()
    address = (record.get("venue_address") or "").strip()
    if name and address:
        return name, f"{name}, {address}"
    return name, address or name


def normalize(records):
    events = []
    for record in records:
        date_start = to_iso(parse_spanish_date(_explicit_year(record.get("date_text"))))
        price_min = record.get("price_min")
        venue_name, venue_raw = _venue_fields(record)
        url = record.get("ticket_url") or record.get("raw_url")
        events.append(
            Event(
                source=SOURCE,
                source_event_id=record.get("slug") or "",
                title=(record.get("title") or "").strip(),
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=date_start,
                # Passline publishes one night per page: never invent a range.
                date_end=date_start,
                occurrences=[date_start] if date_start else [],
                recurrence_unknown=False,
                time=extract_time(record.get("date_text")),
                is_free=None if price_min is None else price_min == 0,
                price_text=None,
                price_min=price_min,
                currency=record.get("currency"),
                ticket_url=url,
                seller=seller_from_url(url),
                image_url=record.get("image_url"),
                city="Mar del Plata",
                raw_url=url,
            )
        )
    return events
