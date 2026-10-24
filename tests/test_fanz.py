"""Tests for the Fanz white-label collector (curated tenants, Chauvin today).

Fanz tenants are server-rendered Next.js sites: the home page carries the
whole upcoming inventory inside `__NEXT_DATA__`, and each event page carries
the price in a JSON-LD `Event` block. Every test is offline: `_fetch` reads
the real pages captured in `tests/fixtures/` or a small synthetic page.

The synthetic pages prove the parser is tenant-agnostic: adding a tenant is
one entry in `fanz.TENANTS`.
"""

import json
from pathlib import Path

import pytest
import requests

import collectors.fanz as fanz

FIXTURES = Path(__file__).resolve().parent / "fixtures"

CHAUVIN_HOME = "https://entradas.chauvin.com.ar/"
SUONA_URL = "https://entradas.chauvin.com.ar/event/164319-suona-ensamble"
SUONA_BANNER = "https://event-banners-fanz.s3.amazonaws.com/1790968939223-banner.png"
CHAVIN_VENUE = "Chauvin Centro de creación"

SECOND_TENANT = fanz.Tenant(
    source="otro",
    base_url="https://entradas.otro.com.ar",
    seller="Otro",
    default_venue="Sala Otro",
)


def _load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _home_html(events, hostname="entradas.chauvin.com.ar"):
    """Wrap a synthetic inventory in the Next.js payload Fanz renders."""
    payload = {
        "props": {
            "pageProps": {
                "events": events,
                "timezone": "America/Argentina/Buenos_Aires",
                "hostname": hostname,
            }
        },
        "page": "/",
    }
    return (
        "<html><head></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def _detail_html(price=15000, currency="ARS", offers=None):
    """Minimal event page carrying the JSON-LD block Fanz emits."""
    if offers is None:
        offers = {"@type": "Offer", "price": price, "priceCurrency": currency}
    node = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": "Demo show",
        "offers": offers,
    }
    return (
        "<html><head>"
        '<script type="application/ld+json">'
        f"{json.dumps(node)}"
        "</script></head><body></body></html>"
    )


def _date(start="2026-11-13T00:00:00.000Z", end=None, name="jueves, 12 de noviembre, 21:00"):
    return {
        "start": start,
        "end": end,
        "name": name,
        "id": 1,
        "ticketsLeft": 10,
        "isSoldOut": False,
    }


def _event(
    event_id=1,
    title="Demo show",
    slug="1-demo-show",
    location="Sala Demo",
    dates=None,
):
    return {
        "id": event_id,
        "title": title,
        "slug": slug,
        "banner": "https://example.test/banner.png",
        "Location": {"locationName": location, "isOnline": False},
        "Category": {"id": 1, "name": "Soundroom", "color": "rgb(0, 0, 0)"},
        "Dates": [_date()] if dates is None else dates,
        "cheapestVisibleTicket": None,
        "soldOut": False,
        "isFinished": False,
    }


def _record(**overrides):
    record = {
        "source": "chauvin",
        "event_id": 164319,
        "slug": "164319-suona-ensamble",
        "title": "SUONA Ensamble",
        "category": "Soundroom",
        "dates": [
            _date(start="2026-10-31T00:00:00.000Z", name="viernes, 30 de octubre, 21:00")
        ],
        "venue_name": CHAVIN_VENUE,
        "tenant_venue": CHAVIN_VENUE,
        "seller": "Chauvin",
        "image_url": SUONA_BANNER,
        "ticket_url": SUONA_URL,
        "raw_url": SUONA_URL,
        "detail": {"price": 15000.0, "currency": "ARS"},
    }
    record.update(overrides)
    return record


