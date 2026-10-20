#!/usr/bin/env python3
"""Static site generator for Cartelera MDP (Fase 2).

Reads the pipeline outputs and writes a single-page static site:

    data/events_normalized.json   every normalized event (source of singles)
    data/events_deduped.json      duplicate clusters (2+ members each)
    data/venues.json              venue registry (display names, addresses)
    data/last_run.json            footer "updated at" timestamp

Merge rule (one card per dedupe cluster): seller-sourced members (articket,
cultutickets, clubtri) win for title, price, ticket_url and image_url;
municipal members win for the venue address (the agenda carries street
addresses); dates are the union of member occurrences; an event is free when
any member is free. Unclustered normalized events are single-member site
events and go through the same precedence, so the fallback is uniform.
Seller values that are only placeholders (Club TRI's "Comprar", empty
strings) fall through to the next source instead of shadowing a real value.

Dedupe only exports clusters, so the full catalog is the cluster merges plus
the normalized events no cluster consumed.

No network, standard library only (Python 3.12).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, quote
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Site identity and constants
# ---------------------------------------------------------------------------

SITE_NAME = "Cartelera MDP"  # placeholder name, single source of truth
SITE_URL = "https://martinrdilo.github.io/cartelera-mdp/"
SITE_TAGLINE = "Qué hay este finde en Mar del Plata"
SITE_DESCRIPTION = (
    "Cartelera de música en Mar del Plata: qué hay este finde (jueves a domingo), "
    "todos los shows y entradas con link directo a la ticketera oficial."
)

ART_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_OUT_DIR = ROOT / "site"
ASSETS_SRC = ROOT / "site_assets"

# Seller sources win over the municipal agenda for event-level fields.
SELLER_SOURCES = ("articket", "cultutickets", "clubtri")
SOURCE_ORDER = SELLER_SOURCES + ("municipal",)

WEEKDAY_ABBR = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")

# Values that carry no price information; they must not shadow a real price.
PRICE_PLACEHOLDERS = {
    "comprar",
    "comprar entradas",
    "ver",
    "ver entradas",
    "entradas",
    "más info",
    "mas info",
}

WINDOWS = ("weekend", "7days", "all")
MAX_CARD_DATES = 3


# ---------------------------------------------------------------------------
# Dates and windows
# ---------------------------------------------------------------------------


def today_in_art(now: datetime | None = None) -> date:
    """Current date in Mar del Plata (America/Argentina/Buenos_Aires)."""
    return (now or datetime.now(ART_TZ)).astimezone(ART_TZ).date()


def weekend_window(today: date) -> tuple[date, date]:
    """Thu..Sun window for "Este finde".

    Monday to Wednesday: next Thursday..Sunday. Thursday onwards: today..Sunday.
    Always clipped to >= today by construction.
    """
    weekday = today.weekday()  # Monday == 0
    if weekday >= 3:  # Thu, Fri, Sat, Sun: today through this week's Sunday
        start = today
        end = today + timedelta(days=6 - weekday)
    else:  # Mon, Tue, Wed: next Thursday through Sunday
        start = today + timedelta(days=3 - weekday)
        end = start + timedelta(days=3)
    return start, end


def window_bounds(window: str, today: date) -> tuple[date | None, date | None]:
    """Bounds for a filter window; None means unbounded."""
    if window == "weekend":
        return weekend_window(today)
    if window == "7days":
        return today, today + timedelta(days=6)
    if window == "all":
        return None, None
    raise ValueError(f"unknown window: {window!r}")


def event_dates(event: dict) -> list[str]:
    """Known session dates; falls back to the start date when none are known."""
    dates = event.get("occurrences") or ([event["date_start"]] if event.get("date_start") else [])
    return sorted(d for d in dates if d)


def upcoming_dates(event: dict, today: date) -> list[str]:
    """Session dates on or after today (ISO strings sort lexicographically)."""
    return [d for d in event_dates(event) if d >= today.isoformat()]


def matches_window(dates: list[str], window: str, today: date) -> bool:
    """True when any of the (upcoming) ISO dates falls inside the window."""
    start, end = window_bounds(window, today)
    for raw in dates:
        current = date.fromisoformat(raw)
        if start is not None and current < start:
            continue
        if end is not None and current > end:
            continue
        return True
    return False


def format_date_short(iso: str) -> str:
    """'2026-10-15' -> 'Jue 15/10'."""
    parsed = date.fromisoformat(iso)
    return f"{WEEKDAY_ABBR[parsed.weekday()]} {parsed.day:02d}/{parsed.month:02d}"


def format_when(dates: list[str], time: str | None) -> str:
    """'Jue 15/10 · 21:00' or 'Jue 15/10, Vie 16/10 · 21:00 · +2 fechas'."""
    label = ", ".join(format_date_short(d) for d in dates[:MAX_CARD_DATES])
    extra = len(dates) - MAX_CARD_DATES
    if time:
        label += f" · {time}"
    if extra > 0:
        label += f" · +{extra} fechas"
    return label




def format_updated(last_run: dict) -> str | None:
    """Footer timestamp in Mar del Plata local time."""
    raw = (last_run or {}).get("finished_at")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    local = parsed.astimezone(ART_TZ)
    return local.strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def is_usable(value) -> bool:
    """False for empty values and for price placeholders with no information."""
    if value is None or value == "" or value == []:
        return False
    if isinstance(value, str) and value.strip().casefold() in PRICE_PLACEHOLDERS:
        return False
    return True


def _parse_amount(raw: str) -> float | None:
    """'12.000' / '12000' / '12.000,50' -> float (es-AR separators)."""
    cleaned = re.sub(r"[^\d.,]", "", raw or "")
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


def format_price(value) -> str | None:
    """12000 -> '$12.000'; 12500.5 -> '$12.500,50'; None -> None."""
    if value is None:
        return None
    number = round(float(value), 2)
    if number == int(number):
        return "$" + f"{int(number):,}".replace(",", ".")
    return "$" + f"{number:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def clean_price_text(text: str | None) -> str | None:
    """Reduce a raw price note to a short label, or None when it says nothing.

    '$12000, en venta en articket.com.ar' -> '$12.000'
    'Desde $14000; en venta en www.articket.com.ar' -> 'Desde $14.000'
    'Libre y gratuita' -> 'Gratis'
    'Comprar' -> None
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.casefold() in PRICE_PLACEHOLDERS:
        return None
    if re.search(r"\b(gratis|gratuit|libre)\b", stripped, re.IGNORECASE) and not re.search(r"\d", stripped):
        return "Gratis"
    match = re.search(r"(desde\s*)?\$\s*([\d.,]+)", stripped, re.IGNORECASE)
    if match:
        amount = _parse_amount(match.group(2))
        if amount is not None:
            qualifier = "Desde " if match.group(1) else ""
            return f"{qualifier}{format_price(amount)}"
    # No price found: keep the note but drop ticketer URLs.
    without_urls = re.sub(
        r"\s*(?:en\s+)?(?:venta\s+en\s+)?(?:https?://)?(?:www\.)?[a-z0-9.-]+\.(?:com|ar|live|com\.ar)\S*",
        "",
        stripped,
        flags=re.IGNORECASE,
    ).strip(" .,;")
    return without_urls or None


