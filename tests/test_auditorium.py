"""Tests for the Teatro Auditorium collector (listing pages + page detail).

Every test is offline: `_fetch_page` and `_fetch_detail` are replaced with
fixtures so `collect()` never touches the network.
"""

from pathlib import Path

import pytest
import requests

import collectors.auditorium as auditorium

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE = "https://teatroauditorium.gba.gob.ar"
LISTING_PAGE_0 = "auditorium_programacion.html"
LISTING_PAGE_1 = "auditorium_programacion_p1.html"

# Listing path -> detail fixture captured from that very page.
DETAIL_FIXTURES = {
    "/actividades-agenda/proyectan-el-documental-desobediente": "auditorium_detail_plateanet.html",
    "/actividades-agenda/presentan-el-libro-apogeo-y-ocaso-de-regimenes-militares-en-argentina-del-doctor": (
        "auditorium_detail_free.html"
    ),
    "/actividades-agenda/despues-del-fuego-en-el-cafe-teatral": "auditorium_detail_boleteria.html",
}

EMPTY_PAGE = "<html><body>sin resultados</body></html>"


def _load_html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _record(**overrides):
    record = {
        "source": "auditorium",
        "title": "Demo",
        "path": "/actividades-agenda/demo",
        "sala": "Astor Piazzolla",
        "datetimes": ["2026-11-01T20:00:00-03:00", "2026-11-01T20:00:00-03:00", "2026-11-01T21:30:00-03:00"],
        "image_url": None,
        "raw_url": f"{BASE}/actividades-agenda/demo",
        "detail": None,
    }
    record.update(overrides)
    return record


@pytest.fixture
def auditorium_source(monkeypatch):
    """Wire collect() to the two listing fixtures plus a trailing empty page."""
    pages = {0: _load_html(LISTING_PAGE_0), 1: _load_html(LISTING_PAGE_1)}
    calls = {"pages": [], "details": []}

    def fetch_page(page):
        calls["pages"].append(page)
        return pages.get(page, EMPTY_PAGE)

    def fetch_detail(path):
        calls["details"].append(path)
        fixture = DETAIL_FIXTURES.get(path)
        return auditorium.parse_detail(_load_html(fixture)) if fixture else None

    monkeypatch.setattr(auditorium, "REQUEST_DELAY", 0)
    monkeypatch.setattr(auditorium, "_fetch_page", fetch_page)
    monkeypatch.setattr(auditorium, "_fetch_detail", fetch_detail)
    return calls


class TestParsePage:
    def test_parses_first_listing_page(self):
        records = auditorium.parse_page(_load_html(LISTING_PAGE_0))

        assert len(records) == 6
        first = records[0]
        assert first["source"] == "auditorium"
        assert first["title"] == "Proyectan el documental “Desobediente”"
        assert first["path"] == "/actividades-agenda/proyectan-el-documental-desobediente"
        assert first["sala"] == "Roberto J. Payró"
        assert first["datetimes"] == [
            "2026-10-24T18:00:00-03:00",
            "2026-10-24T18:00:00-03:00",
            "2026-10-24T19:48:00-03:00",
        ]
        assert first["image_url"] == (
            f"{BASE}/sites/default/files/styles/resumen_noticias/public/actividades/"
            "agenda-cartelera/2026/10/proyectan-el-documental-desobediente.jpg.webp?itok=MplSOvjW"
        )
        assert first["raw_url"] == f"{BASE}/actividades-agenda/proyectan-el-documental-desobediente"

    def test_parses_second_listing_page_in_document_order(self):
        records = auditorium.parse_page(_load_html(LISTING_PAGE_1))

        assert len(records) == 6
        assert records[0]["title"] == 'Los locos del radioteatro presentan "Juana es América"'
        despues = next(record for record in records if record["path"].endswith("despues-del-fuego-en-el-cafe-teatral"))
        assert despues["title"] == "“Después del Fuego” en el Café Teatral"
        assert despues["sala"] == "Café Teatral Emilio Alfaro"

    def test_multi_function_day_keeps_duplicate_datetimes(self):
        records = auditorium.parse_page(_load_html(LISTING_PAGE_0))

        fifth = records[4]
        assert fifth["title"] == "Proyectan “La vida es así” en el ciclo Cine Arte"
        assert len(fifth["datetimes"]) == 6
        assert {value[:10] for value in fifth["datetimes"]} == {"2026-10-25"}
        assert fifth["sala"] == "Astor Piazzolla"

    def test_jorge_laureti_sala_is_parsed(self):
        records = auditorium.parse_page(_load_html(LISTING_PAGE_0))

        assert records[3]["sala"] == "Jorge Laureti - Puerto"

    def test_missing_sala_and_image_are_none(self):
        html = (
            '<html><article class="node--type-actividades-agenda">'
            '<h2><a href="/actividades-agenda/demo">Demo</a></h2>'
            "</article></html>"
        )

        records = auditorium.parse_page(html)

        assert len(records) == 1
        assert records[0]["sala"] is None
        assert records[0]["image_url"] is None
        assert records[0]["datetimes"] == []


