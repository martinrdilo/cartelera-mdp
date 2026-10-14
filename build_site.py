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


def format_range(start: date, end: date) -> str:
    """'Jue 15/10 – Dom 18/10'."""
    return f"{format_date_short(start.isoformat())} – {format_date_short(end.isoformat())}"


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


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"


def render_media(event: dict) -> str:
    """Poster when available, a quiet placeholder with the initial otherwise."""
    if event.get("image_url"):
        return (
            '<div class="card__media">'
            f'<img src="{esc(event["image_url"])}" alt="" loading="lazy" decoding="async">'
            "</div>"
        )
    initial = esc((event["title"] or "?").strip()[:1].upper())
    return f'<div class="card__media card__media--empty" aria-hidden="true">{initial}</div>'


def render_card(event: dict, scope: str) -> str:
    venue_line = esc(event["venue_name"])
    if event.get("address"):
        venue_line += f' <span class="card__address">{esc(event["address"])}</span>'
    price = event.get("price_label")
    if price:
        modifier = " card__price--free" if price == "Gratis" else ""
        price_html = f'<p class="card__price{modifier}">{esc(price)}</p>'
    else:
        price_html = ""
    actions = []
    if event.get("ticket_url"):
        actions.append(
            f'<a class="btn btn--primary" href="{esc(event["ticket_url"])}" target="_blank" '
            'rel="noopener" data-outbound="ticket" '
            f'data-event-id="{esc(event["slug"])}">Sacar entrada</a>'
        )
    elif not event["is_free"]:
        # No online sale link in any source: say so instead of offering a dead button.
        actions.append('<span class="btn btn--muted">Sin venta online</span>')
    actions.append(
        f'<button type="button" class="btn btn--ghost js-share" data-event-id="{esc(event["slug"])}">'
        "Compartir</button>"
    )
    card_attrs = (
        f'data-event-id="{esc(event["slug"])}" data-card-scope="{scope}" '
        f'data-venue="{esc(event["venue_id"])}" data-free="{1 if event["is_free"] else 0}" '
        f'data-dates="{esc(" ".join(event["dates"]))}" data-time="{esc(event["time"] or "")}" '
        f'data-title="{esc(event["title"])}" data-venue-name="{esc(event["venue_name"])}"'
    )
    return (
        f'<article class="card" {card_attrs}>'
        f"{render_media(event)}"
        '<div class="card__body">'
        f'<h3 class="card__title">{esc(event["title"])}</h3>'
        f'<p class="card__venue">{venue_line}</p>'
        f'<p class="card__when">{esc(format_when(event["dates"], event["time"]))}</p>'
        f'<div class="card__foot">{price_html}'
        f'<div class="card__actions">{"".join(actions)}</div>'
        "</div></div></article>"
    )


def venue_options(events: list[dict]) -> list[tuple[str, str, int]]:
    """(display name, venue id, upcoming count) for venues with events, A-Z."""
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for event in events:
        counts[event["venue_id"]] = counts.get(event["venue_id"], 0) + 1
        names[event["venue_id"]] = event["venue_name"]
    return sorted(
        ((names[venue_id], venue_id, count) for venue_id, count in counts.items()),
        key=lambda row: row[0].casefold(),
    )