@pytest.fixture
def fanz_source(monkeypatch):
    """Wire collect() to the fixtures: Chauvin home, real SUONA detail, stub rest."""
    calls = []

    def fetch(url):
        calls.append(url)
        if url == CHAUVIN_HOME:
            return _load("fanz_chauvin_home.html")
        if url == SUONA_URL:
            return _load("fanz_chauvin_event_suona.html")
        return _detail_html(price=9000)

    monkeypatch.setattr(fanz, "REQUEST_DELAY", 0)
    monkeypatch.setattr(fanz, "_fetch", fetch)
    return calls


class TestTenantRegistry:
    def test_the_curated_list_holds_only_chauvin(self):
        assert [tenant.source for tenant in fanz.TENANTS] == ["chauvin"]
        assert fanz.TENANTS[0].base_url == "https://entradas.chauvin.com.ar"
        assert fanz.TENANTS[0].seller == "Chauvin"
        assert fanz.TENANTS[0].default_venue == CHAVIN_VENUE

    def test_tenant_urls_are_derived_from_the_base_url(self):
        tenant = fanz.Tenant(
            source="otro",
            base_url="https://entradas.otro.com.ar",
            seller="Otro",
            default_venue="Sala Otro",
        )

        assert tenant.home_url == "https://entradas.otro.com.ar/"
        assert tenant.event_url("900-show") == "https://entradas.otro.com.ar/event/900-show"


class TestParseHome:
    def test_real_home_carries_the_twelve_upcoming_events(self):
        events = fanz.parse_home(_load("fanz_chauvin_home.html"))

        assert len(events) == 12
        assert [event["id"] for event in events][:3] == [164319, 131810, 164321]
        assert events[0]["title"] == "SUONA Ensamble"
        assert events[0]["slug"] == "164319-suona-ensamble"
        assert events[0]["Dates"][0]["start"] == "2026-10-31T00:00:00.000Z"

    def test_page_without_next_data_raises(self):
        with pytest.raises(ValueError):
            fanz.parse_home("<html><body><p>not a Fanz page</p></body></html>")

    def test_malformed_next_data_raises(self):
        html = '<html><body><script id="__NEXT_DATA__">{not json}</script></body></html>'

        with pytest.raises(ValueError):
            fanz.parse_home(html)

    def test_payload_without_events_raises(self):
        html = '<html><body><script id="__NEXT_DATA__">{"props": {"pageProps": {}}}</script></body></html>'

        with pytest.raises(ValueError):
            fanz.parse_home(html)

    def test_empty_inventory_is_a_valid_result(self):
        assert fanz.parse_home(_home_html([])) == []


class TestParseDetail:
    def test_real_page_supplies_the_price_from_json_ld(self):
        detail = fanz.parse_detail(_load("fanz_chauvin_event_suona.html"))

        assert detail == {"price": 15000.0, "currency": "ARS"}

    def test_a_list_of_offers_yields_the_cheapest_price(self):
        offers = [
            {"@type": "Offer", "price": 20000, "priceCurrency": "ARS"},
            {"@type": "Offer", "price": 15000, "priceCurrency": "ARS"},
        ]

        assert fanz.parse_detail(_detail_html(offers=offers))["price"] == 15000.0

    def test_an_object_price_is_read_from_its_value(self):
        offers = {"@type": "Offer", "price": {"value": 18000}, "priceCurrency": "ARS"}

        assert fanz.parse_detail(_detail_html(offers=offers))["price"] == 18000.0

    def test_page_without_an_offer_has_no_price(self):
        detail = fanz.parse_detail(_detail_html(offers={"@type": "Offer"}))

        assert detail == {"price": None, "currency": None}

    def test_page_without_event_json_ld_raises(self):
        with pytest.raises(ValueError):
            fanz.parse_detail("<html><body><p>not an event</p></body></html>")

    def test_malformed_json_ld_raises(self):
        html = (
            "<html><head>"
            '<script type="application/ld+json">{not json}</script>'
            "</head></html>"
        )

        with pytest.raises(ValueError):
            fanz.parse_detail(html)


