"""Tests for the TuEntrada collector (server-rendered search + RSC sessions).

Every test is offline: search and event fetches are replaced with fixtures so
`collect()` never touches the network.
"""

import json
from pathlib import Path

import pytest
import requests

from collectors import tuentrada

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_IMAGE = (
    "https://bucket.tuentrada.com/cdn-cgi/image/width=590,height=548,format=auto,quality=85/"
    "bucket/events/paren-la-mano/paren-la-mano-image-main-1784649384.jpg"
)


def _load_html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _card(slug, title, when, venue_text, image_url="https://bucket.tuentrada.com/demo.jpg"):
    return (
        f'<a href="{slug}"><div class="flex items-stretch bg-white">'
        f'<img src="{image_url}" alt="{title}"/>'
        f"<h2>{title}</h2>"
        f'<span><svg class="lucide lucide-calendar-days"></svg>{when}</span>'
        f'<span><svg class="lucide lucide-map-pin"></svg>{venue_text}</span>'
        f"</div></a>"
    )


def _search_page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


def _push(text):
    """One RSC flight push carrying `text` as its JSON string literal."""
    return f"<script>self.__next_f.push([1,{json.dumps(text)}])</script>"


def _record(**overrides):
    record = {
        "source": "tuentrada",
        "slug": "demo",
        "title": "Demo",
        "date": "2026-11-07",
        "date_end": None,
        "time": "21:00",
        "venue": "Teatro Enrique Carreras",
        "city": "Mar Del Plata",
        "image_url": "https://bucket.tuentrada.com/demo.jpg",
        "raw_url": "https://www.tuentrada.com/demo",
        "detail": None,
    }
    record.update(overrides)
    return record


def _fixture_record():
    record = tuentrada.parse_search(_load_html("tuentrada_search.html"))[0]
    record["detail"] = tuentrada.parse_event(_load_html("tuentrada_event.html"))
    return record


class TestParseSearch:
    def test_fixture_card_is_fully_parsed(self):
        records = tuentrada.parse_search(_load_html("tuentrada_search.html"))

        assert records == [
            {
                "source": "tuentrada",
                "slug": "paren-la-mano-mdq",
                "title": "PAREN LA MANO",
                "date": "2026-11-07",
                "date_end": None,
                "time": "21:00",
                "venue": "Polideportivo Mar De Plata",
                "city": "Mar Del Plata",
                "image_url": FIXTURE_IMAGE,
                "raw_url": "https://www.tuentrada.com/paren-la-mano-mdq",
            }
        ]

    def test_multi_day_range_parses_end_date_and_no_time(self):
        html = _search_page(
            _card("obra-1", "Obra", "Del 23-10-2026 al 27-10-2026", "Teatro Enrique Carreras")
        )

        record = tuentrada.parse_search(html)[0]

        assert record["date"] == "2026-10-23"
        assert record["date_end"] == "2026-10-27"
        assert record["time"] is None
        assert record["venue"] == "Teatro Enrique Carreras"
        assert record["city"] == ""

    def test_hrefs_with_paths_or_absolute_urls_are_skipped(self):
        html = _search_page(
            _card(
                "https://evil.test/evento",
                "Absoluta",
                "01-11-2026 20:00 hs",
                "Teatro X, Mar Del Plata",
            ),
            _card("evento/anidado", "Anidada", "01-11-2026 20:00 hs", "Teatro X, Mar Del Plata"),
            _card("/evento-valido/", "Válida", "01-11-2026 20:00 hs", "Teatro X, Mar Del Plata"),
        )

        assert [record["slug"] for record in tuentrada.parse_search(html)] == ["evento-valido"]

    def test_anchor_without_card_container_is_ignored(self):
        html = '<a href="suelto"><div class="plain">x</div></a>'

        assert tuentrada.parse_search(html) == []


