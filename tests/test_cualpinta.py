"""Tests for the Cual Pinta collector (sitemap + JSON-LD event detail pages).

Every test is offline: `_fetch_sitemap` and `_fetch_detail` are replaced with
fixtures so `collect()` never touches the network.
"""

import json
from pathlib import Path

import pytest
import requests

import collectors.cualpinta as cualpinta

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE = "https://www.cualpinta.com"
SITEMAP_URL = f"{BASE}/sitemap.xml"
EVENT_URL = f"{BASE}/mar-del-plata/eventos/{{slug}}"

# Detail fixtures captured from the live site on 2026-10-23.
DETAIL_FIXTURES = {
    "zrock-ae4410": "cualpinta_detail_zrock.html",
    "https-www-plateanet-com-obra-34808-obra-el-20jefe-20del-20je": "cualpinta_detail_jefe.html",
    "alcatraz-y-terra-en-abbey-road": "cualpinta_detail_alcatraz.html",
    "hairspray": "cualpinta_detail_hairspray.html",
}

ZROCK_IMAGE = (
    "https://tevemsqyanpeztfjfqvx.supabase.co/storage/v1/object/public/"
    "eventos-imagenes/ingesta/1792592446376-rqonw9rr26j.jpg"
)
ZROCK_TICKET = "https://articket.com.ar/ZROCK-LOS-TOXICOS-SPLASH-SATIVA-JOVENES-INDOCUMENTADOS/"
JEFE_TICKET = "https://www.plateanet.com/obra/34808?obra=EL%20JEFE%20DEL%20JEFE..&paso=sectores"
ALCATRAZ_TICKET = "https://abbeyroadmdp.com.ar/evento/alcatraz-y-terra/"
HAIRSPRAY_TICKET = "https://www.ticketek.com.ar/hairspray/teatro-tronador"


def _load_html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _html(blocks=(), chips=(), anchors=()):
    """Build a minimal detail page with JSON-LD blocks, chips and anchors."""
    scripts = "".join(
        '<script type="application/ld+json">' + json.dumps(block) + "</script>" for block in blocks
    )
    chip_html = "".join(f'<span class="cp-chip">{chip}</span>' for chip in chips)
    link_html = "".join(f'<a href="{href}">link</a>' for href in anchors)
    return f"<html><head>{scripts}</head><body>{chip_html}{link_html}</body></html>"


def _event(**overrides):
    payload = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": "Demo",
        "startDate": "2026-11-01T20:00:00-03:00",
        "eventStatus": "https://schema.org/EventScheduled",
        "location": {
            "@type": "Place",
            "name": "Club Demo",
            "address": {"@type": "PostalAddress", "streetAddress": "Calle 123"},
        },
        "image": ["https://cdn.example.test/demo.jpg"],
        "offers": {
            "@type": "Offer",
            "price": 5000,
            "priceCurrency": "ARS",
            "url": "https://www.cualpinta.com/mar-del-plata/eventos/demo",
        },
        "url": "https://www.cualpinta.com/mar-del-plata/eventos/demo",
    }
    payload.update(overrides)
    return payload


def _detail_record(slug):
    record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES[slug]))
    record["source"] = "cualpinta"
    record["detail_url"] = EVENT_URL.format(slug=slug)
    return record


def _record(**overrides):
    record = {
        "source": "cualpinta",
        "detail_url": EVENT_URL.format(slug="demo"),
        "name": "Demo",
        "start_date": "2026-11-01T20:00:00-03:00",
        "end_date": None,
        "event_status": "https://schema.org/EventScheduled",
        "venue_name": "Club Demo",
        "street_address": "Calle 123",
        "price": 5000,
        "currency": "ARS",
        "image_url": "https://cdn.example.test/demo.jpg",
        "category": "Recital",
        "ticket_url": "https://articket.com.ar/demo/",
    }
    record.update(overrides)
    return record


@pytest.fixture
def cualpinta_source(monkeypatch):
    """Wire collect() to four real detail fixtures behind a small sitemap."""
    urls = [EVENT_URL.format(slug=slug) for slug in DETAIL_FIXTURES]
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<urlset>"
        + "".join(f"<url><loc>{url}</loc></url>" for url in urls)
        + '<url><loc>https://www.cualpinta.com/mar-del-plata</loc></url>'
        "</urlset>"
    )
    calls = {"sitemap": 0, "details": []}

    def fetch_sitemap():
        calls["sitemap"] += 1
        return sitemap

    def fetch_detail(url):
        calls["details"].append(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES[slug]))
        # Keep the collection tests about collection mechanics; the category
        # filter has its own tests below.
        record["category"] = "Recital"
        return record

    monkeypatch.setattr(cualpinta, "REQUEST_DELAY", 0)
    monkeypatch.setattr(cualpinta, "_fetch_sitemap", fetch_sitemap)
    monkeypatch.setattr(cualpinta, "_fetch_detail", fetch_detail)
    return urls, calls