class TestCollect:
    def test_collects_the_home_then_every_detail_page(self, fanz_source):
        records = fanz.collect()

        assert fanz_source[0] == CHAUVIN_HOME
        assert len(fanz_source) == 13
        assert fanz_source[1] == SUONA_URL
        assert all(url.startswith(CHAUVIN_HOME + "event/") for url in fanz_source[1:])
        assert len(records) == 12
        assert records[0]["title"] == "SUONA Ensamble"
        assert records[0]["detail"] == {"price": 15000.0, "currency": "ARS"}
        assert records[1]["detail"] == {"price": 9000.0, "currency": "ARS"}

    def test_raw_records_carry_listing_and_detail_data(self, fanz_source):
        record = fanz.collect()[0]

        assert record["source"] == "chauvin"
        assert record["event_id"] == 164319
        assert record["slug"] == "164319-suona-ensamble"
        assert record["category"] == "Soundroom"
        assert record["dates"] == [
            {
                "start": "2026-10-31T00:00:00.000Z",
                "end": "2026-10-31T02:00:00.000Z",
                "name": "viernes, 30 de octubre, 21:00",
                "sold_out": False,
                "tickets_left": 53,
            }
        ]
        assert record["venue_name"] == CHAVIN_VENUE
        assert record["tenant_venue"] == CHAVIN_VENUE
        assert record["seller"] == "Chauvin"
        assert record["image_url"] == SUONA_BANNER
        assert record["ticket_url"] == SUONA_URL
        assert record["raw_url"] == SUONA_URL

    def test_records_are_json_serializable(self, fanz_source):
        records = fanz.collect()

        assert len(json.loads(json.dumps(records))) == 12

    def test_failing_detail_keeps_the_event_with_an_unknown_price(
        self, monkeypatch, capsys
    ):
        def fetch(url):
            if url == CHAUVIN_HOME:
                return _load("fanz_chauvin_home.html")
            if url == SUONA_URL:
                raise requests.RequestException("boom")
            return _detail_html(price=9000)

        monkeypatch.setattr(fanz, "REQUEST_DELAY", 0)
        monkeypatch.setattr(fanz, "_fetch", fetch)

        records = fanz.collect()
        events = fanz.normalize(records)

        assert len(records) == 12
        assert records[0]["detail"] is None
        assert events[0].title == "SUONA Ensamble"
        assert events[0].price_min is None
        assert events[0].is_free is None
        assert events[0].currency is None
        assert f"[fanz] detail {SUONA_URL}" in capsys.readouterr().err

    def test_unparsable_detail_keeps_the_event(self, monkeypatch, capsys):
        def fetch(url):
            if url == CHAUVIN_HOME:
                return _load("fanz_chauvin_home.html")
            if url == SUONA_URL:
                return "<html><body><p>not an event</p></body></html>"
            return _detail_html(price=9000)

        monkeypatch.setattr(fanz, "REQUEST_DELAY", 0)
        monkeypatch.setattr(fanz, "_fetch", fetch)

        records = fanz.collect()

        assert len(records) == 12
        assert records[0]["detail"] is None
        assert f"[fanz] detail {SUONA_URL}" in capsys.readouterr().err

    def test_failing_tenant_home_is_logged_and_skipped(self, monkeypatch, capsys):
        def fetch(url):
            if url == SECOND_TENANT.home_url:
                raise requests.RequestException("boom")
            if url == CHAUVIN_HOME:
                return _load("fanz_chauvin_home.html")
            return _detail_html(price=9000)

        monkeypatch.setattr(fanz, "REQUEST_DELAY", 0)
        monkeypatch.setattr(fanz, "TENANTS", (fanz.TENANTS[0], SECOND_TENANT))
        monkeypatch.setattr(fanz, "_fetch", fetch)

        records = fanz.collect()

        assert len(records) == 12
        assert {record["source"] for record in records} == {"chauvin"}
        assert f"[fanz] tenant {SECOND_TENANT.source} home failed" in capsys.readouterr().err

    def test_every_tenant_failing_raises(self, monkeypatch):
        def fetch(url):
            raise requests.RequestException("boom")

        monkeypatch.setattr(fanz, "REQUEST_DELAY", 0)
        monkeypatch.setattr(fanz, "_fetch", fetch)

        with pytest.raises(requests.RequestException):
            fanz.collect()

    def test_requests_are_spaced_one_second_apart(self, monkeypatch):
        def fetch(url):
            if url == CHAUVIN_HOME:
                return _load("fanz_chauvin_home.html")
            return _detail_html()

        monkeypatch.setattr(fanz, "REQUEST_DELAY", 1.0)
        monkeypatch.setattr(fanz, "_fetch", fetch)
        waits = []
        monkeypatch.setattr(fanz.time, "sleep", waits.append)

        records = fanz.collect()

        assert len(records) == 12
        # One home request plus twelve details: the first one is immediate.
        assert waits == [1.0] * 12

    def test_a_second_tenant_is_one_tuple_entry(self, monkeypatch):
        home = _home_html(
            [
                _event(
                    event_id=900,
                    slug="900-show-sin-sala",
                    title="Show sin sala",
                    location=None,
                ),
                _event(
                    event_id=901,
                    slug="901-show-con-sala",
                    title="Show con sala",
                    location="Sala Chica",
                ),
            ],
            hostname="entradas.otro.com.ar",
        )
        calls = []

        def fetch(url):
            calls.append(url)
            if url == CHAUVIN_HOME:
                return _load("fanz_chauvin_home.html")
            if url == SECOND_TENANT.home_url:
                return home
            if url.startswith(SECOND_TENANT.base_url + "/event/"):
                return _detail_html(price=8000)
            return _detail_html(price=9000)

        monkeypatch.setattr(fanz, "REQUEST_DELAY", 0)
        monkeypatch.setattr(fanz, "TENANTS", (fanz.TENANTS[0], SECOND_TENANT))
        monkeypatch.setattr(fanz, "_fetch", fetch)

        records = fanz.collect()

        assert SECOND_TENANT.home_url in calls
        assert len(records) == 14
        second = [record for record in records if record["source"] == "otro"]
        assert [record["title"] for record in second] == ["Show sin sala", "Show con sala"]
        events = fanz.normalize(second)
        assert events[0].venue_name == "Sala Otro"
        assert events[0].venue_raw == "Sala Otro"
        assert events[0].seller == "Otro"
        assert events[0].ticket_url == "https://entradas.otro.com.ar/event/900-show-sin-sala"
        assert events[1].venue_name == "Sala Chica"


