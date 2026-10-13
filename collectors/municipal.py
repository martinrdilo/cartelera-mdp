"""Municipal EMTUR agenda collector (turismomardelplata.gob.ar).

The agenda is ASP server-rendered and served as ISO-8859-1. Category pages
are fetched with GET params (?pagina=N&tipo=11) and pagination stops when a
page returns no event panels (or at MAX_PAGES).
"""

import hashlib
import re
import sys
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time, parse_ddmmyyyy, to_iso
from lib.occurrences import expand_segments, parse_weekdays
from lib.schema import Event

BASE = "https://www.turismomardelplata.gob.ar"
RESULTS_URL = f"{BASE}/ASP/SP/resultados-eventos.asp"
CATEGORIES = (("11", "musica"), ("16", "cena_show_pena"), ("19", "festivales"))
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
REQUEST_DELAY = 1.0
MAX_PAGES = 15
SOURCE = "municipal"

_SELLERS = {
    "ticketek": "Ticketek",
    "venti.live": "Venti.live",
    "articket": "Articket",
    "plateanet": "Plateanet",
    "feverup": "Fever",
    "cultutickets": "CultuTickets",
    "passline": "Passline",
    "ticketmas": "Ticketmas",
    "boletería": "Boletería",
    "boleteria": "Boletería",
}
_PHOTO_RE = re.compile(r"Fotos[\\/]eventos[\\/](\d+)_([^\"'<>]+?\.(?:jpe?g|png|gif))", re.IGNORECASE)
_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
# A schedule block repeats "desde: <date> - hasta: <date> Horarios <weekdays>"
# once per range; the tail is scanned for weekday names.
_SEGMENT_RE = re.compile(
    r"desde:\s*(\d{1,2}/\d{1,2}/\d{4})\s*-\s*hasta:\s*(\d{1,2}/\d{1,2}/\d{4})(.*?)(?=desde:|$)",
    re.IGNORECASE | re.DOTALL,
)


def parse_schedule_segments(schedule_text):
    """Pair each desde/hasta range with the weekday names that follow it."""
    segments = []
    for match in _SEGMENT_RE.finditer(schedule_text or ""):
        desde, hasta, tail = match.groups()
        segments.append({"desde": desde, "hasta": hasta, "weekdays": parse_weekdays(tail)})
    return segments


def _fetch_page(page, tipo):
    response = requests.get(
        RESULTS_URL,
        params={"pagina": page, "tipo": tipo},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.content.decode("iso-8859-1", errors="replace")


def _sections(panel):
    """Pair each panel-heading with its following panel-body."""
    sections = []
    children = panel.find_all("div", recursive=False)
    index = 0
    while index < len(children):
        child = children[index]
        if "panel-heading" in child.get("class", []):
            heading = child.get_text(" ", strip=True)
            body_text, body_html = "", ""
            if index + 1 < len(children) and "panel-body" in children[index + 1].get("class", []):
                body = children[index + 1]
                body_text = body.get_text("\n", strip=True)
                body_html = str(body)
                index += 1
            sections.append({"heading": heading, "text": body_text, "html": body_html})
        index += 1
    return sections


def _split_venue(body_text):
    """Split the venue block into (name, raw) using its nbsp separators."""
    lines = [line.strip() for line in body_text.split("\n") if line.strip()]
    first_line = lines[0] if lines else ""
    first_line = first_line.split("Teléfono")[0].split("Telefono")[0]
    parts = [part.strip() for part in first_line.split("\xa0") if part.strip()]
    if not parts:
        return first_line.strip(), first_line.strip()
    name = parts[0]
    address = " ".join(parts[1:])
    raw = f"{name}, {address}" if address else name
    return name, raw


def _parse_entry(text):
    """Return (is_free, price_min, seller) from the "Entrada" block."""
    low = text.lower()
    price_match = _PRICE_RE.search(text)
    price_min = None
    if price_match:
        digits = price_match.group(1).replace(".", "")
        if digits.isdigit():
            price_min = float(digits)
    if price_min is not None:
        is_free = False
    elif "gratuit" in low or "gratis" in low or re.search(r"\blibre\b", low):
        is_free = True
    else:
        is_free = None
    seller = next((name for key, name in _SELLERS.items() if key in low), None)
    return is_free, price_min, seller


def _parse_panel(panel, raw_url, category):
    title_node = panel.select_one("div.panel-title strong")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    sections = {}
    for section in _sections(panel):
        heading = section["heading"].lower()
        if "lugar del evento" in heading and "venue" not in sections:
            sections["venue"] = section
        elif "horarios" in heading and "schedule" not in sections:
            sections["schedule"] = section
        elif "observaciones" in heading and "description" not in sections:
            sections["description"] = section
        elif "entrada" in heading and "entry" not in sections:
            sections["entry"] = section
        elif "fotos" in heading and "photos" not in sections:
            sections["photos"] = section
    venue_body = sections.get("venue", {}).get("text", "")
    venue_name, venue_raw = _split_venue(venue_body)
    schedule_text = sections.get("schedule", {}).get("text", "")
    ranges = parse_schedule_segments(schedule_text)
    photo_match = _PHOTO_RE.search(sections.get("photos", {}).get("html", ""))
    source_event_id = None
    image_url = None
    if photo_match:
        source_event_id = photo_match.group(1)
        image_url = BASE + quote(f"/Fotos/eventos/{photo_match.group(1)}_{photo_match.group(2)}")
    else:
        seed = f"{title}|{ranges[0]['desde'] if ranges else ''}"
        source_event_id = "mdp-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return {
        "source": SOURCE,
        "title": title,
        "venue_name": venue_name,
        "venue_raw": venue_raw,
        "ranges": ranges,
        "schedule_text": schedule_text,
        "description": sections.get("description", {}).get("text", ""),
        "entry_text": sections.get("entry", {}).get("text", ""),
        "source_event_id": source_event_id,
        "image_url": image_url,
        "category": category,
        "raw_url": raw_url,
    }