class TestParseDetail:
    def test_plateanet_detail(self):
        assert auditorium.parse_detail(_load_html("auditorium_detail_plateanet.html")) == {
            "seller": "Plateanet",
            "is_free": False,
        }

    def test_free_detail(self):
        assert auditorium.parse_detail(_load_html("auditorium_detail_free.html")) == {
            "seller": None,
            "is_free": True,
        }

    def test_boleteria_detail(self):
        assert auditorium.parse_detail(_load_html("auditorium_detail_boleteria.html")) == {
            "seller": None,
            "is_free": False,
        }

    def test_seller_match_is_case_insensitive(self):
        detail = auditorium.parse_detail("<html><body>Venta por PLATEANET</body></html>")

        assert detail["seller"] == "Plateanet"

    def test_script_text_is_ignored(self):
        detail = auditorium.parse_detail(
            "<html><head><script>Localidades en venta por Plateanet</script></head>"
            "<body>Entrada libre y gratuita</body></html>"
        )

        assert detail == {"seller": None, "is_free": True}

    def test_unknown_detail_is_none(self):
        assert auditorium.parse_detail("<html><body>Información general</body></html>") == {
            "seller": None,
            "is_free": None,
        }


class TestCollect:
    def test_stops_paging_on_empty_page_and_fetches_every_detail(self, auditorium_source):
        records = auditorium.collect()

        assert auditorium_source["pages"] == [0, 1, 2]
        assert len(records) == 12
        assert all(record["source"] == "auditorium" for record in records)
        assert all("detail" in record for record in records)
        assert auditorium_source["details"] == [record["path"] for record in records]

    def test_detail_enrichment_reaches_normalize(self, auditorium_source):
        events = {event.source_event_id: event for event in auditorium.normalize(auditorium.collect())}

        desobediente = events["proyectan-el-documental-desobediente"]
        assert desobediente.seller == "Plateanet"
        assert desobediente.is_free is False

        libro = events["presentan-el-libro-apogeo-y-ocaso-de-regimenes-militares-en-argentina-del-doctor"]
        assert libro.seller is None
        assert libro.is_free is True

        fuego = events["despues-del-fuego-en-el-cafe-teatral"]
        assert fuego.seller is None
        assert fuego.is_free is False

        sin_detalle = events["mar-del-plata-adora-llega-la-piazzolla"]
        assert sin_detalle.seller is None
        assert sin_detalle.is_free is None

    def test_detail_failure_keeps_event_and_logs(self, auditorium_source, capsys, monkeypatch):
        def failing_detail(path):
            raise requests.RequestException("boom")

        monkeypatch.setattr(auditorium, "_fetch_detail", failing_detail)

        records = auditorium.collect()
        events = auditorium.normalize(records)

        assert len(records) == 12
        assert all(record["detail"] is None for record in records)
        assert all(event.seller is None and event.is_free is None for event in events)
        assert "[auditorium] detail /actividades-agenda/proyectan-el-documental-desobediente failed" in (
            capsys.readouterr().err
        )

    def test_first_page_failure_propagates(self, monkeypatch):
        monkeypatch.setattr(auditorium, "REQUEST_DELAY", 0)

        def failing_page(page):
            raise requests.RequestException("boom")

        monkeypatch.setattr(auditorium, "_fetch_page", failing_page)

        with pytest.raises(requests.RequestException):
            auditorium.collect()

    def test_later_page_failure_keeps_collected_records(self, monkeypatch, capsys):
        calls = []
        page_0 = _load_html(LISTING_PAGE_0)

        def fetch_page(page):
            calls.append(page)
            if page == 0:
                return page_0
            raise requests.RequestException("boom")

        monkeypatch.setattr(auditorium, "REQUEST_DELAY", 0)
        monkeypatch.setattr(auditorium, "_fetch_page", fetch_page)
        monkeypatch.setattr(auditorium, "_fetch_detail", lambda path: None)

        records = auditorium.collect()

        assert calls == [0, 1]
        assert len(records) == 6
        assert "[auditorium] page 1 failed" in capsys.readouterr().err

    def test_max_pages_caps_pagination(self, monkeypatch):
        calls = []
        page_0 = _load_html(LISTING_PAGE_0)

        def fetch_page(page):
            calls.append(page)
            return page_0

        monkeypatch.setattr(auditorium, "REQUEST_DELAY", 0)
        monkeypatch.setattr(auditorium, "MAX_PAGES", 2)
        monkeypatch.setattr(auditorium, "_fetch_page", fetch_page)
        monkeypatch.setattr(auditorium, "_fetch_detail", lambda path: None)

        records = auditorium.collect()

        assert calls == [0, 1]
        assert len(records) == 12


