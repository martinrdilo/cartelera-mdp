"""Teatro Municipal Colón collector (mardelplata.gob.ar/colonprogramacion).

The monthly program is malformed Drupal 7 HTML: two ``div.well.span5`` columns
whose wrapper ``<p>`` contains one nested ``<p>`` per visible line. The
collector reads those lines in document order, tracks the month header
(OCTUBRE) across both columns, and turns every "<weekday> <day> a las <time>
hs" line into one raw record with its title, description lines and price
lines. Raw records stay JSON-ready so they can be stored as evidence.
"""

import hashlib
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

from lib.schema import Event

BASE = "https://www.mardelplata.gob.ar"
LIST_URL = f"{BASE}/colonprogramacion"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"
SOURCE = "colon"
VENUE_NAME = "Teatro Municipal Colón"
CITY = "Mar del Plata"
YEAR_WINDOW_DAYS = 180

_MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}
_TIME = r"(\d{1,2})(?::(\d{2}))?"
_DATE_RE = re.compile(
    r"^(Lunes|Martes|Mi[eé]rcoles|Jueves|Viernes|S[aá]bado|Domingo)"
    rf"\s+(\d{{1,2}})\s+a\s+las\s+{_TIME}(?:\s+y\s+{_TIME})?\s*hs?\.?$",
    re.IGNORECASE,
)
_PRICE_HINT_RE = re.compile(r"entrada|localidad|\$|gratuit|libre", re.IGNORECASE)
_PRICE_AMOUNT_RE = re.compile(r"\$\s*([\d.,]+)")


def _fetch_page():
    response = requests.get(
        LIST_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _program_lines(html):
    """Return the visible program lines of both columns, in document order."""
    soup = BeautifulSoup(html, "html.parser")
    lines = []
    for column in soup.select("div.well.span5"):
        for paragraph in column.find_all("p"):
            # The outer <p> wraps a <div> with the whole column; only the
            # innermost <p> elements are actual lines.
            if paragraph.find("p") is not None or paragraph.find("div") is not None:
                continue
            text = " ".join(paragraph.get_text(" ").split())
            if text:
                lines.append(text)
    return lines


def parse_page(html):
    """Parse the monthly program page into JSON-ready raw records (pure)."""
    records = []
    month = None
    current = None
    for line in _program_lines(html):
        month_number = _MONTHS.get(line.upper())
        if month_number is not None:
            month = month_number
            continue
        match = _DATE_RE.match(line)
        if match:
            day = int(match.group(2))
            hour = int(match.group(3))
            minute = int(match.group(4) or 0)
            current = {
                "title": "",
                "day": day,
                "month": month,
                "time": f"{hour:02d}:{minute:02d}",
                "price_lines": [],
                "description_lines": [],
            }
            records.append(current)
            continue
        if current is None:
            continue
        if not current["title"]:
            current["title"] = line
            continue
        if _PRICE_HINT_RE.search(line):
            current["price_lines"].append(line)
        else:
            current["description_lines"].append(line)

    return [
        {
            "source": SOURCE,
            "title": record["title"],
            "day": record["day"],
            "month": record["month"],
            "time": record["time"],
            "price_lines": record["price_lines"],
            "description": "\n".join(record["description_lines"]),
            "raw_url": LIST_URL,
        }
        for record in records
    ]


def _parse_price(raw):
    """Parse an es-AR amount ("25.000", "$ 25.000,50"); None when invalid."""
    if not raw:
        return None
    text = raw.replace("$", "").replace(" ", "").strip()
    if not text:
        return None
    if "," in text:
        integer, _, decimal = text.rpartition(",")
        integer = integer.replace(".", "")
        text = f"{integer}.{decimal}" if decimal else integer
    else:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _cheapest_price(price_lines):
    """Return (minimum amount, the line that produced it) across all lines."""
    price_min = None
    price_text = None
    for line in price_lines:
        for match in _PRICE_AMOUNT_RE.finditer(line):
            value = _parse_price(match.group(1))
            if value is None:
                continue
            if price_min is None or value < price_min:
                price_min = value
                price_text = line.strip()
    return price_min, price_text


def _resolve_date(month, day, today):
    """Resolve the month/day pair to the closest year around today.

    Invalid dates return None. A candidate more than 180 days in the past
    moves to the next year; one more than 180 days in the future moves to the
    previous year.
    """
    if month is None or day is None:
        return None
    try:
        candidate = date(today.year, month, day)
        if (today - candidate).days > YEAR_WINDOW_DAYS:
            candidate = date(today.year + 1, month, day)
        elif (candidate - today).days > YEAR_WINDOW_DAYS:
            candidate = date(today.year - 1, month, day)
    except ValueError:
        return None
    return candidate


def collect():
    """Fetch the monthly program once; request failures propagate."""
    return parse_page(_fetch_page())


def normalize(records):
    events = []
    today = date.today()
    for record in records:
        resolved = _resolve_date(record["month"], record["day"], today)
        if resolved is None:
            continue
        iso = resolved.isoformat()
        price_lines = record.get("price_lines") or []
        price_min, price_text = _cheapest_price(price_lines)
        if price_min is not None:
            is_free = False
        elif any(
            "gratuit" in line.lower() or "libre" in line.lower() for line in price_lines
        ):
            is_free = True
        else:
            is_free = None
        title = record["title"]
        ticket_haystack = " ".join(
            [record.get("description") or "", *price_lines]
        ).lower()
        seller = "Fever" if "feverup" in ticket_haystack else None
        events.append(
            Event(
                source=SOURCE,
                source_event_id=f"{iso}-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:10]}",
                title=title,
                venue_name=VENUE_NAME,
                venue_raw=VENUE_NAME,
                date_start=iso,
                date_end=iso,
                occurrences=[iso],
                recurrence_unknown=False,
                time=record.get("time"),
                is_free=is_free,
                price_text=price_text,
                price_min=price_min,
                currency="ARS" if price_min is not None else None,
                seller=seller,
                ticket_url=None,
                city=CITY,
                raw_url=LIST_URL,
            )
        )
    return events
