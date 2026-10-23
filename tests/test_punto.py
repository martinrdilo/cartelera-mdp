"""Tests for the Punto Mar del Plata collector (pagination + JSON-LD detail).

Every test is offline: `_fetch_page` and `_fetch_detail` are replaced with
fixtures so `collect()` never touches the network.
"""

import json
from pathlib import Path

import pytest
import requests

import collectors.punto as punto

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _schema_event(payload):
    return (
        '<html><head><script id="schema-event" type="application/ld+json">'
        + json.dumps(payload)
        + "</script></head></html>"
    )


def _record(**overrides):
    record = {
        "codigo": 999,
        "slug": "demo-999",
        "titulo": "Demo",
        "lugar": None,
        "desde": "2026-11-01",
        "hasta": "2026-11-01",
        "horaInicio": "20:00:00",
        "foto": "2026-demo-999.webp",
        "locacionNombre": "Club TRI",
        "detail": None,
    }
    record.update(overrides)
    return record


@pytest.fixture
def punto_source(monkeypatch):
    """Wire collect() to fixtures: one listing page, two parsable details."""
    payload = _load_json("punto_items.json")
    detail_html = {
        "noche-flamenca-20412": _load_html("punto_detail_noche.html"),
        "vinmusic-mdq-cheers-2026-20331": _load_html("punto_detail_vinmusic.html"),
    }
    calls = {"pages": [], "details": []}

    def fetch_page(page):
        calls["pages"].append(page)
        return payload

    def fetch_detail(slug):
        calls["details"].append(slug)
        html = detail_html.get(slug)
        return punto.parse_detail(html) if html else None

    monkeypatch.setattr(punto, "REQUEST_DELAY", 0)
    monkeypatch.setattr(punto, "_fetch_page", fetch_page)
    monkeypatch.setattr(punto, "_fetch_detail", fetch_detail)
    return payload, calls


class TestCollect:
    def test_collects_every_page(self, monkeypatch):
        payload = _load_json("punto_items.json")
        items = payload["items"]
        pages = {
            1: {"total": 2, "totalPaginas": 2, "items": [items[0]]},
            2: {"total": 2, "totalPaginas": 2, "items": [items[1]]},
        }
        calls = []

        def fetch_page(page):
            calls.append(page)
            return pages[page]

        monkeypatch.setattr(punto, "REQUEST_DELAY", 0)
        monkeypatch.setattr(punto, "_fetch_page", fetch_page)
        monkeypatch.setattr(punto, "_fetch_detail", lambda slug: None)

        records = punto.collect()

        assert calls == [1, 2]
        assert [record["codigo"] for record in records] == [items[0]["codigo"], items[1]["codigo"]]
        assert all("detail" in record for record in records)

    def test_max_pages_caps_pagination(self, monkeypatch):
        payload = _load_json("punto_items.json")
        calls = []

        def fetch_page(page):
            calls.append(page)
            return {"total": 120, "totalPaginas": 10, "items": [payload["items"][0]]}

        monkeypatch.setattr(punto, "REQUEST_DELAY", 0)
        monkeypatch.setattr(punto, "MAX_PAGES", 2)
        monkeypatch.setattr(punto, "_fetch_page", fetch_page)
        monkeypatch.setattr(punto, "_fetch_detail", lambda slug: None)

        records = punto.collect()

        assert calls == [1, 2]
        assert len(records) == 2

    def test_single_page_fixture_is_fully_collected(self, punto_source):
        payload, calls = punto_source

        records = punto.collect()

        assert calls["pages"] == [1]
        assert len(records) == len(payload["items"]) == 4
        assert calls["details"] == [item["slug"] for item in payload["items"]]
        assert all(record["source"] == "punto" for record in records)
        assert all("detail" in record for record in records)

    def test_detail_failure_keeps_event_and_logs(self, punto_source, capsys, monkeypatch):
        payload, _ = punto_source

        def failing_detail(slug):
            raise requests.RequestException("boom")

        monkeypatch.setattr(punto, "_fetch_detail", failing_detail)

        records = punto.collect()
        events = punto.normalize(records)

        assert len(records) == len(payload["items"])
        assert all(record["detail"] is None for record in records)
        assert all(event.ticket_url is None and event.seller is None for event in events)
        assert "[punto] detail" in capsys.readouterr().err