class TestParseEvent:
    def test_fixture_session_is_fully_parsed(self):
        payload = tuentrada.parse_event(_load_html("tuentrada_event.html"))

        assert list(payload) == ["sessions"]
        assert len(payload["sessions"]) == 1
        session = payload["sessions"][0]
        assert session["id"] == 7478
        assert session["date"] == "2026-11-07T21:00:00-03:00"
        assert session["venue"] == "Polideportivo Mar De Plata"
        assert session["city"] == "Mar Del Plata"
        assert session["name"] == "Paren La Mano"
        assert session["availability"] == "Disponible"

    def test_marker_split_across_pushes_is_joined(self):
        html = _push('prefix "eventSess') + _push('ions":[{"id": 7}] suffix')

        assert tuentrada.parse_event(html) == {"sessions": [{"id": 7}]}

    def test_missing_or_invalid_marker_returns_no_sessions(self):
        assert tuentrada.parse_event("<html></html>") == {"sessions": []}
        assert tuentrada.parse_event(_push('"eventSessions": not-json')) == {"sessions": []}
        assert tuentrada.parse_event(_push('"eventSessions": {"id": 1}')) == {"sessions": []}

    def test_non_dict_entries_are_dropped(self):
        html = _push('"eventSessions": [{"id": 1}, 42, "skip"]')

        assert tuentrada.parse_event(html) == {"sessions": [{"id": 1}]}


class TestRequestContract:
    class FakeResponse:
        def __init__(self, text=""):
            self.text = text

        def raise_for_status(self):
            pass

    def test_search_request_contract(self, monkeypatch):
        seen = {}
        response = self.FakeResponse(text="<html>ok</html>")

        def fake_get(url, params=None, headers=None, timeout=None):
            seen.update(url=url, params=params, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(tuentrada.requests, "get", fake_get)

        html = tuentrada._fetch_search("mar del plata")

        assert html == "<html>ok</html>"
        assert seen == {
            "url": "https://www.tuentrada.com/busqueda",
            "params": {"q": "mar del plata"},
            "headers": {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"},
            "timeout": 30,
        }

    def test_event_request_contract(self, monkeypatch):
        seen = {}
        response = self.FakeResponse(text=_load_html("tuentrada_event.html"))

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(tuentrada.requests, "get", fake_get)

        detail = tuentrada._fetch_event("paren-la-mano-mdq")

        assert seen == {
            "url": "https://www.tuentrada.com/paren-la-mano-mdq",
            "headers": {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"},
            "timeout": 30,
        }
        assert detail["sessions"][0]["id"] == 7478


class TestIsMdp:
    @pytest.mark.parametrize(
        ("record", "expected"),
        [
            ({"city": "Mar Del Plata", "venue": "Teatro X"}, True),
            ({"city": "mar del plata", "venue": ""}, True),
            ({"city": "", "venue": "Polideportivo Mar del Plata"}, True),
            ({"city": "", "venue": "Estadio Islas Malvinas"}, False),
            ({"city": "Córdoba", "venue": "Teatro X"}, False),
            ({"city": "", "venue": ""}, False),
        ],
    )
    def test_filter(self, record, expected):
        assert tuentrada._is_mdp(record) is expected


class TestCollect:
    def test_dedupes_slugs_across_queries(self, monkeypatch):
        html = _load_html("tuentrada_search.html")
        calls = {"search": [], "detail": []}

        def fetch_search(query):
            calls["search"].append(query)
            return html

        def fetch_event(slug):
            calls["detail"].append(slug)
            return tuentrada.parse_event(_load_html("tuentrada_event.html"))

        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "QUERIES", ("mar del plata", "otra busqueda"))
        monkeypatch.setattr(tuentrada, "_fetch_search", fetch_search)
        monkeypatch.setattr(tuentrada, "_fetch_event", fetch_event)

        records = tuentrada.collect()

        assert calls["search"] == ["mar del plata", "otra busqueda"]
        assert calls["detail"] == ["paren-la-mano-mdq"]
        assert [record["slug"] for record in records] == ["paren-la-mano-mdq"]
        assert records[0]["detail"]["sessions"][0]["id"] == 7478

    def test_keeps_only_mdp_cards(self, monkeypatch):
        html = _search_page(
            _card("mdp-1", "MDP", "07-11-2026 21:00 hs", "Polideportivo Mar De Plata, Mar Del Plata"),
            _card("cba-1", "CBA", "07-11-2026 21:00 hs", "Teatro X, Córdoba"),
            _card("mdp-2", "Sin ciudad", "08-11-2026 20:00 hs", "Teatro Mar del Plata"),
        )
        calls = []

        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "_fetch_search", lambda query: html)
        monkeypatch.setattr(tuentrada, "_fetch_event", lambda slug: calls.append(slug) or None)

        records = tuentrada.collect()

        assert [record["slug"] for record in records] == ["mdp-1", "mdp-2"]
        assert calls == ["mdp-1", "mdp-2"]

    def test_max_events_caps_collection(self, monkeypatch):
        html = _search_page(
            _card("mdp-1", "Uno", "07-11-2026 21:00 hs", "Teatro X, Mar Del Plata"),
            _card("mdp-2", "Dos", "08-11-2026 21:00 hs", "Teatro X, Mar Del Plata"),
        )
        search_calls = []

        def fetch_search(query):
            search_calls.append(query)
            return html

        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "MAX_EVENTS", 1)
        monkeypatch.setattr(tuentrada, "QUERIES", ("uno", "dos"))
        monkeypatch.setattr(tuentrada, "_fetch_search", fetch_search)
        monkeypatch.setattr(tuentrada, "_fetch_event", lambda slug: None)

        records = tuentrada.collect()

        assert search_calls == ["uno"]
        assert [record["slug"] for record in records] == ["mdp-1"]

    def test_first_search_failure_propagates(self, monkeypatch):
        calls = []

        def fetch_search(query):
            calls.append(query)
            raise requests.RequestException("boom")

        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "QUERIES", ("uno", "dos"))
        monkeypatch.setattr(tuentrada, "_fetch_search", fetch_search)

        with pytest.raises(requests.RequestException):
            tuentrada.collect()

        assert calls == ["uno"]

    def test_later_search_failure_logs_and_keeps_collected_records(self, monkeypatch, capsys):
        html = _load_html("tuentrada_search.html")

        def fetch_search(query):
            if query == "dos":
                raise requests.RequestException("boom")
            return html

        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "QUERIES", ("uno", "dos"))
        monkeypatch.setattr(tuentrada, "_fetch_search", fetch_search)
        monkeypatch.setattr(
            tuentrada,
            "_fetch_event",
            lambda slug: tuentrada.parse_event(_load_html("tuentrada_event.html")),
        )

        records = tuentrada.collect()

        assert [record["slug"] for record in records] == ["paren-la-mano-mdq"]
        assert records[0]["detail"] is not None
        assert "[tuentrada] search" in capsys.readouterr().err

    def test_detail_failure_keeps_event_and_logs(self, monkeypatch, capsys):
        html = _load_html("tuentrada_search.html")

        def failing_detail(slug):
            raise requests.RequestException("boom")

        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "_fetch_search", lambda query: html)
        monkeypatch.setattr(tuentrada, "_fetch_event", failing_detail)

        records = tuentrada.collect()
        events = tuentrada.normalize(records)

        assert len(records) == 1
        assert records[0]["detail"] is None
        assert events[0].date_start == "2026-11-07"
        assert "[tuentrada] detail paren-la-mano-mdq failed:" in capsys.readouterr().err

    def test_raw_records_are_json_ready(self, monkeypatch):
        monkeypatch.setattr(tuentrada, "REQUEST_DELAY", 0)
        monkeypatch.setattr(tuentrada, "_fetch_search", lambda query: _load_html("tuentrada_search.html"))
        monkeypatch.setattr(
            tuentrada,
            "_fetch_event",
            lambda slug: tuentrada.parse_event(_load_html("tuentrada_event.html")),
        )

        json.dumps(tuentrada.collect())


