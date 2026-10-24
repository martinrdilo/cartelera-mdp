"""Tests for the Eleven Flow collector (listing anchors + MusicEvent JSON-LD).

Every test is offline: `_fetch_listing` and `_fetch_detail` are replaced with
fixtures, or the pure parsers are called with fixture/inline HTML.
"""

import json
from pathlib import Path

import pytest
import requests

import collectors.elevenflow as elevenflow

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LISTING = "elevenflow_listing.html"
CIRKUS = "elevenflow_detail_cirkus-cirkor-presenta-knitting-peace-20261024-hxxz.html"
MARCELA = "elevenflow_detail_marcela-morelo-20261031-v0d5.html"
CADILLACS = "elevenflow_detail_los-fabulosos-cadillacs-20261024-tspz.html"
BASE = "https://elevenflow.app"


def _load_html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _script(payload):
    return '<script type="application/ld+json">' + json.dumps(payload) + "</script>"


BREADCRUMB = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [],
}


def _detail(payload, body=""):
    """Minimal detail page: a BreadcrumbList block first, then the event."""
    return f"<html><head>{_script(BREADCRUMB)}{_script(payload)}</head><body>{body}</body></html>"


def _record(**overrides):
    record = {
        "source": "elevenflow",
        "name": "Demo",
        "startDate": "2026-11-01T20:00:00-03:00",
        "endDate": "2026-11-01T00:00:00-03:00",
        "eventStatus": "https://schema.org/EventScheduled",
        "venue_name": "Club Tri",
        "street_address": None,
        "price": None,
        "currency": None,
        "image": None,
        "url": f"{BASE}/events/demo-20261101-aaaa",
        "ticket_url": None,
        "raw_url": f"{BASE}/events/demo-20261101-aaaa",
    }
    record.update(overrides)
    return record


class TestParseListing:
    def test_extracts_every_unique_event_url(self):
        urls = elevenflow.parse_listing(_load_html(LISTING))

        assert len(urls) == 53
        assert len(set(urls)) == 53
        assert urls[0] == f"{BASE}/events/los-fabulosos-cadillacs-20261024-tspz"
        assert urls[-1] == f"{BASE}/events/no-te-va-gustar-20270403-kpxk"
        assert all(url.startswith(f"{BASE}/events/") for url in urls)

    def test_dedupes_relative_and_absolute_anchors(self):
        html = (
            "<html><body>"
            '<a href="/events/demo-one">Demo</a>'
            f'<a href="{BASE}/events/demo-one?utm_source=ig">Demo again</a>'
            f'<a href="{BASE}/events/demo-two">Otro</a>'
            '<a href="/events">Agenda</a>'
            '<a href="/recitales-en-mar-del-plata">Listado</a>'
            '<a href="https://otro.example/events/demo-three">Externo</a>'
            "</body></html>"
        )

        assert elevenflow.parse_listing(html) == [
            f"{BASE}/events/demo-one",
            f"{BASE}/events/demo-two",
        ]

    def test_itemlist_json_ld_is_not_used_for_enumeration(self):
        html = _script(
            {
                "@type": "ItemList",
                "itemListElement": [
                    {"item": {"@type": "MusicEvent", "url": f"{BASE}/events/demo"}}
                ],
            }
        )

        assert elevenflow.parse_listing(html) == []

    def test_empty_listing_has_no_urls(self):
        assert elevenflow.parse_listing("") == []
        assert elevenflow.parse_listing("<html><body>sin eventos</body></html>") == []