class TestParseSitemap:
    def test_keeps_every_event_url_from_the_real_sitemap(self):
        urls = cualpinta.parse_sitemap(_load_html("cualpinta_sitemap.xml"))

        assert len(urls) == 144
        assert urls[0] == EVENT_URL.format(slug="fantasia-o-realidad-con-juancho-carbone")
        assert urls[-1] == EVENT_URL.format(slug="love-run-5k-palestra")
        assert all(url.startswith(EVENT_URL.format(slug="")) for url in urls)

    def test_ignores_non_event_urls(self):
        xml = (
            '<?xml version="1.0"?><urlset>'
            "<url><loc>https://www.cualpinta.com</loc></url>"
            "<url><loc>https://www.cualpinta.com/mar-del-plata/lugares/club-tri</loc></url>"
            "<url><loc>https://www.cualpinta.com/mar-del-plata/eventos/demo</loc></url>"
            "</urlset>"
        )

        assert cualpinta.parse_sitemap(xml) == [EVENT_URL.format(slug="demo")]

    def test_empty_input_returns_no_urls(self):
        assert cualpinta.parse_sitemap("") == []


class TestParseDetail:
    def test_real_recital_detail(self):
        record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES["zrock-ae4410"]))

        assert record["name"] == "ZROCK"
        assert record["start_date"] == "2026-10-30T21:00:00-03:00"
        assert record["end_date"] is None
        assert record["event_status"] == "https://schema.org/EventScheduled"
        assert record["venue_name"] == "Abbey Road"
        assert record["street_address"] == (
            "Av. Juan B. Justo 620, B7600 Mar del Plata, Provincia de Buenos Aires"
        )
        assert record["price"] == 15000
        assert record["currency"] == "ARS"
        assert record["image_url"] == ZROCK_IMAGE
        assert record["url"] == EVENT_URL.format(slug="zrock-ae4410")
        assert record["category"] == "Recital"
        assert record["ticket_url"] == ZROCK_TICKET

    def test_real_plateanet_detail(self):
        record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES[
            "https-www-plateanet-com-obra-34808-obra-el-20jefe-20del-20je"
        ]))

        assert record["name"] == "EL JEFE DEL JEFE"
        assert record["category"] == "Stand-up"
        assert record["ticket_url"] == JEFE_TICKET
        assert record["price"] == 50000

    def test_real_venue_site_detail(self):
        record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES["alcatraz-y-terra-en-abbey-road"]))

        assert record["name"] == "ALCATRAZ Y TERRA EN ABBEY ROAD"
        assert record["category"] == "Fiesta"
        assert record["ticket_url"] == ALCATRAZ_TICKET

    def test_real_range_detail(self):
        record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES["hairspray"]))

        assert record["name"] == "Hairspray"
        assert record["start_date"] == "2026-12-12T20:00:00-03:00"
        assert record["end_date"] == "2026-12-13"
        assert record["category"] == "Preestreno"
        assert record["ticket_url"] == HAIRSPRAY_TICKET

    def test_selects_the_event_block_among_several(self):
        html = _html(
            [
                {"@type": "Organization", "name": "Cual Pinta"},
                {"@type": "WebSite", "name": "Cual Pinta"},
                _event(name="El evento"),
                {"@type": "BreadcrumbList", "itemListElement": []},
            ]
        )

        record = cualpinta.parse_detail(html)

        assert record["name"] == "El evento"

    def test_selection_is_not_limited_to_the_first_block(self):
        # The live page carries eight ld+json blocks; the Event is the sixth.
        record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES["zrock-ae4410"]))

        assert record["name"] == "ZROCK"

    def test_category_ignores_plus_prefixed_chips(self):
        html = _html([_event()], chips=("+18", "Recital"))

        assert cualpinta.parse_detail(html)["category"] == "Recital"

    def test_external_ticket_link_skips_cualpinta_and_utility_hosts(self):
        html = _html(
            [_event()],
            anchors=(
                "https://www.cualpinta.com/mar-del-plata/eventos/demo",
                "https://instagram.com/club.tri",
                "https://wa.me/5492230000000",
                "https://www.google.com/maps/dir/?api=1&destination=-38.0,-57.5",
            ),
        )
        html = html.replace(
            "</body>",
            '<a href="https://articket.com.ar/DEMO/">tickets</a></body>',
        )

        assert cualpinta.parse_detail(html)["ticket_url"] == "https://articket.com.ar/DEMO/"

    def test_known_seller_wins_over_an_earlier_external_link(self):
        html = _html([_event()], anchors=("https://open.spotify.com/artist/demo",))
        html = html.replace(
            "</body>",
            '<a href="https://articket.com.ar/DEMO/">Comprar entrada</a></body>',
        )

        assert cualpinta.parse_detail(html)["ticket_url"] == "https://articket.com.ar/DEMO/"

    def test_auditorium_hall_comes_from_the_description(self):
        record = cualpinta.parse_detail(_load_html("cualpinta_detail_amniotika.html"))

        assert record["venue_name"] == "Teatro Auditorium"
        assert "sala Jorge Laureti" in record["description"]
        record.update(detail_url=EVENT_URL.format(slug="amniotika"), source="cualpinta")
        event = cualpinta.normalize([record])[0]
        assert event.venue_name == "Sala Jorge Laureti"

    def test_ticket_cta_wins_over_a_non_seller_link(self):
        html = _html([_event()], anchors=("https://artist.example.test/profile",))
        html = html.replace(
            "</body>",
            '<a href="https://venue.example.test/evento">Comprar entrada</a></body>',
        )

        assert (
            cualpinta.parse_detail(html)["ticket_url"]
            == "https://venue.example.test/evento"
        )

    def test_never_uses_the_cualpinta_offer_url_as_ticket_link(self):
        record = cualpinta.parse_detail(_html([_event()]))

        assert record["ticket_url"] is None

    def test_accepts_a_single_image_string(self):
        record = cualpinta.parse_detail(_html([_event(image="https://cdn.example.test/one.jpg")]))

        assert record["image_url"] == "https://cdn.example.test/one.jpg"

    def test_keeps_a_cancelled_status_for_collect_to_skip(self):
        html = _html([_event(eventStatus="https://schema.org/EventCancelled")])

        assert cualpinta.parse_detail(html)["event_status"] == "https://schema.org/EventCancelled"

    def test_missing_event_block_raises(self):
        with pytest.raises(ValueError):
            cualpinta.parse_detail("<html><body>sin datos</body></html>")


