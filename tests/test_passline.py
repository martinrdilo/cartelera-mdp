"""Tests for the Passline collector (curated venue slugs + Spanish dates).

Passline's `/eventos` listing sits behind a Queue-it waiting room, so the
collector discovers events from a curated list of venue pages. Every test is
offline: `_fetch` reads the real pages captured in `tests/fixtures/`.
"""

import json
from pathlib import Path

import pytest
import requests

import collectors.passline as passline

FIXTURES = Path(__file__).resolve().parent / "fixtures"

ROOMIE_EVENT = (
    "https://www.passline.com/eventos/"
    "3010-blackween-beta-samuturkush-b2b-joseph-chap-joaxcs-artesano"
)
HALLOWEEN_EVENT = (
    "https://www.passline.com/eventos/"
    "3110-big-halloween-mattcity-matt32-vice-city-branco-simon-guille-reboredo-manu-bignami-cmg"
)
JONES_EVENT = "https://www.passline.com/eventos/fiesta-de-fin-de-ano-multiempresa-en-jones"

VENUE_FIXTURES = {
    "roomie-club": "passline_venue_roomie.html",
    "mr-jones": "passline_venue_mr-jones.html",
    "la-caseta": "passline_venue_la-caseta.html",
}
EVENT_FIXTURES = {
    ROOMIE_EVENT: "passline_event_3010-blackween-beta-samuturkush-b2b-joseph-chap-joaxcs-artesano.html",
    HALLOWEEN_EVENT: (
        "passline_event_3110-big-halloween-mattcity-matt32-vice-city-branco-simon-"
        "guille-reboredo-manu-bignami-cmg.html"
    ),
    JONES_EVENT: "passline_event_fiesta-de-fin-de-ano-multiempresa-en-jones.html",
}

JONES_ADDRESS = "Mar del Plata Buenos Aires AR, Buenos Aires 7600, B7602 CLN"


def _load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _venue_html(*hrefs):
    anchors = "".join(f'<a href="{href}">event</a>' for href in hrefs)
    return f"<html><body><div class='container'>{anchors}</div></body></html>"


def _record(**overrides):
    record = {
        "source": "passline",
        "slug": "demo-show",
        "title": "Demo show",
        "date_text": "Viernes 30 de Octubre 2026 - 23:30 hrs.",
        "venue_name": "ROOMIE CLUB",
        "venue_address": (
            "Av. Colón y el Mar, Mar del Plata, Provincia de Buenos Aires, Argentina"
        ),
        "price_min": 20000.0,
        "price_text": "$20.000.-",
        "currency": "ARS",
        "ticket_url": "https://www.passline.com/eventos/demo-show",
        "image_url": "https://www.passline.com/imagenes/eventos/demo-rec.jpg",
        "sold_out": False,
        "raw_url": "https://www.passline.com/eventos/demo-show",
    }
    record.update(overrides)
    return record


@pytest.fixture
def passline_source(monkeypatch):
    """Wire collect() to the fixtures: three venues, one of them empty."""
    calls = []

    def fetch(url):
        calls.append(url)
        if "/venue/" in url:
            slug = url.rsplit("/", 1)[-1]
            return _load(VENUE_FIXTURES[slug])
        return _load(EVENT_FIXTURES[url])

    monkeypatch.setattr(passline, "REQUEST_DELAY", 0)
    monkeypatch.setattr(
        passline, "VENUE_SLUGS", ("roomie-club", "mr-jones", "la-caseta")
    )
    monkeypatch.setattr(passline, "_fetch", fetch)
    return calls


