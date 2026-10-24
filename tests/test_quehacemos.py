"""Tests for the Qué Hacemos aggregator collector.

Discovery enumerates four-day province windows: each window payload already
carries `price`, `link`, `address` and `source`, so there is no per-event
detail request. Every request is served from the two real window payloads in
`tests/fixtures/` (388 and 312 province records); no test touches the network.
"""

import copy
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from collectors import quehacemos

FIXTURES = Path(__file__).resolve().parent / "fixtures"

NOV = json.loads((FIXTURES / "quehacemos_window_nov.json").read_text(encoding="utf-8"))
DEC = json.loads((FIXTURES / "quehacemos_window_dec.json").read_text(encoding="utf-8"))

# The fixtures span Nov 1-4 and Dec 4-7, so each anchors its own window grid.
NOV_TODAY = date(2026, 11, 1)
DEC_TODAY = date(2026, 12, 4)

MUSIC_TYPES = {"recital", "festival", "electronica"}
DROPPED_TYPES = {
    "teatro",
    "stand up",
    "cine",
    "deporte",
    "arte",
    "familia",
    "charla",
    "expo",
    "gastronomia",
    "fiesta",
}

# Kept records measured from each real payload: music types plus the `otro`
# events whose own `link` points at a music seller.
NOV_KEPT_IDS = {67490, 49607, 42956}
DEC_KEPT_IDS = {
    71195,
    49918,
    67283,
    32383,
    64562,
    43478,
    67360,  # recital
    53815,
    72131,  # electronica
    65925,  # festival
    73059,  # otro, Passline
}


def window_url(date_from, date_to):
    """The measured window URL, kept independent from the module on purpose."""
    return (
        "https://api.quehacemos.com.ar/api/v1/events/"
        "?province=Buenos%20Aires"
        f"&date_from={date_from}T00:00:00"
        f"&date_to={date_to}T00:00:00"
        "&limit=1000"
    )


def fix_today(monkeypatch, day):
    monkeypatch.setattr(quehacemos, "_today", lambda: day)