class TestCollect:
    def test_collects_every_sitemap_url_with_source_and_detail_url(self, cualpinta_source):
        urls, calls = cualpinta_source

        records = cualpinta.collect()

        assert calls["sitemap"] == 1
        assert calls["details"] == urls
        assert len(records) == 4
        assert [record["detail_url"] for record in records] == urls
        assert all(record["source"] == "cualpinta" for record in records)

    def test_blocked_categories_are_skipped(self, cualpinta_source, monkeypatch):
        urls, _ = cualpinta_source
        blocked_url = urls[0]

        def fetch_detail(url):
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES[slug]))
            record["category"] = "Deportes" if url == blocked_url else "Recital"
            return record

        monkeypatch.setattr(cualpinta, "_fetch_detail", fetch_detail)

        records = cualpinta.collect()

        assert [record["detail_url"] for record in records] == urls[1:]

    def test_cancelled_event_is_skipped(self, cualpinta_source, monkeypatch):
        urls, _ = cualpinta_source
        cancelled_url = urls[0]

        def fetch_detail(url):
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES[slug]))
            record["category"] = "Recital"
            if url == cancelled_url:
                record["event_status"] = "https://schema.org/EventCancelled"
            return record

        monkeypatch.setattr(cualpinta, "_fetch_detail", fetch_detail)

        records = cualpinta.collect()

        assert [record["detail_url"] for record in records] == urls[1:]

    def test_detail_failure_is_logged_and_skipped(self, cualpinta_source, monkeypatch, capsys):
        urls, _ = cualpinta_source
        failing_url = urls[0]

        def fetch_detail(url):
            if url == failing_url:
                raise requests.RequestException("boom")
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            record = cualpinta.parse_detail(_load_html(DETAIL_FIXTURES[slug]))
            record["category"] = "Recital"
            return record

        monkeypatch.setattr(cualpinta, "_fetch_detail", fetch_detail)

        records = cualpinta.collect()

        assert [record["detail_url"] for record in records] == urls[1:]
        assert f"[cualpinta] detail {failing_url} failed" in capsys.readouterr().err

    def test_sitemap_failure_propagates(self, monkeypatch):
        def failing_sitemap():
            raise requests.RequestException("boom")

        monkeypatch.setattr(cualpinta, "_fetch_sitemap", failing_sitemap)
        monkeypatch.setattr(cualpinta, "_fetch_detail", lambda url: None)

        with pytest.raises(requests.RequestException):
            cualpinta.collect()