class TestParseVenuePage:
    def test_extracts_each_event_link_once(self):
        links = passline.parse_venue_page(_load("passline_venue_roomie.html"))

        assert links == [ROOMIE_EVENT, HALLOWEEN_EVENT]

    def test_relative_event_link_becomes_absolute(self):
        html = _venue_html("/eventos/demo-show")

        assert passline.parse_venue_page(html) == [
            "https://www.passline.com/eventos/demo-show"
        ]

    def test_ignores_links_that_are_not_event_pages(self):
        html = _venue_html(
            "https://imagenes.passline.com/eventos/demo-rec.jpg",
            "https://www.passline.com/eventos-presencial.php",
            "https://www.passline.com/venue/zwan",
            "https://www.passline.com/eventos/",
            "javascript:void(0);",
        )

        assert passline.parse_venue_page(html) == []

    def test_empty_venue_page_has_no_links(self):
        assert passline.parse_venue_page(_load("passline_venue_la-caseta.html")) == []


class TestParseEventPage:
    def test_priced_event_fields(self):
        record = passline.parse_event_page(_load(EVENT_FIXTURES[ROOMIE_EVENT]))

        assert record["source"] == "passline"
        assert record["slug"] == "3010-blackween-beta-samuturkush-b2b-joseph-chap-joaxcs-artesano"
        assert record["title"] == (
            "30.10 BLACKWEEN - BETA & SAMU-TURKUSH B2B JOSEPH CHAP -JOAXCS - ARTESANO (+18)"
        )
        assert record["date_text"] == "Viernes 30 de Octubre 2026 - 23:30 hrs."
        assert record["venue_name"] == "ROOMIE CLUB"
        assert record["venue_address"] == (
            "Av. Colón y el Mar, Mar del Plata, Provincia de Buenos Aires, Argentina"
        )
        assert record["price_min"] == 20000.0
        assert record["price_text"] == "$20.000.-"
        assert record["currency"] == "ARS"
        assert record["ticket_url"] == ROOMIE_EVENT
        assert record["raw_url"] == ROOMIE_EVENT
        assert record["image_url"] == (
            "https://www.passline.com/imagenes/eventos/"
            "3010-blackween-beta-samuturkush-b2b-joseph-chap-joaxcs-artesano-571068-rec.jpg"
        )
        assert record["sold_out"] is False

    def test_sold_out_event_is_still_a_valid_event(self):
        record = passline.parse_event_page(_load(EVENT_FIXTURES[HALLOWEEN_EVENT]))

        assert record["sold_out"] is True
        assert record["title"].startswith("31.10 BIG HALLOWEEN")
        assert record["date_text"] == "Sábado 31 de Octubre 2026 - 23:30 hrs."
        assert record["price_min"] == 7000.0

    def test_event_at_a_different_venue(self):
        record = passline.parse_event_page(_load(EVENT_FIXTURES[JONES_EVENT]))

        assert record["title"] == "FIESTA DE FIN DE AÑO MULTI-EMPRESA EN JONES (+18)"
        assert record["date_text"] == "Viernes 18 de Diciembre 2026 - 21:00 hrs."
        assert record["venue_name"] == "Jones"
        assert record["venue_address"] == JONES_ADDRESS
        assert record["price_min"] == 65000.0
        assert record["sold_out"] is False

    def test_canonical_link_supplies_the_ticket_url(self):
        record = passline.parse_event_page(_load(EVENT_FIXTURES[ROOMIE_EVENT]))

        assert record["ticket_url"] == ROOMIE_EVENT

    def test_page_without_an_event_heading_raises(self):
        with pytest.raises(ValueError):
            passline.parse_event_page("<html><body><p>not an event</p></body></html>")