def price_label(event: dict) -> str | None:
    """'Gratis' | '$12.000' | 'Desde $14.000' | cleaned price_text | None."""
    if event["is_free"] or event["price_min"] == 0:
        return "Gratis"
    if event["price_min"] is not None:
        label = format_price(event["price_min"])
        cleaned = clean_price_text(event["price_text"])
        if cleaned and cleaned.casefold().startswith("desde"):
            label = f"Desde {label}"
        return label
    return clean_price_text(event["price_text"])


# ---------------------------------------------------------------------------
# Venue registry and cluster merge
# ---------------------------------------------------------------------------


def normalize_key(value: str | None) -> str:
    """Case/accent/punctuation-insensitive key for venue matching."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def venue_index(registry: list[dict]) -> dict[str, dict]:
    """Normalized alias -> registry entry (name plus every alias)."""
    index: dict[str, dict] = {}
    for venue in registry:
        for alias in [venue.get("name", "")] + list(venue.get("aliases") or []):
            index[normalize_key(alias)] = venue
    return index


def resolve_venue(name: str | None, raw: str | None, index: dict[str, dict]) -> dict | None:
    """Registry entry for a display name or a 'Venue, Street 123' raw string."""
    candidates = [name or ""]
    if raw and "," in raw:
        candidates.append(raw.split(",", 1)[0])
    for candidate in candidates:
        venue = index.get(normalize_key(candidate))
        if venue:
            return venue
    return None


def venue_address(venue: dict | None, members: list[dict]) -> str | None:
    """Registry address first; municipal venue_raw carries one too."""
    if venue and venue.get("address"):
        return venue["address"]
    for member in members:
        if member.get("source") != "municipal":
            continue
        parts = (member.get("venue_raw") or "").split(",")
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if candidate and candidate.casefold() not in {"mar del plata", "buenos aires"}:
                return candidate
    return None


def event_ref(event: dict) -> str:
    """Stable source reference, same shape dedupe uses ('municipal:49411')."""
    return f"{event.get('source')}:{event.get('source_event_id')}"


def pick_field(members: list[dict], field: str):
    """First usable value in source priority order (sellers before municipal)."""
    for source in SOURCE_ORDER:
        for member in members:
            if member.get("source") == source and is_usable(member.get(field)):
                return member[field]
    return None


def slugify(value: str) -> str:
    slug = normalize_key(value).replace(" ", "-")
    return slug[:70] or "evento"


def merge_members(members: list[dict], index: dict[str, dict], today: date, venue_hint: str | None = None) -> dict:
    """Merge cluster members (or a single event) into one site event."""
    dates = sorted({d for member in members for d in upcoming_dates(member, today)})
    resolved = resolve_venue(venue_hint or "", "", index)
    if resolved is None:
        for source in SOURCE_ORDER:
            for member in members:
                if member.get("source") != source:
                    continue
                resolved = resolve_venue(member.get("venue_name"), member.get("venue_raw"), index)
                if resolved:
                    break
            if resolved:
                break
    venue_name = (resolved or {}).get("name") or venue_hint or members[0].get("venue_name") or "Mar del Plata"
    venue_id = (resolved or {}).get("id") or slugify(venue_name)
    event = {
        "title": pick_field(members, "title") or venue_name,
        "venue_id": venue_id,
        "venue_name": venue_name,
        "address": venue_address(resolved, members),
        "dates": dates,
        "time": pick_field(members, "time"),
        "is_free": any(bool(member.get("is_free")) for member in members),
        "price_min": pick_field(members, "price_min"),
        "price_text": pick_field(members, "price_text"),
        "ticket_url": pick_field(members, "ticket_url"),
        "image_url": pick_field(members, "image_url"),
        "sources": sorted({member.get("source", "") for member in members}),
    }
    event["price_label"] = price_label(event)
    event["display_title"] = choose_display_title(members, event["title"])
    event["slug"] = f"{slugify(event['title'])}-{dates[0]}" if dates else slugify(event["title"])
    return event


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def collect_site_events(data_dir: Path, today: date) -> tuple[list[dict], list[dict], dict]:
    """Build the upcoming catalog: clusters merged, singles kept, past dropped."""
    normalized = load_json(data_dir / "events_normalized.json")
    deduped = load_json(data_dir / "events_deduped.json")
    registry = load_json(data_dir / "venues.json").get("venues", [])
    last_run_path = data_dir / "last_run.json"
    last_run = load_json(last_run_path) if last_run_path.exists() else {}

    index = venue_index(registry)
    clustered = {event_ref(member) for cluster in deduped.get("clusters", []) for member in cluster["events"]}

    events = [
        merge_members(cluster["events"], index, today, cluster.get("venue_name"))
        for cluster in deduped.get("clusters", [])
    ]
    events += [merge_members([event], index, today) for event in normalized if event_ref(event) not in clustered]

    events = [event for event in events if event["dates"]]
    events.sort(key=lambda event: (event["dates"][0], event["time"] or "99:99", event["title"].casefold()))
    seen: dict[str, int] = {}
    for event in events:
        base = event["slug"]
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count:
            event["slug"] = f"{base}-{count + 1}"
    return events, registry, last_run



# Titles from the ticketeras arrive in shouty, date-stamped shapes
# ("SANTO PECADO EN ABBEY ROAD 16-10"). The data stays untouched; the display
# title prefers a member title that is already well cased and strips the date.
DATE_SUFFIX_RE = re.compile(r"[,\s-]*\b\d{1,2}[-/]\d{1,2}\b\s*$")
WEEKDAY_PREFIX_RE = re.compile(
    r"^\s*(?:lun|mar|mi[eé]|jue|vie|s[áa]b|dom)[a-záéíóú]*\.?\s+\d{1,2}[-/]\d{1,2}\s+",
    re.IGNORECASE,
)
SMALL_WORDS = {
    "a", "al", "and", "con", "de", "del", "el", "en", "la", "las", "lo", "los",
    "o", "of", "para", "por", "the", "u", "vs", "y",
}
KEEP_CAPS = {"dj", "vj", "mc", "ii", "iii", "iv", "led", "mdp", "tv", "uv"}


def clean_title(text: str | None) -> str:
    """Drop a leading weekday+date and a trailing date token."""
    value = WEEKDAY_PREFIX_RE.sub("", text or "")
    value = DATE_SUFFIX_RE.sub("", value)
    return " ".join(value.split()).strip(" ,")


def looks_clean(text: str) -> bool:
    """True when the title is not shouted and carries no embedded date."""
    return any(char.islower() for char in text) and not re.search(r"\b\d{1,2}[-/]\d{1,2}\b", text)


def title_case(text: str) -> str:
    """'THE BEATLES SINFONICO' -> 'The Beatles Sinfonico'."""
    words = []
    for position, word in enumerate(text.split()):
        lowered = word.lower()
        if lowered in KEEP_CAPS:
            words.append(word.upper())
        elif position > 0 and lowered in SMALL_WORDS:
            words.append(lowered)
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)


def choose_display_title(members: list[dict], fallback: str) -> str:
    """Prefer a well-cased member title (seller order), else fix the fallback."""
    ranked = sorted(
        members,
        key=lambda member: SOURCE_ORDER.index(member["source"]) if member.get("source") in SOURCE_ORDER else len(SOURCE_ORDER),
    )
    candidates = [clean_title(member.get("title")) for member in ranked]
    candidates = [candidate for candidate in candidates if candidate]
    for candidate in candidates:
        if looks_clean(candidate):
            return candidate
    if candidates:
        return title_case(candidates[0])
    return clean_title(fallback) or fallback


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
WEEKDAY_FULL = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
SOURCE_LABELS = {
    "municipal": "Municipal",
    "articket": "Articket",
    "cultutickets": "CultuTickets",
    "clubtri": "Club TRI",
}
THUMB_VARIANTS = 4


def primary_date(event: dict) -> str:
    """The date a row sits under: the first upcoming occurrence."""
    return event["dates"][0]


def in_weekend(iso: str, today: date) -> bool:
    start, end = weekend_window(today)
    return start <= date.fromisoformat(iso) <= end


def format_day_long(iso: str) -> str:
    """'2026-10-23' -> 'Viernes 23 de octubre'."""
    parsed = date.fromisoformat(iso)
    return f"{WEEKDAY_FULL[parsed.weekday()]} {parsed.day} de {MONTHS_ES[parsed.month - 1]}"


def format_month_year(day: date) -> str:
    """'Octubre 2026'."""
    return f"{MONTHS_ES[day.month - 1].capitalize()} {day.year}"


def format_weekend_kicker(today: date) -> str:
    """'Jueves 22 — Domingo 25 · Octubre 2026' (single day collapses)."""
    start, end = weekend_window(today)
    month = format_month_year(start)
    if start == end:
        return f"{WEEKDAY_FULL[start.weekday()]} {start.day} · {month}"
    return f"{WEEKDAY_FULL[start.weekday()]} {start.day} — {WEEKDAY_FULL[end.weekday()]} {end.day} · {month}"


def initials(title: str) -> str:
    """'Koino Yokan en Club TRI' -> 'KY'; falls back to the first character."""
    words = [word for word in re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", title or "") if len(word) > 2]
    if not words:
        return (title or "?").strip()[:1].upper() or "?"
    return "".join(word[0].upper() for word in words[:2])


def thumb_variant(seed: str) -> int:
    """Stable 0..3 bucket so typographic thumbnails vary by venue."""
    return sum(ord(char) for char in (seed or "")) % THUMB_VARIANTS


def maps_url(address: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote(f"{address}, Mar del Plata, Argentina")


def search_blob(event: dict) -> str:
    """Normalized haystack for the client-side search box."""
    parts = [event.get("title") or "", event.get("venue_name") or "", event.get("address") or ""]
    return normalize_key(" ".join(parts))


def price_parts(event: dict) -> tuple[str, str] | None:
    """('$20.000', 'desde') / ('Gratis', '') / None."""
    label = event.get("price_label")
    if not label:
        return None
    if label == "Gratis":
        return ("Gratis", "")
    if label.startswith("Desde "):
        return (label[len("Desde "):], "desde")
    return (label, "entrada")


def group_by_date(events: list[dict]) -> list[tuple[str, list[dict]]]:
    """Date -> events, ordered by date (events keep their date/time order)."""
    groups: dict[str, list[dict]] = {}
    for event in events:
        groups.setdefault(primary_date(event), []).append(event)
    return sorted(groups.items())


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"


def render_theme_boot() -> str:
    """Applies the stored (or system) theme before the stylesheet paints."""
    return (
        "<script>(function(){try{var k='cartelera-theme';"
        "var s=localStorage.getItem(k);"
        "var d=s==='light'||s==='dark'?s:(window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');"
        "document.documentElement.setAttribute('data-theme',d);"
        "}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();</script>"
    )


def render_header() -> str:
    return (
        '<header class="topbar">'
        '<div class="topbar__in">'
        '<a class="brand" href="#top" aria-label="Cartelera MDP, inicio">'
        '<span class="brand__mark" aria-hidden="true">MDP</span>'
        '<span class="brand__name">Cartelera<s>.</s></span>'
        '<span class="brand__city">Mar del Plata</span>'
        "</a>"
        '<label class="search">'
        '<span class="search__icon" aria-hidden="true">⌕</span>'
        '<input type="search" id="search" placeholder="Buscar banda o sala" '
        'aria-label="Buscar por banda, sala o dirección" autocomplete="off">'
        "</label>"
        '<button type="button" class="theme-toggle" id="theme-toggle" aria-label="Cambiar tema" title="Cambiar tema">'
        '<svg class="theme-toggle__icon theme-toggle__icon--sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<circle cx="12" cy="12" r="4.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>'
        "</svg>"
        '<svg class="theme-toggle__icon theme-toggle__icon--moon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>'
        "</svg>"
        "</button>"
        "</div>"
        "</header>"
    )


def render_intro(events: list[dict], today: date) -> str:
    venues = len({event["venue_id"] for event in events})
    free = sum(1 for event in events if event["is_free"])
    has_weekend = any(in_weekend(primary_date(event), today) for event in events)
    if has_weekend:
        kicker = format_weekend_kicker(today)
        heading = "Qué hay este finde<br>en <em>Mar del Plata</em>"
    else:
        kicker = "Próximos eventos"
        heading = "Qué hay<br>en <em>Mar del Plata</em>"
    return (
        '<section class="intro" id="top">'
        "<div>"
        f'<p class="kicker">{esc(kicker)}</p>'
        f"<h1>{heading}</h1>"
        "</div>"
        '<div class="intro__stats">'
        f'<span data-label="Eventos"><b>{len(events)}</b></span>'
        f'<span data-label="Salas"><b>{venues}</b></span>'
        f'<span data-label="Gratis"><b>{free}</b></span>'
        "</div>"
        "</section>"
    )


def render_day_nav(groups: list[tuple[str, list[dict]]], today: date) -> str:
    """Finde + one tab per weekend day with events + Todo."""
    start, end = weekend_window(today)
    weekend_dates = [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]
    by_date = dict(groups)
    weekend_count = sum(len(by_date.get(iso, [])) for iso in weekend_dates)
    buttons: list[str] = []
    if weekend_count:
        buttons.append(
            f'<button type="button" class="day is-on" data-view="weekend" aria-pressed="true">'
            f"<b>Finde</b><i>{weekend_count}</i></button>"
        )
    for iso in weekend_dates:
        day_events = by_date.get(iso)
        if not day_events:
            continue
        parsed = date.fromisoformat(iso)
        buttons.append(
            f'<button type="button" class="day" data-view="{iso}" aria-pressed="false">'
            f"<b>{WEEKDAY_ABBR[parsed.weekday()]}</b><span>{parsed.day:02d}</span>"
            f"<i>{len(day_events)}</i></button>"
        )
    total = sum(len(day_events) for _, day_events in groups)
    all_active = " is-on" if not weekend_count else ""
    buttons.append(
        f'<button type="button" class="day day--all{all_active}" data-view="all" '
        f'aria-pressed="{"true" if not weekend_count else "false"}"><b>Todo</b><i>{total}</i></button>'
    )
    return f'<nav class="daynav" aria-label="Filtrar por día">{"".join(buttons)}</nav>'


def top_venues(events: list[dict], limit: int = 3) -> list[tuple[str, str, int]]:
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for event in events:
        counts[event["venue_id"]] = counts.get(event["venue_id"], 0) + 1
        names[event["venue_id"]] = event["venue_name"]
    ranked = sorted(
        ((names[venue_id], venue_id, count) for venue_id, count in counts.items()),
        key=lambda row: (-row[2], row[0].casefold()),
    )
    return ranked[:limit]


def render_toolbar(events: list[dict]) -> str:
    free = sum(1 for event in events if event["is_free"])
    chips = [
        f'<button type="button" class="chip" data-filter="free" aria-pressed="false">'
        f"Gratis <em>{free}</em></button>"
    ]
    for name, venue_id, count in top_venues(events):
        chips.append(
            f'<button type="button" class="chip" data-filter="venue" data-value="{esc(venue_id)}" '
            f'aria-pressed="false">{esc(name)} <em>{count}</em></button>'
        )
    return (
        '<div class="toolbar" role="group" aria-label="Filtros de la agenda">'
        f'{"".join(chips)}'
        '<p class="toolbar__count" id="filter-count" aria-live="polite"></p>'
        "</div>"
    )


def pick_featured(events: list[dict], today: date) -> dict | None:
    """S8: earliest weekend event with poster and ticket, then with poster, then any.

    "Weekend" means the row's primary date (the day it is listed under), so the
    featured event always appears in the weekend agenda.
    """
    weekend = [event for event in events if in_weekend(primary_date(event), today)]
    for pool in (
        [event for event in weekend if event.get("image_url") and event.get("ticket_url")],
        [event for event in weekend if event.get("image_url")],
        weekend,
    ):
        if pool:
            return pool[0]
    return None


def ticket_host(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host


def render_featured(event: dict | None) -> str:
    if not event:
        return ""
    parsed = date.fromisoformat(primary_date(event))
    price = price_parts(event)
    price_html = ""
    if price:
        value, note = price
        suffix = f"<small>{esc(note)}</small>" if note else ""
        price_html = f'<div class="feature__price">{esc(value)}{suffix}</div>'
    ticket = event.get("ticket_url")
    host = ticket_host(ticket)
    actions = []
    if ticket:
        actions.append(
            f'<a class="btn btn--primary" href="{esc(ticket)}" target="_blank" rel="noopener" '
            f'data-outbound="ticket" data-event-id="{esc(event["slug"])}">Sacar entrada</a>'
        )
    actions.append(
        f'<button type="button" class="btn btn--ghost js-share" data-event-id="{esc(event["slug"])}">'
        "Compartir</button>"
    )
    where = esc(event["venue_name"])
    if event.get("address"):
        where += f" · {esc(event['address'])}"
    meta_bits = [
        f"<b>{esc(format_day_long(primary_date(event)))}</b>",
    ]
    if event.get("time"):
        meta_bits.append(esc(event["time"]))
    meta_bits.append(where)
    if host:
        meta_bits.append(f"Venta en {esc(host)}")
    meta = '<i>·</i>'.join(meta_bits[:1]) + "".join(f"<i>·</i>{bit}" for bit in meta_bits[1:])
    poster = (
        f'<img src="{esc(event["image_url"])}" alt="" loading="lazy" decoding="async" data-thumb>'
        if event.get("image_url")
        else f'<div class="feature__fallback" aria-hidden="true"><b>{esc(initials(event["title"]))}</b></div>'
    )
    return (
        '<section class="feature" aria-label="Destacado del finde">'
        '<div class="feature__poster">'
        f"{poster}"
        f'<div class="feature__badge"><b>{WEEKDAY_ABBR[parsed.weekday()].upper()}</b><span>{parsed.day:02d}</span></div>'
        "</div>"
        '<div class="feature__body">'
        '<p class="kicker">Destacado del finde</p>'
        f"<h2>{esc(event['display_title'])}</h2>"
        f'<p class="feature__meta">{meta}</p>'
        f'<div class="feature__actions">{"".join(actions)}{price_html}</div>'
        "</div>"
        "</section>"
    )


def render_thumb(event: dict) -> str:
    if event.get("image_url"):
        return (
            '<div class="row__thumb">'
            f'<img src="{esc(event["image_url"])}" alt="" loading="lazy" decoding="async" data-thumb>'
            "</div>"
        )
    return (
        f'<div class="row__thumb row__thumb--type t{thumb_variant(event["venue_id"])}" aria-hidden="true">'
        f"{esc(initials(event['display_title']))}</div>"
    )


def render_tags(event: dict) -> str:
    tags = []
    extra = len(event["dates"]) - 1
    if extra > 0:
        tags.append(f'<span class="tag tag--more">+{extra} fechas</span>')
    if not tags:
        return ""
    return " " + "".join(tags)


def render_row_details(event: dict) -> str:
    dates = " · ".join(format_day_long(iso) for iso in event["dates"])
    facts = [f"<p><b>Fechas:</b> {esc(dates)}</p>"]
    if event.get("address"):
        facts.append(f"<p><b>Dónde:</b> {esc(event['address'])}</p>")
    sources = [SOURCE_LABELS.get(source, source) for source in event.get("sources") or []]
    if sources:
        facts.append(f"<p><b>Datos:</b> {esc(' + '.join(sources))}</p>")
    actions = []
    if event.get("ticket_url"):
        host = ticket_host(event["ticket_url"])
        label = f"Comprar en {host}" if host else "Comprar"
        actions.append(
            f'<a class="btn btn--primary" href="{esc(event["ticket_url"])}" target="_blank" rel="noopener" '
            f'data-outbound="ticket" data-event-id="{esc(event["slug"])}">{esc(label)} ↗</a>'
        )
    if event.get("address"):
        actions.append(
            f'<a class="btn btn--ghost" href="{esc(maps_url(event["address"]))}" target="_blank" rel="noopener">'
            "Cómo llegar</a>"
        )
    actions.append(
        f'<button type="button" class="btn btn--ghost js-share" data-event-id="{esc(event["slug"])}">'
        "Compartir</button>"
    )
    return (
        f'<div class="row__details" id="detail-{esc(event["slug"])}" hidden>'
        f'<div class="row__facts">{"".join(facts)}</div>'
        f'<div class="row__actions">{"".join(actions)}</div>'
        "</div>"
    )


def render_row(event: dict, today: date) -> str:
    slug = esc(event["slug"])
    primary = primary_date(event)
    price = price_parts(event)
    if event["is_free"]:
        price_html = '<span class="row__price row__price--free">Gratis<small>sin entrada</small></span>'
    elif price:
        value, note = price
        note_html = f"<small>{esc(note)}</small>" if note else ""
        price_html = f'<span class="row__price">{esc(value)}{note_html}</span>'
    else:
        price_html = '<span class="row__price row__price--dim">Consultar<small>en puerta</small></span>'

    if event.get("ticket_url"):
        cta = (
            f'<a class="row__cta row__cta--buy" href="{esc(event["ticket_url"])}" target="_blank" '
            f'rel="noopener" data-outbound="ticket" data-event-id="{slug}">Entradas</a>'
        )
    else:
        cta = ""

    time_html = f'{esc(event["time"])}<small>hs</small>' if event.get("time") else "—"
    venue = esc(event["venue_name"])
    address = f'<i>·</i>{esc(event["address"])}' if event.get("address") else ""
    attrs = (
        f'data-row data-id="{slug}" data-date="{primary}" '
        f'data-in-weekend="{1 if in_weekend(primary, today) else 0}" '
        f'data-free="{1 if event["is_free"] else 0}" data-venue="{esc(event["venue_id"])}" '
        f'data-search="{esc(search_blob(event))}" data-initials="{esc(initials(event["display_title"]))}" '
        f'data-title="{esc(event["display_title"])}" data-venue-name="{esc(event["venue_name"])}" '
        f'data-when="{esc(format_when(event["dates"], event["time"]))}" '
        f'data-dates="{esc(" ".join(event["dates"]))}"'
    )
    return (
        f'<article class="row" {attrs}>'
        f'<div class="row__time">{time_html}</div>'
        f"{render_thumb(event)}"
        '<div class="row__main">'
        f'<h3 class="row__title">{esc(event["display_title"])}</h3>'
        f'<p class="row__meta"><span class="row__venue">{venue}</span>{address}{render_tags(event)}</p>'
        "</div>"
        f'<div class="row__side">{price_html}{cta}</div>'
        f'<button type="button" class="row__more js-disclose" aria-expanded="false" '
        f'aria-controls="detail-{slug}" aria-label="Ver detalle de {esc(event["display_title"])}">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 9l6 6 6-6"/></svg>'
        "</button>"
        f"{render_row_details(event)}"
        "</article>"
    )


def render_agenda(groups: list[tuple[str, list[dict]]], today: date, default_view: str) -> str:
    blocks = []
    for iso, day_events in groups:
        weekend = in_weekend(iso, today)
        hidden = "" if default_view in {"weekend", "all"} and (default_view == "all" or weekend) else " hidden"
        parsed = date.fromisoformat(iso)
        rows = "\n".join(render_row(event, today) for event in day_events)
        blocks.append(
            f'<section class="daygroup" data-date="{iso}" data-in-weekend="{1 if weekend else 0}"'
            f'{hidden} aria-label="{esc(format_day_long(iso))}">'
            '<div class="daygroup__head">'
            f"<h2><b>{WEEKDAY_FULL[parsed.weekday()]}</b> <em>{parsed.day} de {MONTHS_ES[parsed.month - 1]}</em></h2>"
            f'<span>{plural(len(day_events), "evento", "eventos")}</span>'
            "</div>"
            f"{rows}"
            "</section>"
        )
    return f'<div class="agenda" id="agenda">{"".join(blocks)}</div>'


def render_json_ld(weekend: list[dict]) -> str:
    items = []
    for position, event in enumerate(weekend, start=1):
        start_date = event["dates"][0] + (f"T{event['time']}" if event["time"] else "")
        address = {"@type": "PostalAddress", "addressLocality": "Mar del Plata"}
        if event.get("address"):
            address["streetAddress"] = event["address"]
        item = {
            "@type": "Event",
            "name": event["display_title"],
            "startDate": start_date,
            "location": {"@type": "Place", "name": event["venue_name"], "address": address},
            "url": event["ticket_url"] or SITE_URL,
        }
        if event["is_free"]:
            item["isAccessibleForFree"] = True
        elif event["price_min"] is not None:
            item["offers"] = {
                "@type": "Offer",
                "price": event["price_min"],
                "priceCurrency": "ARS",
                "url": event["ticket_url"] or SITE_URL,
            }
        items.append({"@type": "ListItem", "position": position, "item": item})
    payload = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": SITE_URL,
            "inLanguage": "es-AR",
        },
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Este finde en Mar del Plata",
            "itemListElement": items,
        },
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")


def render_footer(last_run: dict) -> str:
    updated = format_updated(last_run)
    updated_html = f'<span>Actualizado {esc(updated)}</span>' if updated else ""
    return (
        '<footer class="foot">'
        "<p>Datos de <b>agenda municipal</b>, <b>Articket</b>, <b>CultuTickets</b> y <b>Club TRI</b>. "
        "La compra se hace en el sitio oficial de cada ticketera.</p>"
        f"{updated_html}"
        "</footer>"
    )


def events_payload(events: list[dict], today: date) -> dict:
    """Everything app.js needs, inlined so the page never fetches anything."""
    start, end = weekend_window(today)
    seven_start, seven_end = window_bounds("7days", today)
    return {
        "site": {"name": SITE_NAME, "url": SITE_URL},
        "today": today.isoformat(),
        "windows": {
            "weekend": {"start": start.isoformat(), "end": end.isoformat()},
            "7days": {"start": seven_start.isoformat(), "end": seven_end.isoformat()},
        },
        "events": [
            {
                "id": event["slug"],
                "title": event["display_title"],
                "venue_id": event["venue_id"],
                "venue_name": event["venue_name"],
                "address": event["address"],
                "dates": event["dates"],
                "time": event["time"],
                "is_free": event["is_free"],
                "price_label": event["price_label"],
                "ticket_url": event["ticket_url"],
                "image_url": event["image_url"],
            }
            for event in events
        ],
    }


def render_index(events: list[dict], last_run: dict, today: date) -> str:
    groups = group_by_date(events)
    start, end = weekend_window(today)
    weekend = [event for event in events if matches_window(event["dates"], "weekend", today)]
    has_weekend = bool(weekend)
    default_view = "weekend" if has_weekend else "all"
    featured = render_featured(pick_featured(events, today))
    if events:
        empty_html = (
            '<p class="empty-state" id="empty-state" hidden>'
            "No hay eventos con esos filtros. "
            '<button type="button" id="clear-filters">Limpiar filtros</button>'
            "</p>"
        )
    else:
        empty_html = '<p class="empty-state" id="empty-state">No hay eventos cargados todavía.</p>'
    payload = json.dumps(events_payload(events, today), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = f"{SITE_NAME} — Qué hay este finde en Mar del Plata"
    return f"""<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(SITE_DESCRIPTION)}">
