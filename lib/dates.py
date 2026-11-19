"""Spanish date and time parsing helpers.

The municipal agenda uses dd/mm/yyyy strings; ClubTri uses weekday-style
dates without a year ("Mié 14 de Octubre"), so the year is inferred:
current year, rolled to the next year when the candidate is clearly past.
"""

import re
import unicodedata
from datetime import date, timedelta

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_SPANISH_RE = re.compile(
    r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)(?:\s+de\s+(\d{4}))?",
    re.IGNORECASE,
)
_TIME_HHMM_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_TIME_HOUR_RE = re.compile(r"(\d{1,2})\s*(?:hs?|horas)\b", re.IGNORECASE)
_TIME_BARE_RE = re.compile(r"^\s*(\d{1,2})\s*$")

# Sources print the weekday next to a year-less date ("Sáb 14 de Noviembre").
# When present it disambiguates the year: a stale agenda entry must keep the
# year whose weekday matches the text, not roll forward just because it passed.
_WEEKDAYS = {
    "lun": 0,
    "lunes": 0,
    "mar": 1,
    "martes": 1,
    "mie": 2,
    "miercoles": 2,
    "jue": 3,
    "jueves": 3,
    "vie": 4,
    "viernes": 4,
    "sab": 5,
    "sabado": 5,
    "dom": 6,
    "domingo": 6,
}
_WEEKDAY_RE = re.compile(
    r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
    r"lun|mar|mie|jue|vie|sab|dom)\b",
    re.IGNORECASE,
)


def _strip_accents(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def parse_ddmmyyyy(text):
    """Parse the first dd/mm/yyyy date inside text. Returns date or None."""
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _weekday_from_text(text):
    """Return the weekday index printed in the text (Monday=0), or None."""
    cleaned = _strip_accents(text).lower()
    match = _WEEKDAY_RE.search(cleaned)
    return _WEEKDAYS.get(match.group(1)) if match else None


def parse_spanish_date(text, today=None):
    """Parse a "14 de Octubre" style date, inferring the year.

    When the text prints a weekday, the year that matches that weekday wins:
    a stale listing of the past Saturday stays in the current year instead of
    jumping twelve months ahead. Without a weekday, the agenda rule still
    applies: current year, rolled forward when the candidate is clearly past.
    """
    if not text:
        return None
    match = _SPANISH_RE.search(text)
    if not match:
        return None
    day_text, month_text, year_text = match.groups()
    month = _MONTHS.get(_strip_accents(month_text).lower())
    if month is None:
        return None
    today = today or date.today()
    expected_weekday = _weekday_from_text(text)
    try:
        if year_text:
            return date(int(year_text), month, int(day_text))
        if expected_weekday is not None:
            for year in (today.year, today.year + 1):
                try:
                    option = date(year, month, int(day_text))
                except ValueError:
                    continue
                if option.weekday() == expected_weekday:
                    return option
        candidate = date(today.year, month, int(day_text))
    except ValueError:
        return None
    if candidate < today - timedelta(days=1):
        candidate = date(today.year + 1, month, int(day_text))
    return candidate


def extract_time(text):
    """Extract a HH:MM time from strings like "19 Hs", "20:00", "23.59 Hs", "22"."""
    if not text:
        return None
    match = _TIME_HHMM_RE.search(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        match = _TIME_HOUR_RE.search(text) or _TIME_BARE_RE.search(text)
        if not match:
            return None
        hour, minute = int(match.group(1)), 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def to_iso(value):
    """Convert a date (or None) to an ISO-8601 date string."""
    return value.isoformat() if value else None