class TestParseDetail:
    def test_selects_music_event_among_breadcrumb_blocks(self):
        record = elevenflow.parse_detail(_load_html(CIRKUS))

        assert record["name"] == "CIRKUS CIRKOR PRESENTA - KNITTING PEACE"
        assert record["startDate"] == "2026-10-24T21:00:00-03:00"
        assert record["endDate"] == "2026-10-24T01:00:00-03:00"
        assert record["eventStatus"] == "https://schema.org/EventScheduled"
        assert record["venue_name"] == "Roxy-Radio City"
        assert record["street_address"] is None
        assert record["price"] == 0.0
        assert record["currency"] == "ARS"
        assert record["image"] == (
            "https://www.plateanet.com/img/imagenes/220x220/"
            "CIRKUS-CIRKOR-PRESENTA---KNITTING-PEACE.jpg"
        )
        assert record["url"] == f"{BASE}/events/cirkus-cirkor-presenta-knitting-peace-20261024-hxxz"

    def test_plateanet_anchor_becomes_ticket_url(self):
        record = elevenflow.parse_detail(_load_html(CIRKUS))

        assert record["ticket_url"] == (
            "https://www.plateanet.com/obra/34743?obra=CIRKUS-CIRKOR-PRESENTA---KNITTING-PEACE"
        )

    def test_external_link_filter_skips_elevenflow_social_and_maps(self):
        html = _detail(
            {
                "@type": "MusicEvent",
                "name": "Demo",
                "startDate": "2026-11-01T20:00:00-03:00",
            },
            body=(
                f'<a href="{BASE}/events/otro">Eleven Flow</a>'
                '<a href="https://www.instagram.com/p/abc">Instagram</a>'
                '<a href="https://wa.me/5492230000000">WhatsApp</a>'
                '<a href="https://www.google.com/maps/place/Club+Tri">Mapa</a>'
                '<a href="https://www.facebook.com/evento">Facebook</a>'
                '<a href="https://www.plateanet.com/obra/35757?obra=DEMO">Entradas</a>'
            ),
        )

        assert elevenflow.parse_detail(html)["ticket_url"] == (
            "https://www.plateanet.com/obra/35757?obra=DEMO"
        )

    def test_without_external_anchor_ticket_url_is_none(self):
        html = _detail(
            {
                "@type": "MusicEvent",
                "name": "Demo",
                "startDate": "2026-11-01T20:00:00-03:00",
            },
            body=f'<a href="{BASE}/events/otro">Otra fecha</a>',
        )

        assert elevenflow.parse_detail(html)["ticket_url"] is None

    def test_street_address_and_missing_offers(self):
        html = _detail(
            {
                "@type": "MusicEvent",
                "name": "Demo",
                "startDate": "2026-11-01T20:00:00-03:00",
                "location": {
                    "@type": "MusicVenue",
                    "name": "Club Tri",
                    "address": {"@type": "PostalAddress", "streetAddress": "Moreno 2345"},
                },
                "image": "https://example.test/demo.jpg",
            }
        )

        record = elevenflow.parse_detail(html)

        assert record["venue_name"] == "Club Tri"
        assert record["street_address"] == "Moreno 2345"
        assert record["price"] is None
        assert record["currency"] is None
        assert record["image"] == "https://example.test/demo.jpg"
        assert record["ticket_url"] is None

    def test_offers_list_uses_lowest_price(self):
        html = _detail(
            {
                "@type": "MusicEvent",
                "name": "Demo",
                "startDate": "2026-11-01T20:00:00-03:00",
                "offers": [
                    {"price": "15000", "priceCurrency": "ARS"},
                    {"price": 12000, "priceCurrency": "ARS"},
                ],
            }
        )

        record = elevenflow.parse_detail(html)

        assert record["price"] == 12000.0
        assert record["currency"] == "ARS"

    def test_missing_music_event_raises(self):
        with pytest.raises(ValueError):
            elevenflow.parse_detail("<html><body>sin datos</body></html>")


def _listing(*urls):
    anchors = "".join(f'<a href="{url}">evento</a>' for url in urls)
    return f"<html><body>{anchors}</body></html>"


class TestCollect:
    def test_enriches_every_listing_url_with_a_detail_record(self, monkeypatch):
        urls = elevenflow.parse_listing(_load_html(LISTING))
        calls = []

        def fetch_detail(url):
            calls.append(url)
            return elevenflow.parse_detail(_load_html(CIRKUS))

        monkeypatch.setattr(elevenflow, "REQUEST_DELAY", 0)
        monkeypatch.setattr(elevenflow, "_fetch_listing", lambda: _load_html(LISTING))
        monkeypatch.setattr(elevenflow, "_fetch_detail", fetch_detail)

        records = elevenflow.collect()

        assert calls == urls
        assert len(records) == 53
        assert all(record["source"] == "elevenflow" for record in records)
        assert [record["raw_url"] for record in records] == urls

    def test_listing_failure_propagates(self, monkeypatch):
        def failing_listing():
            raise requests.RequestException("boom")

        monkeypatch.setattr(elevenflow, "_fetch_listing", failing_listing)

        with pytest.raises(requests.RequestException):
            elevenflow.collect()

    def test_detail_failure_is_logged_and_skipped(self, monkeypatch, capsys):
        urls = [f"{BASE}/events/demo-one", f"{BASE}/events/demo-two"]
        monkeypatch.setattr(elevenflow, "REQUEST_DELAY", 0)
        monkeypatch.setattr(elevenflow, "_fetch_listing", lambda: _listing(*urls))

        def fetch_detail(url):
            if url.endswith("demo-two"):
                raise requests.RequestException("boom")
            return elevenflow.parse_detail(_load_html(CIRKUS))

        monkeypatch.setattr(elevenflow, "_fetch_detail", fetch_detail)

        records = elevenflow.collect()

        assert [record["raw_url"] for record in records] == [urls[0]]
        stderr = capsys.readouterr().err
        assert "[elevenflow] detail" in stderr
        assert urls[1] in stderr

    def test_cancelled_event_is_skipped(self, monkeypatch):
        urls = [f"{BASE}/events/cancelled", f"{BASE}/events/scheduled"]
        monkeypatch.setattr(elevenflow, "REQUEST_DELAY", 0)
        monkeypatch.setattr(elevenflow, "_fetch_listing", lambda: _listing(*urls))

        def fetch_detail(url):
            status = (
                "https://schema.org/EventCancelled"
                if url.endswith("cancelled")
                else "https://schema.org/EventScheduled"
            )
            return {"name": "Demo", "startDate": "2026-11-01T20:00:00-03:00", "eventStatus": status}

        monkeypatch.setattr(elevenflow, "_fetch_detail", fetch_detail)

        records = elevenflow.collect()

        assert [record["raw_url"] for record in records] == [urls[1]]


