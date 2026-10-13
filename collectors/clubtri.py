"""Club TRI venue agenda collector (clubtri.com).

The homepage is the agenda (server-rendered). Dates come as
"Mié 14 de Octubre" without a year, so lib.dates infers it.
"""

import hashlib
import re

import requests
from bs4 import BeautifulSoup

from lib.dates import extract_time, parse_spanish_date, to_iso
from lib.schema import Event

URL = "https://clubtri.com/"
USER_AGENT = "cartelera-mdp-spike/0.1 (local research)"
SOURCE = "clubtri"
VENUE_NAME = "Club TRI"
VENUE_RAW = "Club TRI, XX de Septiembre 2650, Mar del Plata"
SELLERS = {
    "articket.com.ar": "Articket",
    "passline.com": "Passline",
    "ticketmas.ar": "Ticketmas",
}
_IMAGE_ID_RE = re.compile(r"/imgs/agenda/(\d+)/")


def collect():
    response = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content.decode("utf-8", errors="replace"), "html.parser")
    records = []
    for card in soup.select("div.card-hire"):
        title_node = card.find("h2")
        date_node = card.find("h3")
        time_node = card.find("h4")
        status_node = card.select_one("a.btn_vermas")
        link_node = card.find("a")
        image_node = card.find("img")
        image_url = image_node["src"] if image_node and image_node.has_attr("src") else None
        image_id_match = _IMAGE_ID_RE.search(image_url or "")
        records.append(
            {
                "source": SOURCE,
                "title": title_node.get_text(strip=True) if title_node else "",
                "date_text": date_node.get_text(strip=True) if date_node else "",
                "time_text": time_node.get_text(strip=True) if time_node else "",
                "status_text": status_node.get_text(strip=True) if status_node else "",
                "link": link_node["href"] if link_node and link_node.has_attr("href") else "",
                "image_url": image_url,
                "image_id": image_id_match.group(1) if image_id_match else None,
                "raw_url": URL,
            }
        )
    return records


def normalize(records):
    events = []
    for record in records:
        is_ticket_link = any(host in record["link"] for host in SELLERS)
        seller = next((name for host, name in SELLERS.items() if host in record["link"]), None)
        status = record["status_text"].lower()
        is_free = True if "gratis" in status else (False if status else None)
        seed = f"{record['title']}|{record['date_text']}"
        source_event_id = record["image_id"] or "clubtri-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
        date_iso = to_iso(parse_spanish_date(record["date_text"]))
        events.append(
            Event(
                source=SOURCE,
                source_event_id=source_event_id,
                title=record["title"],
                venue_name=VENUE_NAME,
                venue_raw=VENUE_RAW,
                date_start=date_iso,
                date_end=date_iso,
                time=extract_time(record["time_text"]),
                is_free=is_free,
                price_text=record["status_text"] or None,
                price_min=None,
                currency=None,
                ticket_url=record["link"] if is_ticket_link else None,
                seller=seller,
                image_url=record["image_url"],
                city="Mar del Plata",
                raw_url=record["raw_url"],
            )
        )
    return events
