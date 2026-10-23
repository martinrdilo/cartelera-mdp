"""Tests for the Teatro Colón collector (mardelplata.gob.ar/colonprogramacion).

The monthly page is malformed Drupal 7 HTML: the program lives in two
``div.well.span5`` columns and every visible line is a ``<p>`` nested inside a
wrapper ``<p>``. The fixture is the real October 2026 page (28 events); every
test works offline and monkeypatches requests, so the suite never uses the
network.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
import requests

from collectors import colon

FIXTURE = Path(__file__).parent / "fixtures" / "colon_programacion.html"


class FakeDate(date):
    """A date with a frozen today() so the year inference stays deterministic."""

    _today = date(2026, 10, 23)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(colon, "date", FakeDate)


@pytest.fixture(scope="module")
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def records(html):
    return colon.parse_page(html)


class FakeResponse:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True
        if self.error is not None:
            raise self.error


def _lines(*lines):
    """Wrap plain lines the same way the Drupal columns do."""
    body = "".join(f"<p>{line}</p>" for line in lines)
    return f'<html><body><div class="well span5"><p><div>{body}</div></p></div></body></html>'


def _record(**overrides):
    record = {
        "source": "colon",
        "title": "OBRA DE PRUEBA",
        "day": 1,
        "month": 10,
        "time": "20:30",
        "price_lines": [],
        "description": "",
        "raw_url": colon.LIST_URL,
    }
    record.update(overrides)
    return record


class TestConstants:
    def test_base_list_url_user_agent_and_source(self):
        assert colon.BASE == "https://www.mardelplata.gob.ar"
        assert colon.LIST_URL == "https://www.mardelplata.gob.ar/colonprogramacion"
        assert colon.USER_AGENT == "cartelera-mdp-pipeline/0.2 (local research)"
        assert colon.SOURCE == "colon"


class TestParsePage:
    def test_parses_every_event_of_the_october_page(self, records):
        assert len(records) == 28

    def test_first_record_has_month_day_time_title_prices_and_description(self, records):
        assert records[0] == {
            "source": "colon",
            "title": "CICLO ANUAL BALLET DE CÁMARA DE LA ESCUELA MUNICIPAL DE DANZAS NORMA FONTENLA",
            "day": 1,
            "month": 10,
            "time": "20:30",
            "price_lines": [
                "Entrada Gral: $10000",
                "Jubilados, Residentes y Estudiantes: $7500",
            ],
            "description": (
                "El Ballet de Cámara de la Escuela Municipal de Danzas Norma Fontenla "
                "realizará la tercera función de su Ciclo 2026 en el Teatro Municipal "
                "Colón. La velada contará con cuatro estrenos, con propuestas de danza "
                "clásica, neoclásica y contemporánea, y la participación de 30 bailarinas."
            ),
            "raw_url": colon.LIST_URL,
        }

    def test_free_record_keeps_its_entrada_line(self, records):
        record = next(record for record in records if record["day"] == 5)
        assert record["title"] == "CONCIERTO CENTENRIO DE LA BASE NAVAL MAR DEL PLATA"
        assert record["month"] == 10
        assert record["time"] == "20:00"
        assert record["price_lines"] == ["Entrada libre y gratuita por orden de llegada."]
        assert record["description"] == (
            "La Banda de Música del Comando del Area Naval Atlántico realizará un "
            "concierto en conmemoración al Centenario de la Base Naval Mar del Plata."
        )

    def test_last_record_is_the_last_day_of_the_month(self, records):
        record = records[-1]
        assert record["day"] == 31
        assert record["month"] == 10
        assert record["time"] == "20:00"
        assert record["title"] == "ORQUESTA MUNICIPAL DE TANGO"
        assert record["price_lines"] == [
            "Entrada general: $7000",
            "Jubilados, Residentes y Estudiantes: $5000",
        ]
        assert record["description"] == (
            "Programa a confirmar.\nDirector Titular: Mtro. Julio Davila"
        )

    def test_month_header_carries_over_to_the_second_column(self, records):
        # The second column has no month header of its own.
        assert {record["month"] for record in records} == {10}

    def test_multi_session_line_starts_a_record_with_its_first_time(self, records):
        # "Viernes 16 a las 19 y 21:30 hs": both functions share the date, so
        # the event is one row whose time is the first function.
        record = next(record for record in records if record["day"] == 16)
        assert record["time"] == "19:00"
        assert record["title"] == "CANDLELIGHT CONCERTS BY FEVER"
        assert (
            "Las entradas se adquieren ÚNICAMENTE a través de la página Web: "
            "www.feverup.com o por medio de la aplicación FEVER."
        ) in record["price_lines"]
        previous = next(record for record in records if record["day"] == 15)
        assert "CANDLELIGHT" not in previous["description"]

    def test_records_are_json_ready(self, records):
        assert set(records[0]) == {
            "source",
            "title",
            "day",
            "month",
            "time",
            "price_lines",
            "description",
            "raw_url",
        }
        assert json.loads(json.dumps(records)) == records

    def test_month_headers_update_the_current_month(self):
        page = _lines(
            "OCTUBRE",
            "Jueves 1 a las 20:30 hs",
            "OBRA UNO",
            "NOVIEMBRE",
            "Viernes 6 a las 21 hs",
            "OBRA DOS",
        )
        assert [(record["month"], record["day"]) for record in colon.parse_page(page)] == [
            (10, 1),
            (11, 6),
        ]

    def test_month_header_is_matched_case_insensitively(self):
        page = _lines("octubre", "Jueves 1 a las 20:30 hs", "OBRA UNO")
        assert colon.parse_page(page)[0]["month"] == 10

    def test_whitespace_is_collapsed_and_empty_lines_are_skipped(self):
        page = _lines(
            "OCTUBRE",
            "  Jueves   1   a las   20:30   hs  ",
            "  OBRA   CON   ESPACIOS  ",
            "&nbsp;",
            "Entrada   general:   $7000",
        )
        record = colon.parse_page(page)[0]
        assert record["title"] == "OBRA CON ESPACIOS"
        assert record["price_lines"] == ["Entrada general: $7000"]
        assert record["description"] == ""

    def test_no_month_header_leaves_month_empty(self):
        page = _lines("Sábado 3 a las 20 hs", "OBRA SIN MES")
        assert colon.parse_page(page) == [
            {
                "source": "colon",
                "title": "OBRA SIN MES",
                "day": 3,
                "month": None,
                "time": "20:00",
                "price_lines": [],
                "description": "",
                "raw_url": colon.LIST_URL,
            }
        ]


class TestParsePrice:
    def test_dotted_thousands(self):
        assert colon._parse_price("25.000") == 25000.0

    def test_dollar_sign_space_thousands_and_comma_decimals(self):
        assert colon._parse_price("$ 25.000,50") == 25000.5

    def test_plain_digits(self):
        assert colon._parse_price("7000") == 7000.0

    @pytest.mark.parametrize("raw", [None, "", "   ", "$", "libre", "consultar"])
    def test_invalid_input_returns_none(self, raw):
        assert colon._parse_price(raw) is None


class TestResolveDate:
    def test_same_year_when_the_date_is_within_the_window(self):
        assert colon._resolve_date(10, 15, date(2026, 10, 23)) == date(2026, 10, 15)

    def test_january_page_viewed_in_december_rolls_forward(self):
        assert colon._resolve_date(1, 10, date(2026, 12, 20)) == date(2027, 1, 10)

    def test_december_page_viewed_in_january_rolls_back(self):
        assert colon._resolve_date(12, 20, date(2027, 1, 10)) == date(2026, 12, 20)

    def test_exactly_180_days_in_the_past_stays_in_the_current_year(self):
        assert colon._resolve_date(1, 1, date(2026, 6, 30)) == date(2026, 1, 1)

    def test_181_days_in_the_past_rolls_to_the_next_year(self):
        assert colon._resolve_date(1, 1, date(2026, 7, 1)) == date(2027, 1, 1)

    def test_exactly_180_days_in_the_future_stays_in_the_current_year(self):
        assert colon._resolve_date(12, 31, date(2026, 7, 4)) == date(2026, 12, 31)

    def test_181_days_in_the_future_rolls_to_the_previous_year(self):
        assert colon._resolve_date(12, 31, date(2026, 7, 3)) == date(2025, 12, 31)

    @pytest.mark.parametrize(
        ("month", "day"),
        [(2, 30), (13, 1), (None, 5), (2, None), (2, 29)],
    )
    def test_invalid_dates_return_none(self, month, day):
        # 2/29 is invalid because the candidate year (2027) is not a leap year.
        assert colon._resolve_date(month, day, date(2027, 3, 1)) is None


class TestRequestContract:
    def test_fetch_page_gets_the_list_url_with_the_pipeline_user_agent(self, monkeypatch, html):
        calls = {}
        response = FakeResponse(text=html)

        def fake_get(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            return response

        monkeypatch.setattr(colon.requests, "get", fake_get)

        assert colon._fetch_page() == html
        assert calls["url"] == "https://www.mardelplata.gob.ar/colonprogramacion"
        assert calls["headers"] == {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"}
        assert calls["timeout"] == 30
        assert response.raise_for_status_called is True

    def test_fetch_page_raises_for_http_errors(self, monkeypatch):
        monkeypatch.setattr(
            colon.requests,
            "get",
            lambda url, **kwargs: FakeResponse(error=requests.HTTPError("500")),
        )

        with pytest.raises(requests.HTTPError):
            colon._fetch_page()

    def test_collect_makes_a_single_request_and_parses_the_page(self, monkeypatch, html):
        calls = []
        response = FakeResponse(text=html)

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return response

        monkeypatch.setattr(colon.requests, "get", fake_get)

        records = colon.collect()

        assert calls == [
            (
                "https://www.mardelplata.gob.ar/colonprogramacion",
                {
                    "headers": {"User-Agent": "cartelera-mdp-pipeline/0.2 (local research)"},
                    "timeout": 30,
                },
            )
        ]
        assert records == colon.parse_page(html)
        assert len(records) == 28

    def test_collect_propagates_network_failures(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(colon.requests, "get", fake_get)

        with pytest.raises(requests.ConnectionError):
            colon.collect()


class TestNormalize:
    def test_first_record_becomes_a_paid_event(self, records):
        record = records[0]
        event = colon.normalize([record])[0]

        assert event.source == "colon"
        assert event.source_event_id == (
            "2026-10-01-"
            + hashlib.sha1(record["title"].encode("utf-8")).hexdigest()[:10]
        )
        assert event.title == record["title"]
        assert event.venue_name == "Teatro Municipal Colón"
        assert event.venue_raw == "Teatro Municipal Colón"
        assert event.city == "Mar del Plata"
        assert event.date_start == "2026-10-01"
        assert event.date_end == "2026-10-01"
        assert event.occurrences == ["2026-10-01"]
        assert event.recurrence_unknown is False
        assert event.time == "20:30"
        assert event.price_min == 7500.0
        assert event.price_text == "Jubilados, Residentes y Estudiantes: $7500"
        assert event.is_free is False
        assert event.currency == "ARS"
        assert event.seller is None
        assert event.ticket_url is None
        assert event.image_url is None
        assert event.raw_url == colon.LIST_URL

    def test_price_min_is_the_cheapest_dollar_amount_of_every_line(self):
        record = _record(
            price_lines=["Entrada general: $10.000", "Estudiantes: $ 7.500,50"],
        )

        event = colon.normalize([record])[0]

        assert event.price_min == 7500.5
        assert event.price_text == "Estudiantes: $ 7.500,50"
        assert event.is_free is False
        assert event.currency == "ARS"

    def test_free_record_has_no_price_and_is_free(self, records):
        record = next(record for record in records if record["day"] == 5)

        event = colon.normalize([record])[0]

        assert event.price_min is None
        assert event.price_text is None
        assert event.is_free is True
        assert event.currency is None
        assert event.date_start == "2026-10-05"
        assert event.time == "20:00"

    def test_fever_only_event_gets_its_seller(self, records):
        record = next(record for record in records if record["day"] == 16)

        event = colon.normalize([record])[0]

        assert event.seller == "Fever"
        assert event.price_min is None
        assert event.is_free is None

    def test_record_without_price_or_free_hint_stays_unknown(self):
        record = _record(price_lines=["Consultar en boletería"])

        event = colon.normalize([record])[0]

        assert event.price_min is None
        assert event.price_text is None
        assert event.is_free is None
        assert event.currency is None

    def test_january_record_rolls_to_the_next_year(self):
        event = colon.normalize([_record(month=1, day=5)])[0]

        assert event.date_start == "2027-01-05"
        assert event.date_end == "2027-01-05"
        assert event.occurrences == ["2027-01-05"]
        assert event.source_event_id.startswith("2027-01-05-")

    def test_records_without_a_resolvable_date_are_skipped(self):
        assert colon.normalize([_record(month=None)]) == []
        assert colon.normalize([_record(month=2, day=31)]) == []

    def test_every_fixture_record_normalizes_in_document_order(self, records):
        events = colon.normalize(records)

        assert len(events) == 28
        assert [event.date_start for event in events] == [
            f"2026-10-{day:02d}"
            for day in [
                1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14, 15, 16, 17, 19, 21,
                22, 23, 24, 24, 25, 26, 27, 28, 29, 30, 31,
            ]
        ]
        for event in events:
            assert event.source == "colon"
            assert event.venue_name == "Teatro Municipal Colón"
            assert event.occurrences == [event.date_start]
            assert event.recurrence_unknown is False
            assert event.raw_url == colon.LIST_URL