class TestRequestContract:
    class FakeResponse:
        def __init__(self, text=""):
            self.text = text
            self.status_checked = False

        def raise_for_status(self):
            self.status_checked = True

    def test_listing_request_contract(self, monkeypatch):
        seen = {}
        response = self.FakeResponse(text=_load_html(LISTING))

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(elevenflow.requests, "get", fake_get)

        html = elevenflow._fetch_listing()

        assert html == response.text
        assert response.status_checked
        assert seen["url"] == f"{BASE}/recitales-en-mar-del-plata"
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30

    def test_detail_request_contract(self, monkeypatch):
        seen = {}
        url = f"{BASE}/events/cirkus-cirkor-presenta-knitting-peace-20261024-hxxz"
        response = self.FakeResponse(text=_load_html(CIRKUS))

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(elevenflow.requests, "get", fake_get)

        record = elevenflow._fetch_detail(url)

        assert seen["url"] == url
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30
        assert record["name"] == "CIRKUS CIRKOR PRESENTA - KNITTING PEACE"


class TestNormalize:
    @staticmethod
    def _event(**overrides):
        return elevenflow.normalize([_record(**overrides)])[0]

    def test_empty_input(self):
        assert elevenflow.normalize([]) == []

    def test_single_day_event_from_real_detail(self):
        record = elevenflow.parse_detail(_load_html(CADILLACS))
        record.update(source="elevenflow", raw_url=record["url"])

        event = elevenflow.normalize([record])[0]

        assert event.source == "elevenflow"
        assert event.source_event_id == "los-fabulosos-cadillacs-20261024-tspz"
        assert event.title == "Los Fabulosos Cadillacs"
        assert event.venue_name == "Arena Mardel Plata"
        assert event.venue_raw == "Arena Mardel Plata"
        assert event.date_start == "2026-10-24"
        assert event.date_end == "2026-10-24"
        assert event.occurrences == ["2026-10-24"]
        assert event.recurrence_unknown is False
        assert event.time == "20:00"
        assert event.price_min is None
        assert event.price_text is None
        assert event.currency is None
        assert event.is_free is None
        assert event.seller is None
        assert event.image_url == (
            "https://nxfwjuobcaycszirliqr.supabase.co/storage/v1/object/public/"
            "imported-events/agendade/b8713091-e9fb-4435-80e8-ddd9ddce2991.jpg"
        )
        assert event.city == "Mar del Plata"
        assert event.raw_url == record["url"]

    def test_earlier_end_date_collapses_to_one_day(self):
        event = self._event(
            startDate="2026-11-01T20:00:00-03:00",
            endDate="2026-11-01T00:00:00-03:00",
        )

        assert event.date_end == "2026-11-01"
        assert event.occurrences == ["2026-11-01"]
        assert event.recurrence_unknown is False

    def test_real_range_keeps_recurrence_unknown(self):
        event = self._event(
            startDate="2026-11-06T16:00:00-03:00",
            endDate="2026-11-08T20:00:00-03:00",
        )

        assert event.date_start == "2026-11-06"
        assert event.date_end == "2026-11-08"
        assert event.occurrences == []
        assert event.recurrence_unknown is True

    def test_plateanet_link_sets_seller(self):
        record = elevenflow.parse_detail(_load_html(MARCELA))
        record.update(source="elevenflow", raw_url=record["url"])

        event = elevenflow.normalize([record])[0]

        assert event.ticket_url == (
            "https://www.plateanet.com/obra/34546?obra=MARCELA-MORELO-PRESENTA-LA-MORELO&paso=inicio"
        )
        assert event.seller == "Plateanet"

    @pytest.mark.parametrize(
        ("price", "is_free", "price_min"),
        [
            (0.0, None, None),
            (15000.0, False, 15000.0),
            (None, None, None),
        ],
    )
    def test_price_variants(self, price, is_free, price_min):
        event = self._event(price=price, currency="ARS" if price is not None else None)

        assert event.price_min == price_min
        assert event.price_text is None
        assert event.is_free is is_free
        assert event.currency == ("ARS" if price_min is not None else None)

    def test_venue_raw_includes_street_address(self):
        event = self._event(venue_name="Club Tri", street_address="Moreno 2345")

        assert event.venue_name == "Club Tri"
        assert event.venue_raw == "Club Tri, Moreno 2345"

    def test_date_only_start_has_no_time(self):
        event = self._event(startDate="2026-11-01", endDate="2026-11-01")

        assert event.date_start == "2026-11-01"
        assert event.time is None
        assert event.occurrences == ["2026-11-01"]

    def test_missing_start_date(self):
        event = self._event(startDate=None, endDate=None)

        assert event.date_start is None
        assert event.date_end is None
        assert event.occurrences == []
        assert event.recurrence_unknown is False
        assert event.time is None

    def test_cancelled_record_is_not_normalized(self):
        events = elevenflow.normalize(
            [
                _record(eventStatus="https://schema.org/EventCancelled"),
                _record(eventStatus="https://schema.org/EventScheduled"),
            ]
        )

        assert len(events) == 1