<meta name="color-scheme" content="dark light">
<link rel="canonical" href="{esc(SITE_URL)}">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(SITE_NAME)}">
<meta property="og:locale" content="es_AR">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(SITE_DESCRIPTION)}">
<meta property="og:url" content="{esc(SITE_URL)}">
<meta name="twitter:card" content="summary">
{render_theme_boot()}
<link rel="stylesheet" href="assets/style.css">
<script type="application/ld+json">
{render_json_ld(weekend)}
</script>
</head>
<body>
<a class="skip-link" href="#agenda">Saltar a la agenda</a>
{render_header()}
<main class="shell">
{render_intro(events, today)}
{render_day_nav(groups, today)}
{render_toolbar(events)}
{featured}
{render_agenda(groups, today, default_view)}
{empty_html}
{render_footer(last_run)}
</main>
<script id="events-data" type="application/json">{payload}</script>
<script src="assets/app.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Build entry point
# ---------------------------------------------------------------------------


def build(data_dir: Path = DEFAULT_DATA_DIR, out_dir: Path = DEFAULT_OUT_DIR, today: date | None = None) -> dict:
    """Generate the static site; returns a small stats summary."""
    today = today or today_in_art()
    events, _registry, last_run = collect_site_events(data_dir, today)
    weekend_count = sum(1 for event in events if matches_window(event["dates"], "weekend", today))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(exist_ok=True)
    (out_dir / "index.html").write_text(render_index(events, last_run, today), encoding="utf-8")
    shutil.copyfile(ASSETS_SRC / "style.css", out_dir / "assets" / "style.css")
    shutil.copyfile(ASSETS_SRC / "app.js", out_dir / "assets" / "app.js")
    shutil.copyfile(ASSETS_SRC / "favicon.svg", out_dir / "favicon.svg")

    return {
        "today": today.isoformat(),
        "upcoming": len(events),
        "weekend": weekend_count,
        "venues": len({event["venue_id"] for event in events}),
        "files": ["index.html", "assets/style.css", "assets/app.js", "favicon.svg"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Cartelera MDP static site.")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="output directory (default: site/)")
    parser.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD), for deterministic builds")
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else None
    stats = build(out_dir=Path(args.out), today=today)
    print(f"{SITE_NAME} -> {args.out}")
    print(f"today: {stats['today']}")
    print(f"upcoming events: {stats['upcoming']}")
    print(f"weekend events: {stats['weekend']}")
    print(f"venues: {stats['venues']}")
    for name in stats["files"]:
        print(f"  wrote {Path(args.out) / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
