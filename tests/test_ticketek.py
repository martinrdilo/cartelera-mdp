"""Tests for the Ticketek collector (search JSON + per-show node JSON)."""

import json
from pathlib import Path

import pytest

from collectors import ticketek

FIXTURES = Path(__file__).parent / "fixtures"
USER_AGENT = "cartelera-mdp-pipeline/0.2 (local research)"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def search_payload(with_abel=False):
    payload = load_fixture("ticketek_search.json")
    if with_abel:
        payload["resultados"].append(
            {
                "id": "27661",
                "titulo": "Abel Pintos",
                "url": "abel-pintos",
                "imagen": "//prod-cms-static.ticketek.com.ar/abel.png",
                "imagenHorizontal": "//prod-cms-static.ticketek.com.ar/abel-wide.png",
                "shows": [
                    {
                        "estado": "buy",
                        "id": 27662,
                        "showcode": "ABELP26TT",
                        "mobile": False,
                        "lugar": "Mar del Plata",
                        "venue": "Teatro Tronador",
                    }
                ],
                "date": "",
            }
        )
    return payload


def node_fixtures():
    return {
        "hairspray--teatro-tronador": load_fixture("ticketek_node_hairspray.json"),
        "dillom--bendu-arena": load_fixture("ticketek_node_dillom.json"),
        "abel-pintos--teatro-tronador": load_fixture("ticketek_node_abel.json"),
    }


@pytest.fixture
def ticketek_offline(monkeypatch):
    """Replace network calls with fixture responses and record node paths."""
    state = {
        "search": search_payload(),
        "nodes": node_fixtures(),
        "failures": set(),
        "paths": [],
    }
    monkeypatch.setattr(ticketek, "REQUEST_DELAY", 0)

    def fake_search():
        return state["search"]

    def fake_node(path):
        state["paths"].append(path)
        if path in state["failures"]:
            raise RuntimeError(f"node down: {path}")
        return state["nodes"][path]

    monkeypatch.setattr(ticketek, "_fetch_search", fake_search)
    monkeypatch.setattr(ticketek, "_fetch_node", fake_node)
    return state


class TestFetch:
    def test_search_uses_the_public_endpoint_and_user_agent(self, monkeypatch):
        seen = {}

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"resultados": []}

        def fake_get(url, headers=None, timeout=None):
            seen["url"] = url
            seen["headers"] = headers
            seen["timeout"] = timeout
            return Response()

        monkeypatch.setattr(ticketek.requests, "get", fake_get)
        assert ticketek._fetch_search() == {"resultados": []}
        assert seen["url"] == "https://prod-cms-search.ticketek.com.ar/api/1.1/search/mar%20del%20plata"
        assert seen["headers"] == {"User-Agent": USER_AGENT}
        assert seen["timeout"] == 30

    def test_fetch_node_encodes_the_node_path_query(self, monkeypatch):
        seen = {}

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"title": "Abel Pintos"}

        def fake_get(url, headers=None, timeout=None):
            seen["url"] = url
            seen["headers"] = headers
            return Response()

        monkeypatch.setattr(ticketek.requests, "get", fake_get)
        assert ticketek._fetch_node("abel-pintos--teatro-tronador") == {"title": "Abel Pintos"}
        assert seen["url"] == (
            "https://prod-cms-api.ticketek.com.ar/api/1.0/"
            "node%3Fpath%3Dabel-pintos--teatro-tronador"
        )
        assert seen["headers"] == {"User-Agent": USER_AGENT}


class TestNodePath:
    def test_slash_url_is_flattened_with_double_dash(self):
        assert ticketek._node_path("dillom/bendu-arena", "Bendu Arena") == "dillom--bendu-arena"

    def test_plain_url_gets_the_venue_slug(self):
        assert (
            ticketek._node_path("abel-pintos", "Teatro Tronador")
            == "abel-pintos--teatro-tronador"
        )

    def test_venue_slug_is_lowercase_and_accent_stripped(self):
        assert ticketek._node_path("artista", "Teatro Trónador") == "artista--teatro-tronador"


class TestCollect:
    def test_keeps_only_mar_del_plata_shows(self, ticketek_offline):
        records = ticketek.collect()
        assert [record["show"]["showcode"] for record in records] == ["HAIRS26TT", "DILLOM27MDQ"]
        assert ticketek_offline["paths"] == [
            "hairspray--teatro-tronador",
            "dillom--bendu-arena",
        ]

    def test_one_node_request_per_unique_path(self, ticketek_offline):
        ticketek_offline["search"] = search_payload(with_abel=True)
        records = ticketek.collect()
        assert [record["show"]["showcode"] for record in records] == [
            "HAIRS26TT",
            "DILLOM27MDQ",
            "ABELP26TT",
        ]
        assert len(ticketek_offline["paths"]) == 3
        assert len(set(ticketek_offline["paths"])) == 3

    def test_shows_sharing_a_node_reuse_the_cached_fetch(self, ticketek_offline):
        shows = ticketek_offline["search"]["resultados"][0]["shows"]
        shows.append(
            {
                "estado": "buy",
                "id": 27619,
                "showcode": "HAIRS26TT2",
                "mobile": False,
                "lugar": "Mar del Plata",
                "venue": "Teatro Tronador",
            }
        )
        records = ticketek.collect()
        assert [record["show"]["showcode"] for record in records] == [
            "HAIRS26TT",
            "HAIRS26TT2",
            "DILLOM27MDQ",
        ]
        assert ticketek_offline["paths"] == [
            "hairspray--teatro-tronador",
            "dillom--bendu-arena",
        ]

    def test_node_failure_skips_only_that_show(self, ticketek_offline, capsys):
        ticketek_offline["search"] = search_payload(with_abel=True)
        ticketek_offline["failures"].add("abel-pintos--teatro-tronador")
        records = ticketek.collect()
        assert [record["show"]["showcode"] for record in records] == ["HAIRS26TT", "DILLOM27MDQ"]
        assert "abel-pintos--teatro-tronador" in capsys.readouterr().err