class TestRequestContract:
    class FakeResponse:
        def __init__(self, text=""):
            self.text = text
            self.status_checked = False

        def raise_for_status(self):
            self.status_checked = True

    def test_listing_request_contract(self, monkeypatch):
        seen = {}
        response = self.FakeResponse(text=EMPTY_PAGE)

        def fake_get(url, params=None, headers=None, timeout=None):
            seen.update(url=url, params=params, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(auditorium.requests, "get", fake_get)

        html = auditorium._fetch_page(2)

        assert html == EMPTY_PAGE
        assert response.status_checked
        assert seen["url"] == "https://teatroauditorium.gba.gob.ar/programacion"
        assert seen["params"] == {"page": 2}
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30

    def test_detail_request_contract(self, monkeypatch):
        seen = {}
        path = "/actividades-agenda/despues-del-fuego-en-el-cafe-teatral"
        response = self.FakeResponse(text=_load_html("auditorium_detail_boleteria.html"))

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return response

        monkeypatch.setattr(auditorium.requests, "get", fake_get)

        detail = auditorium._fetch_detail(path)

        assert seen["url"] == f"{BASE}{path}"
        assert seen["headers"]["User-Agent"] == "cartelera-mdp-pipeline/0.2 (local research)"
        assert seen["timeout"] == 30
        assert detail == {"seller": None, "is_free": False}


class TestNormalize:
    @staticmethod
    def _events(records):
        return {event.source_event_id: event for event in auditorium.normalize(records)}

    def test_single_day_event(self):
        event = self._events(auditorium.parse_page(_load_html(LISTING_PAGE_0)))[
            "proyectan-el-documental-desobediente"
        ]

        assert event.source == "auditorium"
        assert event.title == "Proyectan el documental “Desobediente”"
        assert event.venue_name == "Teatro Auditorium"
        assert event.venue_raw == "Sala Roberto J. Payró"
        assert event.date_start == "2026-10-24"
        assert event.date_end == "2026-10-24"
        assert event.occurrences == ["2026-10-24"]
        assert event.recurrence_unknown is False
        assert event.time == "18:00"
        assert event.city == "Mar del Plata"
        assert event.raw_url == f"{BASE}/actividades-agenda/proyectan-el-documental-desobediente"
        assert event.image_url == (
            f"{BASE}/sites/default/files/styles/resumen_noticias/public/actividades/"
            "agenda-cartelera/2026/10/proyectan-el-documental-desobediente.jpg.webp?itok=MplSOvjW"
        )
        assert event.ticket_url is None
        assert event.price_min is None
        assert event.price_text is None
        assert event.currency is None

    def test_multi_function_day_uses_first_start_time(self):
        event = self._events(auditorium.parse_page(_load_html(LISTING_PAGE_0)))[
            "proyectan-la-vida-es-asi-en-el-ciclo-cine-arte"
        ]

        assert event.occurrences == ["2026-10-25"]
        assert event.date_start == "2026-10-25"
        assert event.date_end == "2026-10-25"
        assert event.time == "16:00"

    def test_multi_day_event_lists_every_date(self):
        event = self._events(auditorium.parse_page(_load_html(LISTING_PAGE_1)))[
            "el-auditorium-sera-sede-oficial-del-certamen-pre-cosquin-2027-0"
        ]

        assert event.occurrences == ["2026-10-30", "2026-10-31", "2026-11-01"]
        assert event.date_start == "2026-10-30"
        assert event.date_end == "2026-11-01"
        assert event.recurrence_unknown is False
        assert event.time == "16:30"

    def test_jorge_laureti_venue_mapping(self):
        event = self._events(auditorium.parse_page(_load_html(LISTING_PAGE_0)))[
            "amniotika404-y-rachet-en-el-ciclo-el-rock-buen-puerto"
        ]

        assert event.venue_name == "Teatro Auditorium Laureti Puerto"
        assert event.venue_raw == "Sala Jorge Laureti - Puerto"

    @pytest.mark.parametrize(
        ("sala", "venue_name", "venue_raw"),
        [
            ("Jorge Laureti - Puerto", "Teatro Auditorium Laureti Puerto", "Sala Jorge Laureti - Puerto"),
            (None, "Teatro Auditorium", "Teatro Auditorium"),
            ("", "Teatro Auditorium", "Teatro Auditorium"),
            ("Foyer", "Teatro Auditorium", "Foyer"),
            ("Astor Piazzolla", "Teatro Auditorium", "Sala Astor Piazzolla"),
        ],
    )
    def test_venue_mapping(self, sala, venue_name, venue_raw):
        event = auditorium.normalize([_record(sala=sala)])[0]

        assert event.venue_name == venue_name
        assert event.venue_raw == venue_raw

    @pytest.mark.parametrize(
        ("detail", "seller", "is_free"),
        [
            ({"seller": "Plateanet", "is_free": False}, "Plateanet", False),
            ({"seller": None, "is_free": True}, None, True),
            (None, None, None),
        ],
    )
    def test_detail_fields_flow_into_event(self, detail, seller, is_free):
        event = auditorium.normalize([_record(detail=detail)])[0]

        assert event.seller == seller
        assert event.is_free == is_free

    def test_event_without_datetimes_has_no_dates(self):
        event = auditorium.normalize([_record(datetimes=[])])[0]

        assert event.date_start is None
        assert event.date_end is None
        assert event.occurrences == []
        assert event.time is None
        assert event.recurrence_unknown is False