class TestNormalize:
    def test_fixture_record_maps_polideportivo_and_session_fields(self):
        event = tuentrada.normalize([_fixture_record()])[0]

        assert event.source == "tuentrada"
        assert event.source_event_id == "paren-la-mano-mdq"
        assert event.title == "PAREN LA MANO"
        assert event.venue_name == "Polideportivo Islas Malvinas"
        assert event.venue_raw == "Polideportivo Mar De Plata, Mar Del Plata"
        assert event.date_start == "2026-11-07"
        assert event.date_end == "2026-11-07"
        assert event.occurrences == ["2026-11-07"]
        assert event.recurrence_unknown is False
        assert event.multi_date_incomplete is False
        assert event.time == "21:00"
        assert event.is_free is None
        assert event.price_text is None
        assert event.price_min is None
        assert event.currency is None
        assert event.ticket_url == "https://www.tuentrada.com/paren-la-mano-mdq"
        assert event.seller == "TuEntrada"
        assert event.image_url == FIXTURE_IMAGE
        assert event.city == "Mar del Plata"
        assert event.raw_url == "https://www.tuentrada.com/paren-la-mano-mdq"

    def test_sessions_supply_sorted_dates_and_first_session_time(self):
        sessions = [
            {
                "id": 1,
                "date": "2026-11-07T18:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "Mar Del Plata",
                "name": "Sesión",
            },
            {
                "id": 2,
                "date": "2026-11-09T20:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "Mar Del Plata",
                "name": "Sesión",
            },
            {
                "id": 3,
                "date": "2026-11-08T19:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "Mar Del Plata",
                "name": "Sesión",
            },
        ]

        event = tuentrada.normalize([_record(title="", detail={"sessions": sessions})])[0]

        assert event.occurrences == ["2026-11-07", "2026-11-08", "2026-11-09"]
        assert event.date_start == "2026-11-07"
        assert event.date_end == "2026-11-09"
        assert event.time == "18:00"
        assert event.title == "Sesión"
        assert event.venue_name == "Teatro Enrique Carreras"
        assert event.venue_raw == "Teatro Enrique Carreras, Mar Del Plata"

    def test_non_mdp_sessions_are_dropped(self):
        sessions = [
            {
                "id": 1,
                "date": "2026-11-10T19:00:00-03:00",
                "venue": "Teatro X",
                "city": "Córdoba",
                "name": "Demo",
            },
            {
                "id": 2,
                "date": "2026-11-07T21:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "Mar Del Plata",
                "name": "Demo",
            },
        ]

        event = tuentrada.normalize([_record(detail={"sessions": sessions})])[0]

        assert event.occurrences == ["2026-11-07"]
        assert event.date_start == "2026-11-07"
        assert event.date_end == "2026-11-07"
        assert event.time == "21:00"

    def test_session_with_empty_city_is_kept(self):
        sessions = [
            {
                "id": 1,
                "date": "2026-11-07T21:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "",
                "name": "Demo",
            }
        ]

        event = tuentrada.normalize([_record(detail={"sessions": sessions})])[0]

        assert event.occurrences == ["2026-11-07"]
        assert event.venue_name == "Teatro Enrique Carreras"

    def test_all_non_mdp_sessions_fall_back_to_the_card(self):
        sessions = [
            {
                "id": 1,
                "date": "2026-11-10T19:00:00-03:00",
                "venue": "Teatro X",
                "city": "Córdoba",
                "name": "Demo",
            }
        ]

        event = tuentrada.normalize([_record(detail={"sessions": sessions})])[0]

        assert event.occurrences == ["2026-11-07"]
        assert event.date_start == "2026-11-07"

    def test_sessions_are_sorted_before_picking_the_first_time(self):
        sessions = [
            {
                "id": 1,
                "date": "2026-11-09T20:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "Mar Del Plata",
                "name": "Sesión",
            },
            {
                "id": 2,
                "date": "2026-11-07T18:00:00-03:00",
                "venue": "Teatro Enrique Carreras",
                "city": "Mar Del Plata",
                "name": "Sesión",
            },
        ]

        event = tuentrada.normalize([_record(detail={"sessions": sessions})])[0]

        assert event.date_start == "2026-11-07"
        assert event.time == "18:00"

    def test_missing_detail_keeps_a_card_range_without_inventing_dates(self):
        event = tuentrada.normalize(
            [
                _record(
                    date="2026-11-13",
                    date_end="2026-11-20",
                    detail=None,
                )
            ]
        )[0]

        assert event.date_start == "2026-11-13"
        assert event.date_end == "2026-11-20"
        assert event.occurrences == []
        assert event.recurrence_unknown is True

    def test_missing_detail_uses_card_fields(self):
        event = tuentrada.normalize([_record(detail=None)])[0]

        assert event.title == "Demo"
        assert event.date_start == "2026-11-07"
        assert event.date_end == "2026-11-07"
        assert event.occurrences == ["2026-11-07"]
        assert event.time == "21:00"
        assert event.venue_name == "Teatro Enrique Carreras"
        assert event.venue_raw == "Teatro Enrique Carreras, Mar Del Plata"

    def test_empty_detail_sessions_use_card_fields(self):
        event = tuentrada.normalize([_record(detail={"sessions": []})])[0]

        assert event.occurrences == ["2026-11-07"]
        assert event.time == "21:00"

    def test_record_without_dates_is_skipped(self):
        assert tuentrada.normalize([_record(date=None, detail=None)]) == []

    def test_unknown_venue_keeps_its_name(self):
        event = tuentrada.normalize([_record(venue="Centro Cultural Sur", city="Mar Del Plata")])[0]

        assert event.venue_name == "Centro Cultural Sur"
        assert event.venue_raw == "Centro Cultural Sur, Mar Del Plata"