def use_api(monkeypatch, payloads=None, default=None, fail=()):
    """Serve window payloads by exact URL and log every request."""
    payloads = payloads or {}
    calls = []

    def fake_fetch_json(url):
        calls.append(url)
        if url in fail:
            raise ConnectionError(f"window unreachable: {url}")
        if url in payloads:
            return copy.deepcopy(payloads[url])
        if default is None:
            raise AssertionError(f"unexpected request: {url}")
        return copy.deepcopy(default)

    monkeypatch.setattr(quehacemos, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(quehacemos, "REQUEST_DELAY", 0)
    return calls


def window_records(count, first_id, city="Mar del Plata", event_type="recital"):
    """Return `count` synthetic records on the real API shape."""
    template = next(r for r in NOV if r["city"] == "Mar del Plata")
    records = []
    for index in range(count):
        record = copy.deepcopy(template)
        record.update(id=first_id + index, city=city, event_type=event_type)
        records.append(record)
    return records


def collected(monkeypatch, payload, today):
    """Collect a run whose first window (anchored at `today`) is `payload`."""
    fix_today(monkeypatch, today)
    url = window_url(today.isoformat(), (today + timedelta(days=4)).isoformat())
    calls = use_api(monkeypatch, {url: payload}, default=[])
    return quehacemos.collect(), calls


def normalized(monkeypatch, payload, today):
    """Collect and normalize, keyed by `source_event_id`."""
    records, _ = collected(monkeypatch, payload, today)
    return {event.source_event_id: event for event in quehacemos.normalize(records)}


class TestWindowEnumeration:
    def test_four_day_windows_cover_the_horizon_and_stop_at_it(self, monkeypatch):
        fix_today(monkeypatch, NOV_TODAY)
        calls = use_api(monkeypatch, default=[])

        assert quehacemos.collect() == []

        # 180 days / 4 = 45 windows; the last one ends exactly on the horizon.
        assert len(calls) == 45
        assert calls[0] == window_url("2026-11-01", "2026-11-05")
        assert calls[1] == window_url("2026-11-05", "2026-11-09")
        assert calls[-1] == window_url("2027-04-26", "2027-04-30")
        assert not any("date_from=2027-04-30" in url for url in calls)

    def test_no_request_targets_a_single_event(self, monkeypatch):
        fix_today(monkeypatch, NOV_TODAY)
        calls = use_api(monkeypatch, default=[])

        quehacemos.collect()

        assert all(url.startswith(quehacemos.API_BASE + "/events/?") for url in calls)
        assert not any(re.search(r"/events/\d+$", url) for url in calls)


class TestTruncation:
    def test_a_full_window_splits_and_recurses_down_to_single_days(self, monkeypatch):
        fix_today(monkeypatch, NOV_TODAY)
        payloads = {
            window_url("2026-11-01", "2026-11-05"): window_records(1000, 100000),
            window_url("2026-11-01", "2026-11-03"): window_records(1000, 200000),
            window_url("2026-11-03", "2026-11-05"): window_records(1000, 300000),
            window_url("2026-11-01", "2026-11-02"): window_records(2, 1),
            window_url("2026-11-02", "2026-11-03"): window_records(2, 3),
            window_url("2026-11-03", "2026-11-04"): window_records(2, 5),
            window_url("2026-11-04", "2026-11-05"): window_records(2, 7),
        }
        calls = use_api(monkeypatch, payloads, default=[])

        records = quehacemos.collect()

        assert calls[:7] == [
            window_url("2026-11-01", "2026-11-05"),
            window_url("2026-11-01", "2026-11-03"),
            window_url("2026-11-01", "2026-11-02"),
            window_url("2026-11-02", "2026-11-03"),
            window_url("2026-11-03", "2026-11-05"),
            window_url("2026-11-03", "2026-11-04"),
            window_url("2026-11-04", "2026-11-05"),
        ]
        # The remaining 44 plain windows of the 180-day horizon follow.
        assert len(calls) == 51
        # The truncated payloads are refetched in halves and never emitted.
        assert [record["id"] for record in records] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_a_single_day_at_the_cap_is_kept_and_logged(self, monkeypatch, capsys):
        fix_today(monkeypatch, NOV_TODAY)
        monkeypatch.setattr(quehacemos, "WINDOW_DAYS", 1)
        monkeypatch.setattr(quehacemos, "HORIZON_DAYS", 1)
        calls = use_api(
            monkeypatch,
            {window_url("2026-11-01", "2026-11-02"): window_records(1000, 500)},
            default=[],
        )

        records = quehacemos.collect()

        assert calls == [window_url("2026-11-01", "2026-11-02")]
        assert len(records) == 1000
        err = capsys.readouterr().err
        assert "2026-11-01" in err
        assert "still returns 1000" in err


class TestDedupe:
    def test_cross_window_duplicate_id_is_emitted_once(self, monkeypatch):
        fix_today(monkeypatch, NOV_TODAY)
        shared = next(record for record in NOV if record["id"] == 49607)
        later = copy.deepcopy(shared)
        later["title"] = "duplicate copy"
        payloads = {
            window_url("2026-11-01", "2026-11-05"): [copy.deepcopy(shared)],
            window_url("2026-11-05", "2026-11-09"): [later],
        }
        use_api(monkeypatch, payloads, default=[])

        records = quehacemos.collect()

        assert [record["id"] for record in records] == [49607]
        assert records[0]["title"] == shared["title"]


class TestCityAndProductFilters:
    def test_city_filter_keeps_mar_del_plata_only(self, monkeypatch):
        records, _ = collected(monkeypatch, NOV, NOV_TODAY)

        mdp_ids = {record["id"] for record in NOV if record["city"] == "Mar del Plata"}
        kept = {record["id"] for record in records}
        assert kept <= mdp_ids
        assert kept == NOV_KEPT_IDS

    def test_product_filter_keeps_music_and_whitelisted_otro(self, monkeypatch):
        records, _ = collected(monkeypatch, DEC, DEC_TODAY)

        kept = {record["id"] for record in records}
        assert kept == DEC_KEPT_IDS
        assert {record["event_type"] for record in records} <= MUSIC_TYPES | {"otro"}
        # The only kept `otro` is the Passline one; the MDP Plateanet and
        # Articket `otro` events stay out even though their details are in the
        # window payload (the whitelist reads the record's own link).
        assert {record["id"] for record in records if record["event_type"] == "otro"} == {
            73059
        }
        assert {55934, 66658, 69538}.isdisjoint(kept)
        dropped = {
            record["id"] for record in DEC if record["event_type"] in DROPPED_TYPES
        }
        assert 0 < len(dropped)
        assert dropped.isdisjoint(kept)


class TestRawRecords:
    def test_flat_record_keeps_api_fields_and_overrides_the_upstream_source(
        self, monkeypatch
    ):
        records, _ = collected(monkeypatch, DEC, DEC_TODAY)

        raw = next(record for record in records if record["id"] == 73059)

        # The API said `passline.com`; the collector owns the source name.
        assert raw["source"] == "quehacemos"
        assert raw["link"] == "https://www.passline.com/eventos/supernebula"
        assert "price" in raw and "address" in raw and "image_url" in raw
        assert "listing" not in raw and "detail" not in raw
        # Raw records are written to data/raw/<source>.json.
        json.dumps(records)


class TestNormalize:
    def test_plateanet_seller_becomes_ticket_url(self, monkeypatch):
        event = normalized(monkeypatch, DEC, DEC_TODAY)["32383"]

        link = (
            "https://www.plateanet.com/obra/34548"
            "?obra=LUCIANO-PEREYRA---TOUR-TE-SIGO-AMANDO"
        )
        assert event.source == "quehacemos"
        assert event.source_event_id == "32383"
        assert event.title == "LUCIANO PEREYRA - TOUR TE SIGO AMANDO"
        assert event.seller == "Plateanet"
        assert event.ticket_url == link
        assert event.raw_url == link
        assert event.price_min == 70000.0
        assert event.is_free is False
        assert event.currency == "ARS"
        assert event.price_text is None
        assert event.venue_name == "Roxy-Radio City"
        assert (
            event.venue_raw
            == "Roxy-Radio City, San Luis 1752 - Mar del Plata - Buenos Aires"
        )
        assert (
            event.image_url
            == "https://www.plateanet.com/img/imagenes/1440x500/"
            "LUCIANO-PEREYRA---TOUR-TE-SIGO-AMANDO.jpg"
        )
        assert event.city == "Mar del Plata"

    def test_bandsintown_link_is_an_info_page_not_a_ticket(self, monkeypatch):
        event = normalized(monkeypatch, DEC, DEC_TODAY)["71195"]

        link = (
            "https://www.bandsintown.com/e/109045198"
            "-joystick-at-chauvin-centro-de-creacion"
        )
        assert event.seller is None
        assert event.ticket_url is None
        assert event.raw_url == link
        assert event.price_min is None
        assert event.is_free is None
        assert event.currency is None
        assert event.venue_name == "Chauvin Centro de creación"
        assert event.venue_raw == "Chauvin Centro de creación, San Luis 2849"

    def test_price_zero_is_free(self, monkeypatch):
        record = copy.deepcopy(next(r for r in DEC if r["id"] == 32383))
        record["price"] = 0

        event = normalized(monkeypatch, [record], DEC_TODAY)["32383"]

        assert event.price_min == 0.0
        assert event.is_free is True
        assert event.currency == "ARS"

    def test_dates_occurrences_and_no_invented_time(self, monkeypatch):
        # 2026-11-04T21:00:00 in the payload, but the source publishes no
        # reliable show time: `time` must stay None.
        event = normalized(monkeypatch, NOV, NOV_TODAY)["42956"]

        assert event.date_start == "2026-11-04"
        assert event.date_end == "2026-11-04"
        assert event.occurrences == ["2026-11-04"]
        assert event.recurrence_unknown is False
        assert event.time is None

    def test_venue_without_address_falls_back_to_the_venue_name(self, monkeypatch):
        event = normalized(monkeypatch, DEC, DEC_TODAY)["73059"]

        assert event.venue_name == "GLOW"
        assert event.venue_raw == "GLOW"


class TestWindowFailure:
    def test_a_failing_window_raises_instead_of_dropping_dates(self, monkeypatch):
        fix_today(monkeypatch, NOV_TODAY)
        first = window_url("2026-11-01", "2026-11-05")
        failing = window_url("2026-11-05", "2026-11-09")
        calls = use_api(monkeypatch, {first: []}, default=[], fail={failing})

        with pytest.raises(ConnectionError):
            quehacemos.collect()

        assert calls == [first, failing]

    def test_unexpected_window_payload_raises(self, monkeypatch):
        fix_today(monkeypatch, NOV_TODAY)
        use_api(monkeypatch, default={"error": "boom"})

        with pytest.raises(ValueError):
            quehacemos.collect()