def parse_page(html, raw_url, category):
    """Parse every event panel on one results page (pure, testable)."""
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for panel in soup.select("div.panel.panel-default"):
        if "Lugar del evento" not in panel.get_text(" ", strip=True):
            continue
        records.append(_parse_panel(panel, raw_url, category))
    return records


def collect():
    """Fetch every category page until empty; one page error stops that category."""
    records = []
    seen = set()
    for tipo, category in CATEGORIES:
        for page in range(1, MAX_PAGES + 1):
            raw_url = f"{RESULTS_URL}?pagina={page}&tipo={tipo}"
            try:
                html = _fetch_page(page, tipo)
            except requests.RequestException as exc:
                print(f"[municipal] page {page} tipo={tipo} failed: {exc!r}", file=sys.stderr)
                break
            page_records = parse_page(html, raw_url, category)
            if not page_records:
                break
            for record in page_records:
                first_start = record["ranges"][0]["desde"] if record["ranges"] else ""
                fingerprint = (record["title"].lower(), first_start)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                records.append(record)
            time.sleep(REQUEST_DELAY)
    return records


def normalize(records):
    events = []
    for record in records:
        is_free, price_min, seller = _parse_entry(record["entry_text"])
        segments = []
        for item in record["ranges"]:
            start = parse_ddmmyyyy(item["desde"])
            end = parse_ddmmyyyy(item["hasta"]) or start
            if start and end:
                segments.append({"start": start, "end": end, "weekdays": item.get("weekdays") or set()})
        starts = [segment["start"] for segment in segments]
        ends = [segment["end"] for segment in segments]
        occurrences, recurrence_unknown = expand_segments(segments)
        events.append(
            Event(
                source=SOURCE,
                source_event_id=record["source_event_id"],
                title=record["title"],
                venue_name=record["venue_name"],
                venue_raw=record["venue_raw"],
                date_start=to_iso(min(starts)) if starts else None,
                date_end=to_iso(max(ends)) if ends else None,
                occurrences=occurrences,
                recurrence_unknown=recurrence_unknown,
                time=extract_time(record["schedule_text"]),
                is_free=is_free,
                price_text=re.sub(r"\s+", " ", record["entry_text"]).strip() or None,
                price_min=price_min,
                currency="ARS" if price_min is not None else None,
                ticket_url=None,
                seller=seller,
                image_url=record["image_url"],
                city="Mar del Plata",
                raw_url=record["raw_url"],
            )
        )
    return events
