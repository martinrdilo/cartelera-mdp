"""Tests for the Venti collector: MDP filtering, UTC conversion and pagination."""

import copy
import json
from pathlib import Path

import pytest

from collectors import venti

FIXTURE = Path(__file__).parent / "fixtures" / "venti_events.json"


def load_payload():
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


def page_payload(events, total_pages=1, current_page=1):
    return {
        "status": "ok",
        "events": events,
        "totalItems": len(events),
        "totalPages": total_pages,
        "currentPage": current_page,
    }


def use_pages(monkeypatch, pages):
    """Install fake API pages; returns the list of requested page numbers."""
    calls = []

    def fake_fetch_page(page):
        calls.append(page)
        return copy.deepcopy(pages[page - 1])

    monkeypatch.setattr(venti, "_fetch_page", fake_fetch_page)
    monkeypatch.setattr(venti, "REQUEST_DELAY", 0)
    return calls


def collect_one_page(monkeypatch):
    use_pages(monkeypatch, [load_payload()])
    return venti.collect()


class TestCollectFilter:
    def test_coordinate_filter_excludes_non_mdp_event(self, monkeypatch):
        records = collect_one_page(monkeypatch)
        ids = [record["source_event_id"] for record in records]
        assert ids == ["11783", "11347", "11023"]
        assert "10546" not in ids


class TestNormalizeConversion:
    def test_utc_start_date_becomes_buenos_aires_local_date_and_time(self, monkeypatch):
        events = venti.normalize(collect_one_page(monkeypatch))
        quba = next(event for event in events if event.source_event_id == "11783")
        assert quba.date_start == "2026-10-22"
        assert quba.date_end == "2026-10-22"
        assert quba.occurrences == ["2026-10-22"]
        assert quba.time == "23:00"


class TestNormalizeFields:
    def test_ticket_url_seller_image_venue_occurrences_and_source_id(self, monkeypatch):
        records = collect_one_page(monkeypatch)
        # Raw records must stay JSON-ready for data/raw/<source>.json.
        json.dumps(records)
        event = venti.normalize(records)[2]

        assert event.source == "venti"
        assert event.source_event_id == "11023"
        assert event.title == "LA VIN - LOS TOTORA TOUR"
        assert event.ticket_url == "https://venti.live/evento/vinmusic-mdq-la-vin-tour"
        assert event.seller == "Venti"
        assert event.image_url == "https://images.venti.live/user-images/1788782986347-lg.jpg"
        assert event.venue_name == "Sheraton Mar del Plata Hotel"
        assert (
            event.venue_raw
            == "Sheraton Mar del Plata Hotel, Leandro N. Alem 4221, Mar del Plata"
        )
        assert event.occurrences == ["2026-10-24"]
        assert event.city == "Mar del Plata"
        assert event.raw_url == "https://api.venti.live/api/home/events?limit=100&page=1"
        assert event.is_free is None
        assert event.price_text is None
        assert event.price_min is None
        assert event.currency is None


class TestPagination:
    def test_uses_total_pages_and_dedupes_by_id(self, monkeypatch):
        fixture_events = load_payload()["events"]
        pages = [
            page_payload([fixture_events[0], fixture_events[1]], total_pages=2, current_page=1),
            page_payload([fixture_events[1], fixture_events[2]], total_pages=2, current_page=2),
        ]
        calls = use_pages(monkeypatch, pages)

        events = venti.normalize(venti.collect())

        assert calls == [1, 2]
        assert [event.source_event_id for event in events] == ["11783", "11347", "11023"]
