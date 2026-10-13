"""Articket and CultuTickets collector (shared MuchTicket platform).

Both sites expose the same open JSON: GET /obtener_eventos/?cantidad_eventos=N.
CultuTickets publishes "Mar de Plata" (missing "l") in `lugar`, so the city
filter accepts both spellings.
"""

import re
import sys
import time

import requests

from lib.dates import extract_time, parse_ddmmyyyy, to_iso
from lib.schema import Event

SOURCES = (
    {"source": "articket", "host": "articket.com.ar", "seller": "Articket"},
    {"source": "cultutickets", "host": "cultutickets.com", "seller": "CultuTickets"},
)
USER_AGENT = "cartelera-mdp-spike/0.1 (local research)"
REQUEST_DELAY = 1.0


def _is_mdp(*values):
    for value in values:
        low = (value or "").lower()
        if "mar del plata" in low or "mar de plata" in low:
            return True
    return False


def _fetch(host):
    url = f"https://{host}/obtener_eventos/?cantidad_eventos=500"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return url, response.json()


def _parse_decimal(value):
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect():
    """Fetch both hosts; a failing host does not abort the other."""
    records = []
    for entry in SOURCES:
        try:
            url, payload = _fetch(entry["host"])
        except Exception as exc:  # requests errors, JSON errors
            print(f"[muchticket] {entry['source']} failed: {exc!r}", file=sys.stderr)
            continue
        for item in payload.get("eventos", []):
            if not _is_mdp(item.get("lugar"), item.get("lugar_responsive")):
                continue
            records.append(
                {
                    "source": entry["source"],
                    "host": entry["host"],
                    "seller": entry["seller"],
                    "nombre": item.get("nombre", ""),
                    "desde_fecha": item.get("desde_fecha", ""),
                    "lugar": item.get("lugar", ""),
                    "lugar_responsive": item.get("lugar_responsive", ""),
                    "slug": item.get("slug", ""),
                    "unica_fecha": item.get("unica_fecha"),
                    "url_externa": item.get("url_externa", ""),
                    "entradas_online_desde": item.get("entradas_online_desde"),
                    "texto_precio_home": item.get("texto_precio_home"),
                    "moneda": item.get("moneda") or payload.get("moneda"),
                    "imagen_home": item.get("imagen_home"),
                    "media_url": payload.get("media_url"),
                    "raw_url": url,
                }
            )
        time.sleep(REQUEST_DELAY)
    return records


def normalize(records):
    events = []
    for record in records:
        date_part, _, time_part = record["desde_fecha"].partition(",")
        external = (record["url_externa"] or "").strip()
        ticket_url = external or f"https://{record['host']}/{record['slug']}/"
        price_min = _parse_decimal(record["entradas_online_desde"])
        if price_min is not None:
            is_free = price_min == 0
        else:
            is_free = None
        image_url = None
        if record["imagen_home"]:
            image_url = f"https://{record['host']}" + record["imagen_home"]
        events.append(
            Event(
                source=record["source"],
                source_event_id=record["slug"],
                title=record["nombre"].strip(),
                venue_name=record["lugar"].split(",")[0].strip(),
                venue_raw=record["lugar"].strip(),
                # Limitation: multi-date events (unica_fecha=false) only expose
                # the first date in this endpoint.
                date_start=to_iso(parse_ddmmyyyy(date_part)),
                date_end=to_iso(parse_ddmmyyyy(date_part)),
                time=extract_time(time_part) or extract_time(record["desde_fecha"]),
                is_free=is_free,
                price_text=(record["texto_precio_home"] or "").strip() or None,
                price_min=price_min,
                currency=record["moneda"] or "ARS",
                ticket_url=ticket_url,
                seller=record["seller"],
                image_url=image_url,
                city="Mar del Plata",
                raw_url=record["raw_url"],
            )
        )
    return events