class TestCollect:
    def test_collects_every_venue_and_skips_duplicate_links(self, passline_source):
        records = passline.collect()

        assert passline_source == [
            "https://www.passline.com/venue/roomie-club",
            ROOMIE_EVENT,
            HALLOWEEN_EVENT,
            "https://www.passline.com/venue/mr-jones",
            JONES_EVENT,
            "https://www.passline.com/venue/la-caseta",
        ]
        assert [record["raw_url"] for record in records] == [
            ROOMIE_EVENT,
            HALLOWEEN_EVENT,
            JONES_EVENT,
        ]
        assert all(record["source"] == "passline" for record in records)

    def test_same_event_on_two_venue_pages_is_fetched_once(self, monkeypatch):
        calls = []

        def fetch(url):
            calls.append(url)
            if url.endswith("/roomie-club") or url.endswith("/zwan"):
                return _load("passline_venue_roomie.html")
            return _load(EVENT_FIXTURES[url])

        monkeypatch.setattr(passline, "REQUEST_DELAY", 0)
        monkeypatch.setattr(passline, "VENUE_SLUGS", ("roomie-club", "zwan"))
        monkeypatch.setattr(passline, "_fetch", fetch)

        records = passline.collect()

        assert calls.count(ROOMIE_EVENT) == 1
        assert calls.count(HALLOWEEN_EVENT) == 1
        assert len(records) == 2

    def test_failing_venue_is_logged_and_skipped(self, monkeypatch, capsys):
        def fetch(url):
            if url.endswith("/roomie-club"):
                raise requests.RequestException("boom")
            if "/venue/" in url:
                slug = url.rsplit("/", 1)[-1]
                return _load(VENUE_FIXTURES[slug])
            return _load(EVENT_FIXTURES[url])

        monkeypatch.setattr(passline, "REQUEST_DELAY", 0)
        monkeypatch.setattr(passline, "VENUE_SLUGS", ("roomie-club", "mr-jones"))
        monkeypatch.setattr(passline, "_fetch", fetch)

        records = passline.collect()

        assert [record["raw_url"] for record in records] == [JONES_EVENT]
        assert "[passline] venue roomie-club" in capsys.readouterr().err

    def test_failing_detail_is_logged_and_skipped(self, monkeypatch, capsys):
        def fetch(url):
            if "/venue/" in url:
                slug = url.rsplit("/", 1)[-1]
                return _load(VENUE_FIXTURES[slug])
            if url == HALLOWEEN_EVENT:
                raise requests.RequestException("boom")
            return _load(EVENT_FIXTURES[url])

        monkeypatch.setattr(passline, "REQUEST_DELAY", 0)
        monkeypatch.setattr(passline, "VENUE_SLUGS", ("roomie-club", "mr-jones"))
        monkeypatch.setattr(passline, "_fetch", fetch)

        records = passline.collect()

        assert [record["raw_url"] for record in records] == [ROOMIE_EVENT, JONES_EVENT]
        assert "[passline] detail" in capsys.readouterr().err

    def test_unparsable_detail_is_logged_and_skipped(self, monkeypatch, capsys):
        def fetch(url):
            if "/venue/" in url:
                slug = url.rsplit("/", 1)[-1]
                return _load(VENUE_FIXTURES[slug])
            if url == HALLOWEEN_EVENT:
                return "<html><body><p>not an event</p></body></html>"
            return _load(EVENT_FIXTURES[url])

        monkeypatch.setattr(passline, "REQUEST_DELAY", 0)
        monkeypatch.setattr(passline, "VENUE_SLUGS", ("roomie-club", "mr-jones"))
        monkeypatch.setattr(passline, "_fetch", fetch)

        records = passline.collect()

        assert [record["raw_url"] for record in records] == [ROOMIE_EVENT, JONES_EVENT]
        assert "[passline] detail" in capsys.readouterr().err

    def test_every_venue_failing_raises(self, monkeypatch):
        def fetch(url):
            raise requests.RequestException("boom")

        monkeypatch.setattr(passline, "REQUEST_DELAY", 0)
        monkeypatch.setattr(passline, "VENUE_SLUGS", ("roomie-club", "mr-jones"))
        monkeypatch.setattr(passline, "_fetch", fetch)

        with pytest.raises(requests.RequestException):
            passline.collect()

    def test_records_are_json_serializable(self, passline_source):
        records = passline.collect()

        assert len(json.loads(json.dumps(records))) == 3