class TestRequestContract:
    class FakeResponse:
        def __init__(self, payload=None, text=""):
            self._payload = payload
            self.text = text

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def test_listing_request_contract(self, monkeypatch):
        seen = {}
        response = self.FakeResponse(payload={"items": [], "totalPaginas": 1})

        def fake_get(url, params=None, headers=None, timeout=None):
            seen.update(url=url, params=params, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(punto.requests, "get", fake_get)

        punto._fetch_page(3)

        assert seen["url"] == "https://puntomardelplata.com/api/actividades"
        assert seen["params"] == {
            "soloVigentes": "true",
            "orden": "desde",
            "pagina": 3,
            "tamano": 12,
            "categoria": "1",
        }
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30

    def test_detail_request_contract(self, monkeypatch):
        seen = {}
        html = _schema_event({"@type": "Event", "offers": {"url": "https://venti.live/e/1"}})

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return self.FakeResponse(text=html)

        monkeypatch.setattr(punto.requests, "get", fake_get)

        detail = punto._fetch_detail("noche-flamenca-20412")

        assert seen["url"] == "https://puntomardelplata.com/actividades/noche-flamenca-20412"
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30
        assert detail["seller"] == "Venti"


class TestNormalize:
    @staticmethod
    def _events(punto_source):
        return {event.source_event_id: event for event in punto.normalize(punto.collect())}

    def test_single_day_event(self, punto_source):
        event = self._events(punto_source)["20412"]

        assert event.source == "punto"
        assert event.source_event_id == "20412"
        assert event.title == "Noche flamenca"
        assert event.venue_name == "Teatro Colón"
        assert event.venue_raw == "Teatro Colón"
        assert event.date_start == "2026-10-22"
        assert event.date_end == "2026-10-22"
        assert event.occurrences == ["2026-10-22"]
        assert event.recurrence_unknown is False
        assert event.time == "21:00"
        assert event.image_url == (
            "https://puntomardelplata.com/recursos/actividades/2026/"
            "2026-noche-flamenca-20412.webp"
        )
        assert event.city == "Mar del Plata"
        assert event.raw_url == "https://puntomardelplata.com/actividades/noche-flamenca-20412"

    def test_multi_day_range_never_invents_dates(self, punto_source):
        event = self._events(punto_source)["20331"]

        assert event.occurrences == []
        assert event.recurrence_unknown is True
        assert event.date_start == "2026-12-05"
        assert event.date_end == "2026-12-06"
        assert event.venue_name == "Sheraton Mar del Plata Hotel"
        assert event.venue_raw == "Sheraton Mar del Plata Hotel, Leandro N. Alem 4221, Mar del Plata"

    def test_detail_offers_supply_ticket_url_and_seller(self, punto_source):
        events = self._events(punto_source)

        noche = events["20412"]
        assert noche.ticket_url == "https://unica-cartelera.com.ar/obra/26977-noche-flamenca"
        assert noche.seller == "Única Cartelera"

        vinmusic = events["20331"]
        assert vinmusic.ticket_url == "https://venti.live/evento/vinmusic-mdq-aniversario-ii"
        assert vinmusic.seller == "Venti"

    def test_articket_offer_is_recognized(self):
        detail = punto.parse_detail(
            _schema_event(
                {
                    "@type": "Event",
                    "offers": {"url": "https://articket.com.ar/noche-flamenca/"},
                }
            )
        )

        event = punto.normalize([_record(detail=detail)])[0]

        assert event.ticket_url == "https://articket.com.ar/noche-flamenca/"
        assert event.seller == "Articket"

    @pytest.mark.parametrize(
        ("url", "seller"),
        [
            ("https://venti.live/evento/1", "Venti"),
            ("https://articket.com.ar/obra/1", "Articket"),
            ("https://cultutickets.com/evento/1", "CultuTickets"),
            ("https://ticketek.com.ar/show/1", "Ticketek"),
            ("https://plateanet.com/evento/1", "Plateanet"),
            ("https://wearebombo.com/evento/1", "Bombo"),
            ("https://tuentrada.com/evento/1", "TuEntrada"),
            ("https://unica-cartelera.com.ar/obra/1", "Única Cartelera"),
        ],
    )
    def test_offer_host_selects_seller(self, url, seller):
        detail = punto.parse_detail(_schema_event({"@type": "Event", "offers": {"url": url}}))

        assert detail["ticket_url"] == url
        assert detail["seller"] == seller

    def test_unknown_offer_host_has_no_seller(self):
        detail = punto.parse_detail(
            _schema_event({"@type": "Event", "offers": {"url": "https://example.test/tickets"}})
        )

        assert detail["ticket_url"] == "https://example.test/tickets"
        assert detail["seller"] is None

    def test_offer_prices_feed_price_fields(self):
        detail = punto.parse_detail(
            _schema_event(
                {
                    "@type": "Event",
                    "offers": [
                        {"url": "https://articket.com.ar/demo/", "price": "15000", "priceCurrency": "ARS"},
                        {"url": "https://articket.com.ar/demo/", "price": "12000", "priceCurrency": "ARS"},
                    ],
                }
            )
        )

        event = punto.normalize([_record(detail=detail)])[0]

        assert event.price_min == 12000.0
        assert event.price_text == "$12000"
        assert event.currency == "ARS"
        assert event.is_free is False

    def test_missing_detail_leaves_ticket_fields_empty(self):
        event = punto.normalize([_record(detail=None)])[0]

        assert event.ticket_url is None
        assert event.seller is None
        assert event.price_min is None
        assert event.price_text is None
        assert event.currency is None

    def test_invalid_start_time_is_dropped(self):
        event = punto.normalize([_record(horaInicio="25:99:00")])[0]

        assert event.time is None