class TestNormalize:
    def test_dillom_fields(self, ticketek_offline):
        events = ticketek.normalize(ticketek.collect())
        dillom = next(event for event in events if event.source_event_id == "DILLOM27MDQ")
        assert dillom.source == "ticketek"
        assert dillom.seller == "Ticketek"
        assert dillom.title == "Dillom"
        assert dillom.venue_name == "Bendu Arena"
        assert dillom.venue_raw == "Bendu Arena, Av. Juan B. Justo y Av. de los Trabajadores"
        assert dillom.date_start == "2027-01-30"
        assert dillom.date_end == "2027-01-30"
        assert dillom.occurrences == ["2027-01-30"]
        assert dillom.time == "21:00"
        assert dillom.price_min == 69000
        assert dillom.price_text == "Desde $69000"
        assert dillom.currency == "ARS"
        assert dillom.is_free is False
        assert dillom.ticket_url == "https://www.ticketek.com.ar/dillom/bendu-arena"
        assert dillom.raw_url == "https://www.ticketek.com.ar/dillom/bendu-arena"
        assert dillom.image_url == (
            "https://prod-cms-static.ticketek.com.ar/sites/default/files/styles/"
            "artists_list_featured/public/images/show-header/dillom_s27.png"
        )
        assert dillom.city == "Mar del Plata"

    def test_abel_two_structured_dates_become_two_occurrences(self, ticketek_offline):
        ticketek_offline["search"] = search_payload(with_abel=True)
        events = ticketek.normalize(ticketek.collect())
        abel = next(event for event in events if event.source_event_id == "ABELP26TT")
        assert abel.occurrences == ["2026-11-07", "2026-11-08"]
        assert abel.date_start == "2026-11-07"
        assert abel.date_end == "2026-11-08"
        assert abel.price_text == "Desde $92000"

    def test_price_min_uses_the_cheapest_offer_and_integer_text(self, ticketek_offline):
        node = ticketek_offline["nodes"]["dillom--bendu-arena"]
        node["google_structured_data"].append(
            {
                "name": "Dillom",
                "startDate": "2027-01-31T21:00:00-03:00",
                "endDate": "2027-01-31T21:00:00-03:00",
                "location": {
                    "name": "Bendu Arena",
                    "address": {"streetAddress": "Av. Juan B. Justo y Av. de los Trabajadores"},
                },
                "offers": {
                    "url": "https://www.ticketek.com.ar/dillom/bendu-arena",
                    "price": "50000",
                    "priceCurrency": "ARS",
                },
                "image": "https://prod-cms-static.ticketek.com.ar/dillom-node.png",
            }
        )
        events = ticketek.normalize(ticketek.collect())
        dillom = next(event for event in events if event.source_event_id == "DILLOM27MDQ")
        assert dillom.price_min == 50000
        assert dillom.price_text == "Desde $50000"
        assert dillom.occurrences == ["2027-01-30", "2027-01-31"]

    def test_missing_price_leaves_free_unknown(self, ticketek_offline):
        node = ticketek_offline["nodes"]["dillom--bendu-arena"]
        del node["google_structured_data"][0]["offers"]
        events = ticketek.normalize(ticketek.collect())
        dillom = next(event for event in events if event.source_event_id == "DILLOM27MDQ")
        assert dillom.price_min is None
        assert dillom.price_text is None
        assert dillom.currency == "ARS"
        assert dillom.is_free is None

    def test_zero_price_marks_the_event_as_free(self, ticketek_offline):
        node = ticketek_offline["nodes"]["dillom--bendu-arena"]
        node["google_structured_data"][0]["offers"]["price"] = "0"
        events = ticketek.normalize(ticketek.collect())
        dillom = next(event for event in events if event.source_event_id == "DILLOM27MDQ")
        assert dillom.price_min == 0
        assert dillom.price_text == "Desde $0"
        assert dillom.is_free is True

    def test_image_falls_back_to_the_node_when_the_search_has_none(self, ticketek_offline):
        for result in ticketek_offline["search"]["resultados"]:
            if result["url"] == "dillom/bendu-arena":
                del result["imagenHorizontal"]
                del result["imagen"]
        events = ticketek.normalize(ticketek.collect())
        dillom = next(event for event in events if event.source_event_id == "DILLOM27MDQ")
        assert dillom.image_url == (
            "https://prod-cms-static.ticketek.com.ar/sites/default/files/images/artist/dillom_a27.png"
        )

    def test_record_without_structured_data_is_skipped(self, ticketek_offline):
        ticketek_offline["nodes"]["dillom--bendu-arena"] = {
            "title": "Dillom",
            "showcode": "DILLOM27MDQ",
        }
        events = ticketek.normalize(ticketek.collect())
        assert [event.source_event_id for event in events] == ["HAIRS26TT"]

    def test_record_without_a_valid_date_is_skipped(self, ticketek_offline):
        node = ticketek_offline["nodes"]["dillom--bendu-arena"]
        node["google_structured_data"][0]["startDate"] = "sin-fecha"
        events = ticketek.normalize(ticketek.collect())
        assert [event.source_event_id for event in events] == ["HAIRS26TT"]
