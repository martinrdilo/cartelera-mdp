"""Teatro Auditorium (teatroauditorium.gba.gob.ar) agenda collector.

Read-only. The Drupal 10 programme listing is server-rendered and paginated
through `?page=N` (six activities per page):

    GET /programacion?page=N

Each activity card carries its title, detail path, sala, `time[datetime]`
pairs (start/end, several per activity when it has multiple functions),
image and the detail link. The detail page has no price data: only the
seller ("Localidades en venta por Plateanet") or the free admission note
("Entrada libre y gratuita").

A failing detail page never drops the event: the record keeps `detail=None`
and the failure is logged to stderr.
"""

import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from lib.schema import Event

BASE = "https://teatroauditorium.gba.gob.ar"
LIST_URL = f"{BASE}/programacion"
DETAIL_URL = f"{BASE}{{path}}"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
MAX_PAGES = 15
SOURCE = "auditorium"

_LAURETI = "Jorge Laureti - Puerto"
_SALE_PHRASES = ("localidades en venta", "entradas en venta", "a la venta")
_WHITESPACE_RE = re.compile(r"\s+")


def _collapsed(node):
    """Whitespace-collapsed text of a BeautifulSoup node."""
    return _WHITESPACE_RE.sub(" ", node.get_text(" ", strip=True)).strip()


def _fetch_page(page):
    response = requests.get(
        LIST_URL,
        params={"page": page},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _fetch_detail(path):
    response = requests.get(
        DETAIL_URL.format(path=path),
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return parse_detail(response.text)


def parse_page(html):
    """Parse one programme listing page into JSON-ready records."""
    soup = BeautifulSoup(html or "", "html.parser")
    records = []
    for article in soup.select("article.node--type-actividades-agenda"):
        link = article.select_one("h2 a")
        title = _collapsed(link) if link else ""
        path = link.get("href", "") if link else ""

        sala = None
        for node in article.select("div.text-uppercase"):
            text = _collapsed(node)
            if text.startswith("Sala "):
                sala = text[len("Sala ") :].strip()
                break

        image = article.select_one("img.image-style-resumen-noticias")
        image_src = image.get("src") if image else None

        records.append(
            {
                "source": SOURCE,
                "title": title,
                "path": path,
                "sala": sala,
                "datetimes": [node["datetime"] for node in article.select("time[datetime]")],
                "image_url": urljoin(BASE, image_src) if image_src else None,
                "raw_url": f"{BASE}{path}",
            }
        )
    return records


def parse_detail(html):
    """Read seller and free/paid status from a detail page's visible text."""
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(["script", "style", "noscript"]):
        node.decompose()
    text = _WHITESPACE_RE.sub(" ", soup.get_text(" ", strip=True)).lower()

    seller = "Plateanet" if "plateanet" in text else None
    if "gratuit" in text or "libre y gratuita" in text:
        is_free = True
    elif any(phrase in text for phrase in _SALE_PHRASES):
        is_free = False
    else:
        is_free = None
    return {"seller": seller, "is_free": is_free}


def collect():
    """Fetch every listing page, then enrich each record with its detail page.

    A failure on the first listing page propagates (the pipeline records the
    source as failed); a later page keeps what was already collected. Detail
    failures only drop seller/free fields, never the event.
    """
    records = []
    for page in range(MAX_PAGES):
        try:
            html = _fetch_page(page)
        except Exception as exc:  # network, HTTP or decode errors
            if not records:
                raise
            print(f"[auditorium] page {page} failed: {exc!r}", file=sys.stderr)
            break
        page_records = parse_page(html)
        records.extend(page_records)
        if not page_records:
            break
        if page < MAX_PAGES - 1:
            time.sleep(REQUEST_DELAY)

    for index, record in enumerate(records):
        if index:
            time.sleep(REQUEST_DELAY)
        path = record["path"]
        try:
            detail = _fetch_detail(path)
        except Exception as exc:  # network, HTTP or parse errors
            print(f"[auditorium] detail {path} failed: {exc!r}", file=sys.stderr)
            detail = None
        record["detail"] = detail
    return records


def _venue(sala):
    """Map the card's sala label to (canonical venue_name, venue_raw)."""
    sala = (sala or "").strip()
    if sala == _LAURETI:
        return "Teatro Auditorium Laureti Puerto", "Sala Jorge Laureti - Puerto"
    if not sala:
        return "Teatro Auditorium", "Teatro Auditorium"
    if sala == "Foyer":
        return "Teatro Auditorium", "Foyer"
    return "Teatro Auditorium", f"Sala {sala}"


def normalize(records):
    events = []
    for record in records:
        datetimes = record.get("datetimes") or []
        dates = sorted({value[:10] for value in datetimes})
        detail = record.get("detail") or {}
        venue_name, venue_raw = _venue(record.get("sala"))
        path = (record.get("path") or "").strip()
        events.append(
            Event(
                source=SOURCE,
                source_event_id=path.rstrip("/").rsplit("/", 1)[-1],
                title=(record.get("title") or "").strip(),
                venue_name=venue_name,
                venue_raw=venue_raw,
                date_start=dates[0] if dates else None,
                date_end=dates[-1] if dates else None,
                occurrences=dates,
                recurrence_unknown=False,
                time=datetimes[0][11:16] if datetimes else None,
                is_free=detail.get("is_free"),
                seller=detail.get("seller"),
                image_url=record.get("image_url"),
                city="Mar del Plata",
                raw_url=record.get("raw_url"),
            )
        )
    return events