class TestRequestContract:
    class FakeResponse:
        def __init__(self, text=""):
            self.text = text
            self.status_checked = False

        def raise_for_status(self):
            self.status_checked = True

    def test_sitemap_request_contract(self, monkeypatch):
        seen = {}
        response = self.FakeResponse(text=_load_html("cualpinta_sitemap.xml"))

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(cualpinta.requests, "get", fake_get)

        xml = cualpinta._fetch_sitemap()

        assert xml == response.text
        assert response.status_checked
        assert seen["url"] == SITEMAP_URL
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30

    def test_detail_request_contract(self, monkeypatch):
        seen = {}
        url = EVENT_URL.format(slug="zrock-ae4410")
        response = self.FakeResponse(text=_load_html(DETAIL_FIXTURES["zrock-ae4410"]))

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(cualpinta.requests, "get", fake_get)

        record = cualpinta._fetch_detail(url)

        assert record["name"] == "ZROCK"
        assert "detail_url" not in record
        assert seen["url"] == url
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30


class TestNormalize:
    @staticmethod
    def _events(records):
        return {event.source_event_id: event for event in cualpinta.normalize(records)}

    def test_single_day_event(self):
        event = self._events([_detail_record("zrock-ae4410")])["zrock-ae4410"]

        assert event.source == "cualpinta"
        assert event.title == "ZROCK"
        assert event.venue_name == "Abbey Road"
        assert event.venue_raw == (
            "Abbey Road, Av. Juan B. Justo 620, B7600 Mar del Plata, Provincia de Buenos Aires"
        )
        assert event.date_start == "2026-10-30"
        assert event.date_end == "2026-10-30"
        assert event.occurrences == ["2026-10-30"]
        assert event.recurrence_unknown is False
        assert event.multi_date_incomplete is False
        assert event.time == "21:00"
        assert event.is_free is False
        assert event.price_min == 15000.0
        assert event.price_text is None
        assert event.currency == "ARS"
        assert event.ticket_url == ZROCK_TICKET
        assert event.seller == "Articket"
        assert event.image_url == ZROCK_IMAGE
        assert event.city == "Mar del Plata"
        assert event.raw_url == EVENT_URL.format(slug="zrock-ae4410")

    def test_range_event_never_invents_dates(self):
        event = self._events([_detail_record("hairspray")])["hairspray"]

        assert event.date_start == "2026-12-12"
        assert event.date_end == "2026-12-13"
        assert event.occurrences == []
        assert event.recurrence_unknown is True
        assert event.time == "20:00"
        assert event.seller == "Ticketek"

    def test_missing_end_date_is_a_single_day(self):
        event = self._events([_detail_record(
            "https-www-plateanet-com-obra-34808-obra-el-20jefe-20del-20je"
        )])["https-www-plateanet-com-obra-34808-obra-el-20jefe-20del-20je"]

        assert event.date_start == "2026-10-31"
        assert event.date_end == "2026-10-31"
        assert event.occurrences == ["2026-10-31"]
        assert event.recurrence_unknown is False
        assert event.seller == "Plateanet"

    @pytest.mark.parametrize(
        "end_date",
        ["2026-11-01", "2026-10-31", "2026-11-01T23:00:00-03:00", None, ""],
    )
    def test_equal_or_earlier_end_date_collapses_to_start(self, end_date):
        event = cualpinta.normalize([_record(end_date=end_date)])[0]

        assert event.date_start == "2026-11-01"
        assert event.date_end == "2026-11-01"
        assert event.occurrences == ["2026-11-01"]
        assert event.recurrence_unknown is False

    def test_zero_price_means_free(self):
        event = cualpinta.normalize([_record(price=0)])[0]

        assert event.price_min == 0.0
        assert event.is_free is True
        assert event.currency == "ARS"

    def test_missing_price_leaves_free_status_unknown(self):
        event = cualpinta.normalize([_record(price=None, currency=None)])[0]

        assert event.price_min is None
        assert event.is_free is None
        assert event.currency is None

    def test_price_present_without_currency_defaults_to_ars(self):
        event = cualpinta.normalize([_record(price="7500", currency=None)])[0]

        assert event.price_min == 7500.0
        assert event.currency == "ARS"
        assert event.is_free is False

    def test_venue_raw_without_street_is_just_the_name(self):
        event = cualpinta.normalize([_record(street_address=None)])[0]

        assert event.venue_name == "Club Demo"
        assert event.venue_raw == "Club Demo"

    def test_source_event_id_is_the_detail_url_slug(self):
        event = cualpinta.normalize([_record(detail_url=EVENT_URL.format(slug="demo") + "/")])[0]

        assert event.source_event_id == "demo"

    def test_empty_input_returns_no_events(self):
        assert cualpinta.normalize([]) == []


def test_blocked_categories_cover_non_music_shows():
    for category in ("Cine", "Festival de cine", "Preestreno", "Stand-up", "Danza", "Teatro", "Teatro infantil"):
        assert category in cualpinta.BLOCKED_CATEGORIES