def render_filters(events: list[dict]) -> str:
    options = "\n".join(
        f'<option value="{esc(venue_id)}">{esc(name)} ({count})</option>'
        for name, venue_id, count in venue_options(events)
    )
    return (
        '<div class="filters">'
        '<div class="filters__row" role="group" aria-label="Rango de fechas">'
        '<button type="button" class="chip" data-window="weekend" aria-pressed="false">Este finde</button>'
        '<button type="button" class="chip" data-window="7days" aria-pressed="false">Próximos 7 días</button>'
        '<button type="button" class="chip is-active" data-window="all" aria-pressed="true">Todos</button>'
        "</div>"
        '<div class="filters__row">'
        '<label class="filters__label" for="venue-filter">Lugar</label>'
        f'<select id="venue-filter"><option value="">Todos los lugares</option>{options}</select>'
        '<label class="filters__check"><input type="checkbox" id="free-filter"> Gratis</label>'
        "</div>"
        "</div>"
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
                "title": event["title"],
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


def render_cards(events: list[dict], scope: str) -> str:
    return "\n".join(render_card(event, scope) for event in events)


def render_json_ld(weekend: list[dict]) -> str:
    items = []
    for position, event in enumerate(weekend, start=1):
        start_date = event["dates"][0] + (f"T{event['time']}" if event["time"] else "")
        address = {"@type": "PostalAddress", "addressLocality": "Mar del Plata"}
        if event.get("address"):
            address["streetAddress"] = event["address"]
        item = {
            "@type": "Event",
            "name": event["title"],
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
    updated_html = f'<p class="site-foot__updated">Actualizado: {esc(updated)}</p>' if updated else ""
    return (
        "<footer class=\"site-foot\">"
        "<p>Datos: agenda municipal EMTUR, Articket, CultuTickets, Club TRI. "
        "La compra se hace en el sitio oficial de cada ticketera.</p>"
        f"{updated_html}"
        "</footer>"
    )


def render_index(events: list[dict], last_run: dict, today: date) -> str:
    start, end = weekend_window(today)
    weekend = [event for event in events if matches_window(event["dates"], "weekend", today)]
    if weekend:
        weekend_body = render_cards(weekend, "weekend")
        hero_more = '<p class="hero__more"><a href="#todos">Ver todos los eventos</a></p>'
    else:
        weekend_body = (
            '<p class="empty">Todavía no hay shows cargados para este finde — '
            '<a href="#todos">mirá todos los eventos</a>.</p>'
        )
        hero_more = ""
    hero_sub = f"{esc(format_range(start, end))} · {esc(plural(len(weekend), 'show', 'shows'))}"
    payload = json.dumps(events_payload(events, today), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(SITE_NAME)} — Qué hay este finde en Mar del Plata</title>
<meta name="description" content="{esc(SITE_DESCRIPTION)}">
<link rel="canonical" href="{esc(SITE_URL)}">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(SITE_NAME)}">
<meta property="og:locale" content="es_AR">
<meta property="og:title" content="{esc(SITE_NAME)} — Qué hay este finde en Mar del Plata">
<meta property="og:description" content="{esc(SITE_DESCRIPTION)}">
<meta property="og:url" content="{esc(SITE_URL)}">
<meta name="twitter:card" content="summary">
<link rel="stylesheet" href="assets/style.css">
<script type="application/ld+json">
{render_json_ld(weekend)}
</script>
</head>
<body>
<a class="skip-link" href="#todos">Saltar a la lista de eventos</a>
<header class="site-head">
<p class="site-head__brand">{esc(SITE_NAME)}</p>
<p class="site-head__tagline">{esc(SITE_TAGLINE)}</p>
</header>
<main>
<section class="hero" aria-labelledby="finde-title">
<h1 id="finde-title">Este finde</h1>
<p class="hero__sub">{hero_sub}</p>
<div class="cards" id="weekend-list">
{weekend_body}
</div>
{hero_more}
</section>
<section class="all" id="todos" aria-labelledby="todos-title">
<h2 id="todos-title">Todos los eventos</h2>
<p class="all__sub">{esc(plural(len(events), "evento", "eventos"))} con fecha a partir de hoy.</p>
{render_filters(events)}
<p class="filters__count" id="filter-count" aria-live="polite"></p>
<p class="empty" id="empty-filter" hidden>No hay eventos con esos filtros — probá sacar alguno.</p>
<div class="cards" id="all-list">
{render_cards(events, "all")}
</div>
</section>
</main>
{render_footer(last_run)}
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
