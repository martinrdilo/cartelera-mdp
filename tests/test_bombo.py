"""Tests for the Bombo collector (wearebombo.com).

The search API decides which events belong to Mar del Plata; the detail page
adds venue, organizer, image and price through schema.org MusicEvent JSON-LD.
Every test uses the recorded fixtures and monkeypatches the two fetch helpers,
so the suite never touches the network.
"""

import copy
import json
from pathlib import Path

import pytest

from collectors import bombo

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH_FIXTURE = FIXTURES / "bombo_search.json"
MUTE_FIXTURE = FIXTURES / "bombo_detail_mute.html"
COUNTY_FIXTURE = FIXTURES / "bombo_detail_county.html"


def _search_payload():
    return json.loads(SEARCH_FIXTURE.read_text(encoding="utf-8"))


def _detail(path):
    return bombo._parse_detail_html(path.read_text(encoding="utf-8"))


def _use_search(monkeypatch, payload=None):
    data = _search_payload() if payload is None else payload
    monkeypatch.setattr(bombo, "_fetch_search", lambda: copy.deepcopy(data))


@pytest.fixture(autouse=True)
def no_detail_delay(monkeypatch):
    """Keep the 1 req/s politeness delay in production but not in tests."""
    monkeypatch.setattr(bombo, "REQUEST_DELAY", 0)


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestCollect:
    def test_keeps_only_mar_del_plata_and_preserves_search_fields(self, monkeypatch):
        payload = _search_payload()
        payload.append(
            {
                "id": "cordoba-1",
                "name": "Show en Córdoba",
                "href": "/evento/show-cordoba",
                "imageUrl": "https://files.wearebombo.com/events/cordoba",
                "placeName": "Córdoba",
                "dateStamp": "SÁB 07 NOV",
                "dateTime": "2026-11-07T21:00:00.000-03:00",
            }
        )
        payload.append(
            {
                "id": "mdp-suffix",
                "name": "Show en Mar del Plata",
                "href": "/evento/show-mdp-suffix",
                "imageUrl": None,
                "placeName": "Mar del Plata, Buenos Aires",
                "dateStamp": "DOM 08 NOV",
                "dateTime": "2026-11-08T20:00:00.000-03:00",
            }
        )
        _use_search(monkeypatch, payload)

        fetched = []

        def fetch_detail(href):
            fetched.append(href)
            return {"@type": "MusicEvent", "name": "detalle"}

        monkeypatch.setattr(bombo, "_fetch_detail", fetch_detail)

        records = bombo.collect()

        assert [record["id"] for record in records] == [
            "6abbcdce9fbcc9d661c8df13",
            "6abaa5189fbcc9d661691016",
            "6ace52810d9e9cad1c632ac0",
            "mdp-suffix",
        ]
        assert "cordoba-1" not in [record["id"] for record in records]
        # Details are fetched only for records that survived the filter.
        assert fetched == [record["href"] for record in records]
        first = records[0]
        for field in ("id", "name", "href", "imageUrl", "placeName", "dateStamp", "dateTime"):
            assert first[field] == payload[0][field]
        assert first["source"] == "bombo"
        assert first["detail"] == {"@type": "MusicEvent", "name": "detalle"}

    def test_ticket_bundle_is_not_a_calendar_event(self, monkeypatch):
        payload = _search_payload()
        payload.append(
            {
                "id": "poker-pass",
                "name": "MUTE POKER PASS: 4 EVENTOS, LOS QUE VOS ELIJAS.",
                "href": "/evento/mute-poker-pass",
                "imageUrl": None,
                "placeName": "Mar del Plata",
                "dateStamp": "SÁB 21 NOV",
                "dateTime": "2026-11-21T23:00:00.000-03:00",
            }
        )
        _use_search(monkeypatch, payload)
        monkeypatch.setattr(bombo, "_fetch_detail", lambda href: {"@type": "MusicEvent"})

        records = bombo.collect()

        assert "poker-pass" not in [record["id"] for record in records]

    def test_search_uses_the_api_query_and_exact_user_agent(self, monkeypatch):
        calls = {}

        def fake_get(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            return FakeResponse(payload=[])

        monkeypatch.setattr(bombo.requests, "get", fake_get)

        assert bombo._fetch_search() == []
        assert calls["url"] == "https://wearebombo.com/api/eventos/buscar"
        assert calls["params"] == {"q": "mar del plata"}
        assert calls["headers"] == {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"}
        assert calls["timeout"] == 30

    def test_detail_requests_are_spaced_one_second_apart(self, monkeypatch):
        _use_search(monkeypatch)
        monkeypatch.setattr(bombo, "_fetch_detail", lambda href: {"@type": "MusicEvent"})
        monkeypatch.setattr(bombo, "REQUEST_DELAY", 1.0)
        waits = []
        monkeypatch.setattr(bombo.time, "sleep", waits.append)

        records = bombo.collect()

        assert len(records) == 3
        # First detail is immediate; each following one waits for the previous.
        assert waits == [1.0, 1.0]


class TestDetailParsing:
    def test_fetch_detail_requests_the_detail_page_with_user_agent(self, monkeypatch):
        calls = {}
        html = MUTE_FIXTURE.read_text(encoding="utf-8")

        def fake_get(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            return FakeResponse(text=html)

        monkeypatch.setattr(bombo.requests, "get", fake_get)

        detail = bombo._fetch_detail("/evento/solomun-mute")

        assert calls["url"] == "https://wearebombo.com/evento/solomun-mute"
        assert calls["headers"] == {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"}
        assert detail["@type"] == "MusicEvent"
        assert detail["organizer"]["name"] == "MUTE"

    def test_parser_skips_non_event_json_ld_and_keeps_the_first_event(self):
        mute_script = MUTE_FIXTURE.read_text(encoding="utf-8")
        html = (
            '<html><head><script type="application/ld+json">'
            '{"@type": "Organization", "name": "Bombo"}'
            "</script>"
            + mute_script
            + "</head></html>"
        )

        detail = bombo._parse_detail_html(html)

        assert detail["@type"] == "MusicEvent"
        assert detail["name"] == "SOLOMUN - MUTE"

    def test_parser_handles_an_event_inside_a_graph(self):
        html = (
            '<script type="application/ld+json">'
            '{"@graph": [{"@type": "BreadcrumbList"}, '
            '{"@type": "Event", "name": "Graph Event"}]}'
            "</script>"
        )

        assert bombo._parse_detail_html(html)["name"] == "Graph Event"

    def test_parser_returns_none_without_event_json_ld(self):
        assert bombo._parse_detail_html("<html><body>sin datos</body></html>") is None
        assert bombo._parse_detail_html("") is None


class TestNormalize:
    def test_mute_venue_and_cheapest_instock_admission_price(self):
        record = {
            "id": "solomun-1",
            "name": "SOLOMUN - MUTE",
            "href": "/evento/solomun-mute-solomun-1",
            "imageUrl": "https://files.wearebombo.com/events/search-solomun.webp",
            "placeName": "Mar del Plata",
            "dateStamp": "SÁB 02 ENE",
            "dateTime": "2027-01-02T23:00:00.000-03:00",
            "source": "bombo",
            "detail": _detail(MUTE_FIXTURE),
        }

        event = bombo.normalize([record])[0]

        assert event.source == "bombo"
        assert event.source_event_id == "solomun-1"
        assert event.title == "SOLOMUN - MUTE"
        assert event.venue_name == "Mute Club de Mar"
        assert event.venue_raw.startswith("Ruta 11 Alfar")
        assert event.date_start == "2027-01-02"
        assert event.date_end == "2027-01-02"
        assert event.occurrences == ["2027-01-02"]
        assert event.time == "23:00"
        assert event.price_min == 135000
        assert event.price_text == "Desde $135000"
        assert event.currency == "ARS"
        assert event.is_free is False
        assert event.ticket_url == "https://wearebombo.com/evento/solomun-mute-solomun-1"
        assert event.seller == "Bombo"
        assert event.image_url == (
            "https://files.wearebombo.com/events/blob-a5c57f7375fd-3df0-4221-b269-20e365b50245"
        )
        assert event.city == "Mar del Plata"
        assert event.raw_url == event.ticket_url

    def test_county_venue_from_organizer_and_minimum_instock_price(self):
        record = copy.deepcopy(_search_payload()[2])
        record["source"] = "bombo"
        record["detail"] = _detail(COUNTY_FIXTURE)

        event = bombo.normalize([record])[0]

        assert event.venue_name == "The County Music"
        assert event.venue_raw == (
            "Buenos Aires 7600, B7602CLN Mar del Plata, Provincia de Buenos Aires, Argentina"
        )
        assert event.price_min == 29500
        assert event.price_text == "Desde $29500"
        assert event.currency == "ARS"
        assert event.date_start == "2026-11-14"
        assert event.occurrences == ["2026-11-14"]
        assert event.time == "21:59"
        assert event.ticket_url == "https://wearebombo.com" + record["href"]

    def test_county_venue_from_title_when_organizer_does_not_match(self):
        detail = {
            "@type": "MusicEvent",
            "name": "THE COUNTY PRESENTA: NOCHE X",
            "startDate": "2026-12-12T22:00:00.000-03:00",
            "location": {"address": {"streetAddress": "Buenos Aires 7600"}},
            "organizer": {"@type": "Organization", "name": "Jones"},
        }

        event = bombo.normalize([_record(detail=detail)])[0]

        assert event.venue_name == "The County Music"

    def test_mute_venue_from_address_when_organizer_does_not_match(self):
        detail = {
            "@type": "MusicEvent",
            "name": "Fiesta Electronica",
            "startDate": "2026-12-19T23:00:00.000-03:00",
            "location": {
                "address": {"streetAddress": "Ruta 11 Alfar km 8, Mar del Plata"},
            },
            "organizer": {"@type": "Organization", "name": "Otra Productora"},
        }

        event = bombo.normalize([_record(detail=detail)])[0]

        assert event.venue_name == "Mute Club de Mar"

    def test_detail_failure_keeps_every_event_with_search_venue_and_no_price(
        self, monkeypatch, capsys
    ):
        payload = _search_payload()
        _use_search(monkeypatch, payload)

        def fetch_detail(href):
            if href == payload[0]["href"]:
                raise RuntimeError("boom")
            return None

        monkeypatch.setattr(bombo, "_fetch_detail", fetch_detail)

        events = bombo.normalize(bombo.collect())

        assert len(events) == 3
        first = events[0]
        assert first.title == payload[0]["name"]
        assert first.venue_name == "Mar del Plata"
        assert first.venue_raw is None
        assert first.date_start == "2026-10-30"
        assert first.time == "23:59"
        assert first.occurrences == ["2026-10-30"]
        assert first.ticket_url == "https://wearebombo.com" + payload[0]["href"]
        assert first.seller == "Bombo"
        assert first.image_url == payload[0]["imageUrl"]
        assert first.price_min is None
        assert first.price_text is None
        assert first.currency is None
        assert first.is_free is None
        for event in events:
            assert event.source == "bombo"
            assert event.city == "Mar del Plata"
            assert event.raw_url == event.ticket_url
        errors = capsys.readouterr().err.strip().splitlines()
        assert len(errors) == 3
        assert "boom" in errors[0]
        assert payload[0]["href"] in errors[0]

    def test_search_only_record_uses_search_date_time_image_and_url(self):
        record = _search_payload()[0]

        event = bombo.normalize([record])[0]

        assert event.title == record["name"]
        assert event.venue_name == "Mar del Plata"
        assert event.date_start == "2026-10-30"
        assert event.date_end == "2026-10-30"
        assert event.occurrences == ["2026-10-30"]
        assert event.time == "23:59"
        assert event.image_url == record["imageUrl"]
        assert event.ticket_url == "https://wearebombo.com" + record["href"]
        assert event.seller == "Bombo"
        assert event.price_min is None
        assert event.is_free is None

    def test_price_falls_back_to_all_offers_when_none_is_in_stock(self):
        detail = {
            "@type": "MusicEvent",
            "name": "Sold Out",
            "startDate": "2026-12-05T22:00:00.000-03:00",
            "location": {"address": {"streetAddress": "San Martín 1000"}},
            "organizer": {"name": "Productora"},
            "offers": [
                {"name": "Early", "price": 120000, "availability": "https://schema.org/SoldOut"},
                {"name": "General", "price": 90000, "availability": "https://schema.org/SoldOut"},
            ],
        }

        event = bombo.normalize([_record(detail=detail)])[0]

        assert event.price_min == 90000
        assert event.price_text == "Desde $90000"
        assert event.currency == "ARS"

    def test_image_string_and_missing_organizer(self):
        detail = {
            "@type": "Event",
            "name": "Noche Synth",
            "startDate": "2026-12-01T20:15:00.000-03:00",
            "image": "https://files.wearebombo.com/events/synth.webp",
            "location": {"address": {"streetAddress": "San Martín 1000, Mar del Plata"}},
            "offers": [
                {
                    "name": "General",
                    "price": "0",
                    "priceCurrency": "ARS",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }

        event = bombo.normalize([_record(detail=detail)])[0]

        assert event.venue_name == "Mar del Plata"
        assert event.venue_raw == "San Martín 1000, Mar del Plata"
        assert event.image_url == "https://files.wearebombo.com/events/synth.webp"
        assert event.time == "20:15"
        assert event.price_min == 0
        assert event.price_text == "Desde $0"
        assert event.is_free is True


def _record(detail):
    return {
        "id": "synthetic-1",
        "name": "Evento de prueba",
        "href": "/evento/evento-de-prueba",
        "imageUrl": "https://files.wearebombo.com/events/search.webp",
        "placeName": "Mar del Plata",
        "dateStamp": "SÁB 01 DIC",
        "dateTime": "2026-12-01T20:00:00.000-03:00",
        "source": "bombo",
        "detail": detail,
    }