class TestRequestContract:
    class FakeResponse:
        def __init__(self, text=""):
            self.text = text

        def raise_for_status(self):
            pass

    def test_fetch_request_contract(self, monkeypatch):
        seen = {}

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return self.FakeResponse(text="<html></html>")

        monkeypatch.setattr(passline.requests, "get", fake_get)

        html = passline._fetch("https://www.passline.com/venue/roomie-club")

        assert html == "<html></html>"
        assert seen["url"] == "https://www.passline.com/venue/roomie-club"
        assert seen["headers"] == {
            "User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"
        }
        assert seen["timeout"] == 30

    def test_fetch_raises_on_http_error(self, monkeypatch):
        class FailingResponse:
            def raise_for_status(self):
                raise requests.HTTPError("404")

        monkeypatch.setattr(passline.requests, "get", lambda *args, **kwargs: FailingResponse())

        with pytest.raises(requests.HTTPError):
            passline._fetch("https://www.passline.com/venue/missing")


class TestNormalize:
    def test_empty_input(self):
        assert passline.normalize([]) == []

    def test_priced_event(self):
        event = passline.normalize([_record()])[0]

        assert event.source == "passline"
        assert event.source_event_id == "demo-show"
        assert event.title == "Demo show"
        assert event.venue_name == "ROOMIE CLUB"
        assert event.venue_raw == (
            "ROOMIE CLUB, Av. Colón y el Mar, Mar del Plata, "
            "Provincia de Buenos Aires, Argentina"
        )
        assert event.date_start == "2026-10-30"
        assert event.date_end == "2026-10-30"
        assert event.occurrences == ["2026-10-30"]
        assert event.recurrence_unknown is False
        assert event.time == "23:30"
        assert event.price_min == 20000.0
        assert event.price_text is None
        assert event.currency == "ARS"
        assert event.is_free is False
        assert event.ticket_url == "https://www.passline.com/eventos/demo-show"
        assert event.seller == "Passline"
        assert event.image_url == "https://www.passline.com/imagenes/eventos/demo-rec.jpg"
        assert event.city == "Mar del Plata"
        assert event.raw_url == "https://www.passline.com/eventos/demo-show"

    def test_sold_out_event_is_not_dropped(self, passline_source):
        events = {event.source_event_id: event for event in passline.normalize(passline.collect())}

        assert HALLOWEEN_EVENT.rsplit("/", 1)[-1] in events
        halloween = events["3110-big-halloween-mattcity-matt32-vice-city-branco-simon-guille-reboredo-manu-bignami-cmg"]
        assert halloween.date_start == "2026-10-31"
        assert halloween.date_end == "2026-10-31"
        assert halloween.time == "23:30"
        assert halloween.price_min == 7000.0
        assert halloween.seller == "Passline"

    def test_fixture_event_dates_are_single_day(self, passline_source):
        events = {event.source_event_id: event for event in passline.normalize(passline.collect())}

        jones = events["fiesta-de-fin-de-ano-multiempresa-en-jones"]
        assert jones.date_start == "2026-12-18"
        assert jones.date_end == "2026-12-18"
        assert jones.occurrences == ["2026-12-18"]
        assert jones.time == "21:00"
        assert jones.venue_name == "Jones"
        assert jones.venue_raw == f"Jones, {JONES_ADDRESS}"

    def test_missing_price_leaves_price_fields_empty(self):
        event = passline.normalize(
            [_record(price_min=None, price_text=None, currency=None)]
        )[0]

        assert event.price_min is None
        assert event.price_text is None
        assert event.currency is None
        assert event.is_free is None

    def test_missing_date_keeps_the_event(self):
        event = passline.normalize([_record(date_text="")])[0]

        assert event.date_start is None
        assert event.date_end is None
        assert event.occurrences == []
        assert event.recurrence_unknown is False
        assert event.time is None