class TestNormalize:
    def test_empty_input(self):
        assert fanz.normalize([]) == []

    def test_utc_start_is_shifted_to_art(self):
        event = fanz.normalize([_record()])[0]

        assert event.date_start == "2026-10-30"
        assert event.date_end == "2026-10-30"
        assert event.occurrences == ["2026-10-30"]
        assert event.time == "21:00"
        assert event.recurrence_unknown is False

    def test_a_naive_start_is_read_as_utc(self):
        record = _record(dates=[_date(start="2026-10-31T00:00:00")])

        event = fanz.normalize([record])[0]

        assert event.date_start == "2026-10-30"
        assert event.time == "21:00"

    def test_every_fixture_start_matches_its_human_time_string(self):
        """The ART conversion must agree with Dates[].name on all 12 events."""
        events = fanz.parse_home(_load("fanz_chauvin_home.html"))

        checked = 0
        for event in events:
            for node in event["Dates"]:
                normalized = fanz.normalize([_record(event_id=event["id"], dates=[node])])[0]
                expected_time = node["name"].rsplit(",", 1)[-1].strip()

                assert normalized.time == expected_time
                checked += 1
        assert checked == 13

    def test_detail_price_fills_the_price_fields(self):
        event = fanz.normalize([_record()])[0]

        assert event.price_min == 15000.0
        assert event.currency == "ARS"
        assert event.is_free is False
        assert event.price_text is None

    def test_zero_price_is_free(self):
        record = _record(detail={"price": 0.0, "currency": "ARS"})

        event = fanz.normalize([record])[0]

        assert event.price_min == 0.0
        assert event.is_free is True
        assert event.currency == "ARS"

    def test_missing_detail_leaves_the_price_unknown(self):
        event = fanz.normalize([_record(detail=None)])[0]

        assert event.price_min is None
        assert event.is_free is None
        assert event.currency is None

    def test_multiple_dates_are_sorted_and_deduplicated(self):
        record = _record(
            dates=[
                _date(start="2026-12-13T00:00:00.000Z"),
                _date(start="2026-11-13T00:00:00.000Z"),
                _date(start="2026-12-14T00:30:00.000Z"),
                _date(start="2026-11-13T01:00:00.000Z"),
            ]
        )

        event = fanz.normalize([record])[0]

        assert event.occurrences == ["2026-11-12", "2026-12-12", "2026-12-13"]
        assert event.date_start == "2026-11-12"
        assert event.date_end == "2026-12-13"
        assert event.time == "21:00"

    def test_real_multi_date_event_collapses_its_shared_local_date(self):
        record = _record(
            event_id=161979,
            slug="161979-el-sueno-de-los-elefantes",
            title="EL SUEÑO DE LOS ELEFANTES",
            dates=[
                _date(start="2026-12-12T22:00:00.000Z"),
                _date(start="2026-12-13T00:00:00.000Z"),
            ],
            detail={"price": 12000.0, "currency": "ARS"},
        )

        event = fanz.normalize([record])[0]

        assert event.occurrences == ["2026-12-12"]
        assert event.date_start == "2026-12-12"
        assert event.date_end == "2026-12-12"
        assert event.time == "19:00"

    def test_event_without_dates_is_skipped(self, capsys):
        assert fanz.normalize([_record(dates=[])]) == []
        assert "[fanz] event 164319 skipped: no dates" in capsys.readouterr().err

    def test_event_with_an_unparsable_start_is_skipped(self, capsys):
        record = _record(dates=[_date(start="not-a-date")])

        assert fanz.normalize([record]) == []
        assert "[fanz] event 164319 skipped: unparseable start" in capsys.readouterr().err

    def test_missing_location_name_falls_back_to_the_tenant_venue(self):
        event = fanz.normalize([_record(venue_name="")])[0]

        assert event.venue_name == CHAVIN_VENUE
        assert event.venue_raw == CHAVIN_VENUE

    def test_source_event_id_falls_back_to_the_slug(self):
        event = fanz.normalize([_record(event_id=None)])[0]

        assert event.source_event_id == "164319-suona-ensamble"

    def test_source_event_id_prefers_the_numeric_id(self):
        event = fanz.normalize([_record()])[0]

        assert event.source_event_id == "164319"

    def test_event_identity_and_links(self):
        event = fanz.normalize([_record()])[0]

        assert event.source == "chauvin"
        assert event.title == "SUONA Ensamble"
        assert event.seller == "Chauvin"
        assert event.ticket_url == SUONA_URL
        assert event.raw_url == SUONA_URL
        assert event.image_url == SUONA_BANNER
        assert event.city == "Mar del Plata"


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

        monkeypatch.setattr(fanz.requests, "get", fake_get)

        html = fanz._fetch(CHAUVIN_HOME)

        assert html == "<html></html>"
        assert seen == {
            "url": CHAUVIN_HOME,
            "headers": {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"},
            "timeout": 30,
        }

    def test_fetch_raises_on_http_error(self, monkeypatch):
        class FailingResponse:
            def raise_for_status(self):
                raise requests.HTTPError("404")

        monkeypatch.setattr(
            fanz.requests, "get", lambda *args, **kwargs: FailingResponse()
        )

        with pytest.raises(requests.HTTPError):
            fanz._fetch("https://entradas.chauvin.com.ar/event/missing")
