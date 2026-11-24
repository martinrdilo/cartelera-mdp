"""Tests for the static site generator: windows, merge rule, prices, build.

The integration test builds from the committed data/ snapshot (pipeline run
2026-10-13) with --today 2026-10-14, so the expected counts are fixed.
"""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

import build_site

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


def _anchor_today() -> date:
    """The next Thursday with events, so the weekend layout assertions hold.

    The snapshot is refreshed from live sources, so a hardcoded date goes
    stale within days. Anchoring on a Thursday keeps the "Finde" view at four
    day tabs no matter which corpus is committed.
    """
    today = date.today()
    try:
        events, _, _ = build_site.collect_site_events(DATA_DIR, today)
    except Exception:  # missing or unreadable snapshot
        return today
    for value in sorted({day for event in events for day in event["dates"]}):
        candidate = date.fromisoformat(value)
        if candidate >= today and candidate.weekday() == 3:
            return candidate
    return today


SNAPSHOT_TODAY = date(2026, 10, 14)
# Integration builds use the committed snapshot, anchored on a real Thursday.
BUILD_TODAY = _anchor_today()
# The ficha asserted by the ticket-link test is the 2026-11-20 AN ESPIL show,
# so both build dates are pinned inside that event's lifetime: BUILD_TODAY
# follows the calendar and drops the row once the show has passed, which made
# that test fail for a reason unrelated to the link.
TICKET_TODAYS = (date(2026, 11, 10), date(2026, 11, 20))
JSON_LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.DOTALL)
DATA_RE = re.compile(r'<script id="events-data" type="application/json">(.*?)</script>', re.DOTALL)
COLON_PROGRAM_URL = "https://www.mardelplata.gob.ar/colonprogramacion"


def make_member(source, **overrides):
    """One normalized event dict as it comes out of the pipeline."""
    fields = dict(
        source=source,
        source_event_id=f"{source}-1",
        title=f"Evento {source}",
        venue_name="Club TRI",
        venue_raw="Club TRI, 20 de Septiembre 2650",
        date_start="2026-10-17",
        date_end="2026-10-17",
        occurrences=["2026-10-17"],
        recurrence_unknown=False,
        multi_date_incomplete=False,
        time="21:00",
        is_free=False,
        price_text=None,
        price_min=None,
        currency="ARS",
        ticket_url=None,
        seller=None,
        image_url=None,
        city="Mar del Plata",
        raw_url=None,
        collected_at="2026-10-14T00:14:10+00:00",
    )
    fields.update(overrides)
    return fields


def empty_index():
    return build_site.venue_index([])


class TestWeekendWindow:
    """Thursday..Sunday of the current week, or of the next one before Thursday."""

    CASES = [
        # (today, expected start, expected end)
        (date(2026, 10, 12), date(2026, 10, 15), date(2026, 10, 18)),  # Monday -> next weekend
        (date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 18)),  # Tuesday -> next weekend
        (date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 18)),  # Wednesday -> next weekend
        (date(2026, 10, 15), date(2026, 10, 15), date(2026, 10, 18)),  # Thursday -> today..Sunday
        (date(2026, 10, 16), date(2026, 10, 16), date(2026, 10, 18)),  # Friday -> today..Sunday
        (date(2026, 10, 17), date(2026, 10, 17), date(2026, 10, 18)),  # Saturday -> today..Sunday
        (date(2026, 10, 18), date(2026, 10, 18), date(2026, 10, 18)),  # Sunday -> Sunday only
    ]

    def test_every_weekday(self):
        for today, start, end in self.CASES:
            assert build_site.weekend_window(today) == (start, end), today.isoformat()

    def test_window_is_four_days_at_most(self):
        for today, start, end in self.CASES:
            assert 0 <= (end - start).days <= 3

    def test_window_never_starts_before_today(self):
        for today, start, _ in self.CASES:
            assert start >= today

    def test_next_weekend_keeps_saturday_on_sunday(self):
        # weekend_window clips Sunday to Sunday only; the next weekend must
        # still include the following Saturday.
        assert build_site.next_weekend_window(date(2026, 10, 18)) == (
            date(2026, 10, 24),
            date(2026, 10, 25),
        )
        assert build_site.next_weekend_window(date(2026, 10, 25)) == (
            date(2026, 10, 31),
            date(2026, 11, 1),
        )

    def test_next_weekend_on_other_days_is_the_following_window(self):
        assert build_site.next_weekend_window(date(2026, 10, 17)) == (
            date(2026, 10, 24),
            date(2026, 10, 25),
        )
        assert build_site.next_weekend_window(date(2026, 10, 22)) == (
            date(2026, 10, 29),
            date(2026, 11, 1),
        )


class TestWindowBounds:
    def test_seven_days_window(self):
        assert build_site.window_bounds("7days", SNAPSHOT_TODAY) == (
            date(2026, 10, 14),
            date(2026, 10, 20),
        )

    def test_all_is_unbounded(self):
        assert build_site.window_bounds("all", SNAPSHOT_TODAY) == (None, None)

    def test_unknown_window_raises(self):
        try:
            build_site.window_bounds("tomorrow", SNAPSHOT_TODAY)
        except ValueError:
            return
        raise AssertionError("unknown window must raise ValueError")

    def test_matches_window_edges(self):
        today = SNAPSHOT_TODAY
        assert build_site.matches_window(["2026-10-14"], "7days", today)
        assert build_site.matches_window(["2026-10-20"], "7days", today)
        assert not build_site.matches_window(["2026-10-21"], "7days", today)
        assert build_site.matches_window(["2026-10-15"], "weekend", today)
        assert not build_site.matches_window(["2026-10-22"], "weekend", today)
        assert build_site.matches_window(["2027-04-03"], "all", today)


class TestAddMonths:
    """R2-002: a month shift clamps to the target month's last day.

    The old branch answered the 28th for every invalid day, so 31 May + 1
    landed on 28 June instead of 30 June and the ±12-month horizon came out
    three days short whenever the build date was a month-end.
    """

    @pytest.mark.parametrize(
        ("start", "months", "expected"),
        (
            (date(2026, 5, 31), 1, date(2026, 6, 30)),  # June has 30 days
            (date(2026, 3, 31), 1, date(2026, 4, 30)),  # April has 30 days
            (date(2026, 1, 31), 1, date(2026, 2, 28)),  # non-leap February
            (date(2028, 2, 29), 12, date(2029, 2, 28)),  # leap day, non-leap target
            (date(2026, 12, 31), 1, date(2027, 1, 31)),  # January keeps the 31st
            (date(2026, 5, 15), 1, date(2026, 6, 15)),  # a valid day never moves
            (date(2026, 5, 31), -1, date(2026, 4, 30)),  # backwards past a short month
            (date(2026, 3, 31), -3, date(2025, 12, 31)),  # backwards across a year
        ),
    )
    def test_month_shift_clamps_to_the_target_months_last_day(self, start, months, expected):
        assert build_site.add_months(start, months) == expected


class TestBuildHorizon:
    """Events outside ±12 months of the build date never reach the site."""

    def test_bounds_are_twelve_months_each_way(self):
        assert build_site.horizon_bounds(SNAPSHOT_TODAY) == (
            date(2025, 10, 14),
            date(2027, 10, 14),
        )

    def test_bounds_clamp_february_29(self):
        assert build_site.horizon_bounds(date(2028, 2, 29)) == (
            date(2027, 2, 28),
            date(2029, 2, 28),
        )

    def test_a_month_end_build_date_does_not_shorten_the_horizon(self):
        # add_months(2026-05-31, 12) is 2027-05-31; clamping to the 28th
        # silently dropped the last three days of the year-long window.
        assert build_site.add_months(date(2026, 5, 31), 12) == date(2027, 5, 31)
        assert build_site.horizon_bounds(date(2026, 5, 31)) == (
            date(2025, 5, 31),
            date(2027, 5, 31),
        )
        assert build_site.in_build_horizon(["2027-05-31"], date(2026, 5, 31))

    def test_both_edges_are_inside_the_horizon(self):
        assert build_site.in_build_horizon(["2025-10-14"], SNAPSHOT_TODAY)
        assert build_site.in_build_horizon(["2027-10-14"], SNAPSHOT_TODAY)
        assert not build_site.in_build_horizon(["2027-10-15"], SNAPSHOT_TODAY)
        assert not build_site.in_build_horizon(["2029-01-29"], SNAPSHOT_TODAY)

    def test_any_occurrence_inside_the_horizon_keeps_the_event(self):
        assert build_site.in_build_horizon(["2026-10-17", "2029-01-29"], SNAPSHOT_TODAY)

    def test_event_without_dates_never_qualifies(self):
        assert not build_site.in_build_horizon([], SNAPSHOT_TODAY)

    def test_build_drops_the_events_beyond_the_horizon(self, tmp_path):
        # 2029-01-29 (municipal) and 2029-09-12 (punto) are far past ±12 months.
        today = date(2026, 11, 21)
        stats = build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=today)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert "Recital de Violin" not in html
        assert "2029-01-29" not in html
        assert "Los Tabaleros" not in html
        events, _, _ = build_site.collect_site_events(DATA_DIR, today)
        assert len(events) == stats["upcoming"]

    def test_near_events_survive_the_horizon(self):
        today = date(2026, 11, 21)
        events, _, _ = build_site.collect_site_events(DATA_DIR, today)
        titles = [event["title"] for event in events]
        assert "19º Encuentro Internacional de Coros Mardelcanto 2026" in titles


class TestPriceFormatting:
    def test_integer_amount_uses_thousands_separator(self):
        assert build_site.format_price(12000) == "$12.000"

    def test_decimal_amount_uses_comma(self):
        assert build_site.format_price(12500.5) == "$12.500,50"

    def test_none_amount(self):
        assert build_site.format_price(None) is None

    def test_clean_strips_ticketer_mentions(self):
        assert build_site.clean_price_text("$12000, en venta en articket.com.ar") == "$12.000"

    def test_clean_keeps_desde_qualifier(self):
        assert build_site.clean_price_text("Desde $14000; en venta en www.articket.com.ar") == "Desde $14.000"

    def test_free_text_becomes_gratis(self):
        assert build_site.clean_price_text("Libre y gratuita") == "Gratis"

    def test_placeholder_has_no_price(self):
        assert build_site.clean_price_text("Comprar") is None
        assert build_site.clean_price_text(None) is None

    def test_plain_note_survives_without_urls(self):
        assert build_site.clean_price_text("Sólo en puerta") == "Sólo en puerta"

    def test_label_prefers_free(self):
        event = {"is_free": True, "price_min": 12000, "price_text": "$12000"}
        assert build_site.price_label(event) == "Gratis"

    def test_label_prefers_price_min(self):
        event = {"is_free": False, "price_min": 12000, "price_text": "$12000, en venta en articket.com.ar"}
        assert build_site.price_label(event) == "$12.000"

    def test_label_keeps_desde_with_price_min(self):
        event = {"is_free": False, "price_min": 14000, "price_text": "Desde $14000; en venta en articket.com.ar"}
        assert build_site.price_label(event) == "Desde $14.000"

    def test_label_falls_back_to_text(self):
        event = {"is_free": False, "price_min": None, "price_text": "$5000 más una consumición obligatoria"}
        assert build_site.price_label(event) == "$5.000"

    def test_label_without_price_is_none(self):
        event = {"is_free": False, "price_min": None, "price_text": "Comprar"}
        assert build_site.price_label(event) is None

    def test_label_ignores_a_sale_note_without_a_price(self):
        event = {"is_free": False, "price_min": None, "price_text": "en venta desde App. Bombo"}
        assert build_site.price_label(event) is None

    def test_label_falls_back_to_a_lowercase_desde_price(self):
        event = {"is_free": False, "price_min": None, "price_text": "desde $12000"}
        assert build_site.price_label(event) == "Desde $12.000"

    def test_sale_name_reads_boleteria_and_en_puerta_notes(self):
        assert build_site.sale_label(
            {"seller": None, "ticket_url": None, "price_text": "En boletería"}
        ) == "En boletería"
        assert build_site.sale_label(
            {"seller": None, "ticket_url": None, "price_text": "Sólo en puerta"}
        ) == "En puerta"


class TestMergeRule:
    """Seller members win event fields; municipal wins the address; dates union."""

    def cluster(self):
        return [
            make_member(
                "municipal",
                title="An Espil",
                venue_name="Club TRI",
                price_text="$12000, en venta en articket.com.ar",
                occurrences=["2026-10-17"],
                image_url="https://www.turismomardelplata.gob.ar/foto.jpg",
            ),
            make_member(
                "articket",
                title="AN ESPIL EN CLUB TRI",
                ticket_url="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/",
                occurrences=["2026-10-17", "2026-10-24"],
                image_url="https://articket.com.ar/poster.jpg",
            ),
            make_member("clubtri", title="AN ESPIL EN CLUB TRI", price_text="Comprar"),
        ]

    def test_seller_title_and_ticket_win(self):
        event = build_site.merge_members(self.cluster(), empty_index(), SNAPSHOT_TODAY)
        assert event["title"] == "AN ESPIL EN CLUB TRI"
        assert event["ticket_url"] == "https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"

    def test_seller_image_wins(self):
        event = build_site.merge_members(self.cluster(), empty_index(), SNAPSHOT_TODAY)
        assert event["image_url"] == "https://articket.com.ar/poster.jpg"

    def test_placeholder_price_does_not_shadow_municipal_text(self):
        event = build_site.merge_members(self.cluster(), empty_index(), SNAPSHOT_TODAY)
        assert event["price_text"] == "$12000, en venta en articket.com.ar"
        assert event["price_label"] == "$12.000"

    def test_dates_are_the_union_of_member_occurrences(self):
        event = build_site.merge_members(self.cluster(), empty_index(), SNAPSHOT_TODAY)
        assert event["dates"] == ["2026-10-17", "2026-10-24"]

    def test_past_occurrences_are_dropped(self):
        members = [make_member("municipal", occurrences=["2026-10-13", "2026-11-20"])]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["dates"] == ["2026-11-20"]

    def test_positive_price_beats_a_stray_free_flag(self):
        members = [
            make_member(
                "articket",
                price_min=30000,
                price_text=None,
                is_free=False,
                ticket_url="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/",
            ),
            make_member("cualpinta", source_event_id="cualpinta-1", price_min=0, is_free=True),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["is_free"] is False
        assert event["price_label"] == "$30.000"

    def test_free_when_no_member_has_a_positive_price(self):
        members = [
            make_member("municipal", is_free=True, price_min=None),
            make_member("clubtri", source_event_id="clubtri-1", is_free=None, price_min=None),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["is_free"] is True
        assert event["price_label"] == "Gratis"

    def test_address_from_municipal_raw_when_registry_has_none(self):
        members = [
            make_member("municipal", venue_name="Galpón Nuevo", venue_raw="Galpón Nuevo, Calle Falsa 123"),
            make_member("articket", venue_name="Galpón Nuevo", source_event_id="articket-2"),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["address"] == "Calle Falsa 123"

    def test_registry_address_wins_for_known_venue(self):
        registry = [{"id": "club-tri", "name": "Club TRI", "aliases": ["ClubTri"], "address": "20 de Septiembre 2650"}]
        event = build_site.merge_members(self.cluster(), build_site.venue_index(registry), SNAPSHOT_TODAY)
        assert event["venue_id"] == "club-tri"
        assert event["venue_name"] == "Club TRI"
        assert event["address"] == "20 de Septiembre 2650"

    def test_single_member_fallback(self):
        event = build_site.merge_members([make_member("articket")], empty_index(), SNAPSHOT_TODAY)
        assert event["title"] == "Evento articket"
        assert event["venue_name"] == "Club TRI"
        assert event["dates"] == ["2026-10-17"]


class TestTicketLinkSelection:
    """The buy link must be the event page, never a ticketera homepage."""

    def test_homepage_does_not_beat_a_deep_link(self):
        members = [
            make_member(
                "cualpinta",
                ticket_url="https://alpogo.com",
                seller="Alpogo",
                raw_url="https://www.cualpinta.com/mar-del-plata/eventos/attack",
            ),
            make_member(
                "elevenflow",
                ticket_url="https://alpogo.com/evento/attack-28691",
                seller="Alpogo",
                raw_url="https://elevenflow.app/events/attack",
            ),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["ticket_url"] == "https://alpogo.com/evento/attack-28691"
        assert event["seller"] == "Alpogo"
        assert event["source_url"] == "https://elevenflow.app/events/attack"

    def test_homepage_only_is_not_a_cta(self):
        member = make_member(
            "cualpinta",
            ticket_url="https://alpogo.com",
            seller="Alpogo",
            price_min=50000.0,
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        assert event["ticket_url"] is None
        assert event["seller"] == "Alpogo"
        row = build_site.render_row(event, SNAPSHOT_TODAY)
        assert 'data-outbound="ticket"' not in row
        assert "Venta en Alpogo" in row

    def test_details_leave_the_source_unlinked_when_it_has_no_event_page(self):
        # The municipal agenda is paginated by date: the recorded page drifts
        # as events pass, so it never opens the event it claims to source.
        member = make_member(
            "municipal",
            price_text="$35000, en venta en www.plateanet.com",
            seller="Plateanet",
            raw_url="https://www.turismomardelplata.gob.ar/ASP/SP/resultados-eventos.asp?pagina=6&tipo=11",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        details = build_site.render_row_details(event)
        assert "Datos:" not in details
        assert "Venta:</b> Plateanet" in details
        assert "Fuente:</b> Municipal" in details
        assert "resultados-eventos.asp" not in details

    def test_source_link_is_rendered_as_a_button(self):
        # A bare anchor inherits the page color, so nothing marks it clickable.
        member = make_member("punto", raw_url="https://puntomardelplata.com/actividades/x-1")
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        details = build_site.render_row_details(event)
        assert 'class="btn btn--source"' in details
        assert "Ver en" in details

    def test_deep_link_seller_prefers_the_url_host(self):
        member = make_member(
            "cualpinta",
            ticket_url="https://wearebombo.com/evento/colyn",
            seller="nan",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        assert event["seller"] == "Bombo"

    def test_colon_program_page_is_the_source_link(self):
        # S2: the exception is what turns the Colón rows into linked rows; the
        # municipal member next to them keeps its paginated listing rejected.
        members = [
            make_member(
                "municipal",
                raw_url="https://www.turismomardelplata.gob.ar/ASP/SP/resultados-eventos.asp?pagina=4&tipo=11",
            ),
            make_member("colon", raw_url=COLON_PROGRAM_URL),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["source_name"] == "colon"
        assert event["source_url"] == COLON_PROGRAM_URL
        details = build_site.render_row_details(event)
        assert f'href="{COLON_PROGRAM_URL}"' in details
        assert "Ver en Teatro Colón" in details

    def test_source_link_falls_back_to_a_member_with_a_source_page(self):
        homepage = make_member(
            "cualpinta",
            ticket_url="https://alpogo.com",
            seller="Alpogo",
            raw_url=None,
        )
        source = make_member(
            "municipal",
            raw_url="https://www.turismomardelplata.gob.ar/evento",
        )
        event = build_site.merge_members([homepage, source], empty_index(), SNAPSHOT_TODAY)
        assert event["source_url"] == "https://www.turismomardelplata.gob.ar/evento"
        assert event["source_name"] == "municipal"

    def test_featured_card_shows_the_seller_not_the_raw_host(self):
        member = make_member(
            "articket",
            ticket_url="https://articket.com.ar/AN-ESPIL/",
            seller="Articket",
            occurrences=["2026-10-17"],
            date_start="2026-10-17",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        html = build_site.render_featured_card(event, SNAPSHOT_TODAY, "lead")
        assert "Venta en Articket" in html

    def test_row_without_price_or_link_points_to_the_source(self):
        member = make_member(
            "municipal",
            raw_url="https://www.turismomardelplata.gob.ar/evento",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        row = build_site.render_row(event, SNAPSHOT_TODAY)
        assert "Consultar" in row
        assert "según la fuente" in row

    def test_row_without_price_shows_the_sale_channel(self):
        member = make_member(
            "municipal",
            seller="Plateanet",
            raw_url="https://www.turismomardelplata.gob.ar/evento",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        row = build_site.render_row(event, SNAPSHOT_TODAY)
        assert "Venta en Plateanet" in row

    def test_search_query_is_not_a_deep_link(self):
        member = make_member(
            "cualpinta",
            ticket_url="https://articket.com.ar/?buscar=cumbia",
            seller="Articket",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        assert event["ticket_url"] is None
        assert event["seller"] == "Articket"

    def test_details_without_a_source_url_keep_the_source_label(self):
        member = make_member("municipal", raw_url=None, seller="Plateanet")
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        details = build_site.render_row_details(event)
        assert "Fuente:</b> Municipal" in details

    def test_listing_endpoint_without_the_trailing_slash_is_not_a_source(self):
        # S3c: the marker pinned the trailing slash, so the same endpoint with
        # a query string read as a ficha and became a "Fuente" link.
        member = make_member(
            "articket",
            raw_url="https://articket.com.ar/obtener_eventos?cantidad_eventos=500",
            seller="Articket",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        assert event["source_url"] is None
        details = build_site.render_row_details(event)
        assert "Fuente:</b> Articket" in details
        assert "obtener_eventos" not in details
        assert 'class="btn btn--source"' not in details
        # PRESERVE: a real ficha is still the Fuente link.
        ficha = make_member(
            "articket",
            raw_url="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/",
            seller="Articket",
        )
        event = build_site.merge_members([ficha], empty_index(), SNAPSHOT_TODAY)
        assert event["source_url"] == "https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"
        assert 'class="btn btn--source"' in build_site.render_row_details(event)

    def test_source_falling_back_to_the_buy_page_is_plain_text(self):
        # D1: when no ficha exists the source falls back to the member's own
        # ticket link. Linking it again next to the buy CTA would render two
        # affordances that open the same URL.
        member = make_member(
            "articket",
            raw_url="https://articket.com.ar/obtener_eventos/?cantidad_eventos=500",
            ticket_url="https://articket.com.ar/AN-ESPIL/",
            seller="Articket",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        assert event["source_url"] == event["ticket_url"] == "https://articket.com.ar/AN-ESPIL/"
        details = build_site.render_row_details(event)
        assert "Fuente:</b> Articket" in details
        assert 'class="btn btn--source"' not in details
        assert details.count('href="https://articket.com.ar/AN-ESPIL/"') == 1
        assert "Comprar en articket.com.ar" in details

    def test_source_differing_from_the_buy_page_stays_a_link(self):
        # PRESERVE: two different URLs are two affordances, not a duplicate.
        member = make_member(
            "articket",
            raw_url="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/",
            ticket_url="https://articket.com.ar/AN-ESPIL/",
            seller="Articket",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        assert event["source_url"] != event["ticket_url"]
        details = build_site.render_row_details(event)
        assert 'class="btn btn--source"' in details
        assert "Ver en Articket" in details
        assert 'href="https://articket.com.ar/AN-ESPIL/"' in details


class TestVenueSite:
    """S6: the venue's own site gets its own detail line, never the Fuente link."""

    VENUE_URL = "http://www.centrodeartemdp.com"

    # The venue_url values a live run captured from the panels (2026-11-21): 23
    # rows over 10 distinct values. Seven rows are not a venue site: an address
    # in an http href, a handle, a scheme with no host, the municipality on the
    # .gov.ar spelling. The snapshot still carries them, so the site filters.
    BAD_VENUE_URLS = (
        "http://abbeyroadreservas@hotmail.com",
        "http://IG @feriadeartesanosdelbosque",
        "http://https:/abbeyroadmdp.com.ar/",
        "https:",
        "ig @feriadeartesanosdelbosque",
        "http://www.mardelplata.gov.ar",
        "www.mardelplata.gov.ar",
    )
    GOOD_VENUE_URLS = (
        "http://www.vorterixmdq.com.ar",
        "http://bendu.com.ar",
        "http://www.centrodeartemdp.com",
        "http://www.programacionauditorium.blogspot.com",
        "http://www.chauvin.com.ar",
        "http://www.sheratonmardelplatahotel.com",
    )

    def municipal_with_site(self, **overrides):
        fields = dict(
            venue_name="Centro de Arte Radio City",
            raw_url="https://www.turismomardelplata.gob.ar/ASP/SP/resultados-eventos.asp?pagina=1&tipo=11",
            venue_url=self.VENUE_URL,
        )
        fields.update(overrides)
        return make_member("municipal", **fields)

    def test_venue_site_is_merged_from_the_municipal_member(self):
        members = [self.municipal_with_site(), make_member("articket", source_event_id="articket-2")]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["venue_url"] == self.VENUE_URL

    def test_venue_site_renders_its_own_detail_line(self):
        event = build_site.merge_members([self.municipal_with_site()], empty_index(), SNAPSHOT_TODAY)
        details = build_site.render_row_details(event)
        assert (
            f'<p><b>Sala:</b> <a class="btn btn--source" href="{self.VENUE_URL}" '
            'target="_blank" rel="noopener">Ver sitio de la sala ↗</a></p>'
        ) in details

    def test_venue_site_is_never_the_fuente_link(self):
        # The panel page is a paginated listing: rejected as a source link, so
        # the venue site must not sneak in as one either.
        event = build_site.merge_members([self.municipal_with_site()], empty_index(), SNAPSHOT_TODAY)
        details = build_site.render_row_details(event)
        assert "Fuente:</b> Municipal" in details
        assert "Fuente:</b> <a" not in details
        assert details.count(f'href="{self.VENUE_URL}"') == 1

    def test_venue_site_does_not_replace_a_purchase_cta(self):
        members = [
            self.municipal_with_site(),
            make_member(
                "articket",
                source_event_id="articket-2",
                ticket_url="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/",
            ),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["ticket_url"] == "https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"
        row = build_site.render_row(event, SNAPSHOT_TODAY)
        assert f'href="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"' in row
        assert 'data-outbound="ticket"' in row

    def test_venue_site_does_not_replace_a_real_event_page(self):
        members = [
            self.municipal_with_site(),
            make_member(
                "punto",
                source_event_id="punto-2",
                raw_url="https://puntomardelplata.com/actividades/fiesta-plop-20501",
            ),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["source_url"] == "https://puntomardelplata.com/actividades/fiesta-plop-20501"
        details = build_site.render_row_details(event)
        assert f'href="{self.VENUE_URL}"' in details
        assert "Ver en Punto MDP" in details

    def test_unknown_venue_site_renders_nothing(self):
        event = build_site.merge_members([self.municipal_with_site(venue_url=None)], empty_index(), SNAPSHOT_TODAY)
        details = build_site.render_row_details(event)
        assert "Sala:" not in details
        assert "Ver sitio de la sala" not in details

    @pytest.mark.parametrize("venue_url", BAD_VENUE_URLS)
    def test_a_bad_venue_url_renders_no_sala_line(self, venue_url):
        event = build_site.merge_members(
            [self.municipal_with_site(venue_url=venue_url)], empty_index(), SNAPSHOT_TODAY
        )
        assert event["venue_url"] == venue_url  # the snapshot value stays as it is
        details = build_site.render_row_details(event)
        assert "Sala:" not in details
        assert "Ver sitio de la sala" not in details

    @pytest.mark.parametrize("venue_url", GOOD_VENUE_URLS)
    def test_a_good_venue_url_renders_its_sala_line(self, venue_url):
        event = build_site.merge_members(
            [self.municipal_with_site(venue_url=venue_url)], empty_index(), SNAPSHOT_TODAY
        )
        details = build_site.render_row_details(event)
        assert (
            f'<p><b>Sala:</b> <a class="btn btn--source" href="{venue_url}" '
            'target="_blank" rel="noopener">Ver sitio de la sala ↗</a></p>'
        ) in details

    def test_the_site_and_the_collector_share_one_venue_site_rule(self):
        # R2-001: the rule had a copy at each end, so a fix in one could leave
        # the other rejecting the same URLs. Now a single module owns it and
        # both callers import that same function -- no mirrored copy to drift.
        from collectors import municipal
        from lib import site_urls

        assert build_site.venue_site_url is site_urls.venue_site_url
        assert municipal.venue_site_url is site_urls.venue_site_url
        assert not hasattr(build_site, "MUNICIPAL_HOSTS")
        assert not hasattr(municipal, "MUNICIPAL_HOSTS")

    def test_build_site_imports_with_only_the_standard_library(self):
        # -S drops site-packages: bs4 and requests are invisible, so the site
        # build (and the module it shares with the collector) must be stdlib.
        result = subprocess.run(
            [sys.executable, "-S", "-c", "import build_site"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr

    def test_duplicate_merge_keeps_the_venue_site(self):
        site_event = build_site.merge_members([make_member("municipal")], empty_index(), SNAPSHOT_TODAY)
        other = dict(site_event)
        other["venue_url"] = self.VENUE_URL
        merged = build_site.merge_site_duplicates(site_event, other)
        assert merged["venue_url"] == self.VENUE_URL


class TestExactDuplicateGuard:
    """The site never renders the same venue+title+date twice."""

    @staticmethod
    def site_event(title, venue_id, dates, **overrides):
        event = {
            "title": title,
            "venue_id": venue_id,
            "venue_name": venue_id,
            "address": None,
            "dates": dates,
            "time": "21:00",
            "is_free": False,
            "price_min": None,
            "price_text": None,
            "ticket_url": None,
            "image_url": None,
            "sources": ["articket"],
            "price_label": None,
            "display_title": title,
            "slug": f"{build_site.slugify(title)}-{dates[0]}",
        }
        event.update(overrides)
        return event

    def test_exact_duplicate_is_merged(self):
        left = self.site_event("Dillom", "bendu", ["2027-01-30"], sources=["ticketek"])
        right = self.site_event(
            "DILLOM", "bendu", ["2027-01-30"], sources=["punto"],
            ticket_url="https://venti.live/evento/dillom", price_min=69000,
        )
        merged = build_site.collapse_exact_duplicates([left, right])
        assert len(merged) == 1
        assert merged[0]["ticket_url"] == "https://venti.live/evento/dillom"
        assert merged[0]["price_min"] == 69000
        assert merged[0]["sources"] == ["punto", "ticketek"]

    def test_site_duplicate_fills_the_ticket_group_together(self):
        left = self.site_event("Dillom", "bendu", ["2027-01-30"], sources=["ticketek"])
        right = self.site_event(
            "DILLOM", "bendu", ["2027-01-30"], sources=["punto"],
            ticket_url="https://venti.live/evento/dillom",
            seller="Venti",
            source_name="punto",
            source_url="https://puntomardelplata.com/actividades/dillom",
        )
        merged = build_site.collapse_exact_duplicates([left, right])[0]
        assert merged["ticket_url"] == "https://venti.live/evento/dillom"
        assert merged["seller"] == "Venti"
        assert merged["source_name"] == "punto"
        assert merged["source_url"] == "https://puntomardelplata.com/actividades/dillom"

    def test_same_title_different_session_stays_two_rows(self):
        left = self.site_event("Dillom", "bendu", ["2027-01-30"])
        right = self.site_event("Dillom", "bendu", ["2027-01-31"])
        assert len(build_site.collapse_exact_duplicates([left, right])) == 2

    def test_same_title_different_venue_stays_two_rows(self):
        left = self.site_event("Dillom", "bendu", ["2027-01-30"])
        right = self.site_event("Dillom", "arena", ["2027-01-30"])
        assert len(build_site.collapse_exact_duplicates([left, right])) == 2

    def test_spacing_variant_of_the_same_title_collapses(self):
        # Qué Hacemos listed the same show as "An Espil" and "AnEspil".
        left = self.site_event("An Espil", "club-tri", ["2026-11-20"], sources=["municipal"])
        right = self.site_event("AnEspil", "club-tri", ["2026-11-20"], sources=["quehacemos"])
        merged = build_site.collapse_exact_duplicates([left, right])
        assert len(merged) == 1
        assert merged[0]["sources"] == ["municipal", "quehacemos"]

    def test_shared_date_merges_multi_date_rows(self):
        left = self.site_event("Festival", "arena", ["2026-12-05", "2026-12-06"])
        right = self.site_event("Festival", "arena", ["2026-12-06", "2026-12-07"])
        merged = build_site.collapse_exact_duplicates([left, right])
        assert len(merged) == 1
        assert merged[0]["dates"] == ["2026-12-05", "2026-12-06", "2026-12-07"]


class TestEscaping:
    def test_quotes_and_accents_are_escaped(self):
        member = make_member(
            "articket",
            title='Rock & Roll "en vivo" <script>alert(1)</script>',
            venue_name="Café Sábado",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        row = build_site.render_row(event, SNAPSHOT_TODAY)
        assert "&amp;" in row
        assert "&quot;" in row
        assert "<script>alert(1)</script>" not in row
        assert "Café Sábado" in row

    def test_format_when_shortens_long_date_lists(self):
        label = build_site.format_when(["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"], "21:00")
        assert label == "Jue 15/10, Vie 16/10, Sáb 17/10 · 21:00 · +2 fechas"

    def test_format_when_single_date(self):
        assert build_site.format_when(["2026-10-15"], "21:00") == "Jue 15/10 · 21:00"


class TestDisplayHelpers:
    """The agenda shows readable titles; the raw seller title stays in the data."""

    def test_uppercase_title_gets_sentence_case(self):
        assert build_site.title_case("THE BEATLES SINFONICO") == "The Beatles Sinfonico"

    def test_small_words_stay_lowercase(self):
        assert build_site.title_case("FALSO CASAMIENTO EN MAR DEL PLATA") == "Falso Casamiento en Mar del Plata"

    def test_known_acronyms_keep_caps(self):
        assert build_site.title_case("POST PUNK JUNK") == "Post Punk Junk"
        assert build_site.title_case("DJ SET EN VIVO") == "DJ Set en Vivo"

    def test_trailing_date_is_stripped(self):
        assert build_site.clean_title("SANTO PECADO EN ABBEY ROAD 16-10") == "SANTO PECADO EN ABBEY ROAD"

    def test_spanish_date_phrase_is_stripped(self):
        assert build_site.clean_title("Colyn 21 noviembre 2026") == "Colyn"
        assert build_site.clean_title("Solomun 2 de enero de 2027") == "Solomun"

    def test_leading_weekday_date_is_stripped(self):
        assert build_site.clean_title("SAB 17-10 LUCHO SSJ") == "LUCHO SSJ"

    def test_well_cased_member_title_wins(self):
        members = [
            make_member("articket", title="SANTO PECADO EN ABBEY ROAD 16-10"),
            make_member("municipal", title="Santo Pecado", source_event_id="municipal-2"),
        ]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["title"] == "SANTO PECADO EN ABBEY ROAD 16-10"
        assert event["display_title"] == "Santo Pecado"

    def test_display_title_falls_back_to_case_fix(self):
        members = [make_member("clubtri", title="GEORGIE BOY EN WOLFGANG")]
        event = build_site.merge_members(members, empty_index(), SNAPSHOT_TODAY)
        assert event["display_title"] == "Georgie Boy en Wolfgang"

    def test_quoted_word_is_capitalized(self):
        # S5: the opening quote used to eat the capital ('‘norma Fontenla’).
        assert build_site.title_case(
            "CICLO ANUAL BALLET DE CÁMARA DE LA ESCUELA MUNICIPAL DE DANZAS ‘NORMA FONTENLA’"
        ) == "Ciclo Anual Ballet de Cámara de la Escuela Municipal de Danzas ‘Norma Fontenla’"

    def test_already_mixed_case_words_are_preserved(self):
        # Sentence-casing must not lowercase proper nouns into nonsense.
        assert build_site.title_case("HOMENAJE A McCartney EN VIVO") == "Homenaje a McCartney en Vivo"

    def test_uppercase_municipal_title_gets_a_readable_display_title(self):
        raw = "CICLO ANUAL BALLET DE CÁMARA DE LA ESCUELA MUNICIPAL DE DANZAS ‘NORMA FONTENLA’"
        event = build_site.merge_members([make_member("municipal", title=raw)], empty_index(), SNAPSHOT_TODAY)
        assert event["title"] == raw
        assert event["display_title"] == (
            "Ciclo Anual Ballet de Cámara de la Escuela Municipal de Danzas ‘Norma Fontenla’"
        )

    def test_uppercase_colon_title_keeps_the_raw_title(self):
        raw = "ORQUESTA SINFÓNICA MUNICIPAL"
        event = build_site.merge_members(
            [make_member("colon", title=raw, raw_url=COLON_PROGRAM_URL)], empty_index(), SNAPSHOT_TODAY
        )
        assert event["title"] == raw
        assert event["display_title"] == "Orquesta Sinfónica Municipal"

    def test_initials_and_thumb_variant_are_stable(self):
        assert build_site.initials("Koino Yokan en Club TRI") == "KY"
        assert build_site.initials("C4") == "C"
        assert build_site.thumb_variant("club-tri") == build_site.thumb_variant("club-tri")
        assert 0 <= build_site.thumb_variant("club-tri") < 4

    def test_price_parts_splits_the_desde_note(self):
        assert build_site.price_parts({"price_label": "Desde $20.000"}) == ("$20.000", "desde")
        assert build_site.price_parts({"price_label": "$20.000"}) == ("$20.000", "entrada")
        assert build_site.price_parts({"price_label": "Gratis"}) == ("Gratis", "")
        assert build_site.price_parts({"price_label": None}) is None

    def test_group_by_date_uses_the_primary_date(self):
        first = build_site.merge_members(
            [make_member("articket", occurrences=["2026-10-16", "2026-10-17"])], empty_index(), SNAPSHOT_TODAY
        )
        second = build_site.merge_members(
            [make_member("municipal", occurrences=["2026-10-17"], source_event_id="m2")], empty_index(), SNAPSHOT_TODAY
        )
        groups = build_site.group_by_date([first, second])
        assert [iso for iso, _ in groups] == ["2026-10-16", "2026-10-17"]
        assert len(groups[1][1]) == 1
        assert build_site.in_weekend("2026-10-17", SNAPSHOT_TODAY)
        assert not build_site.in_weekend("2026-10-22", SNAPSHOT_TODAY)


def day_groups(html):
    """[(iso, in_weekend, row_count)] straight from the rendered page."""
    blocks = re.split(r'<section class="daygroup"', html)[1:]
    groups = []
    for block in blocks:
        match = re.match(r' data-date="([\d-]+)" data-in-weekend="([01])"', block)
        assert match, "day group without date attributes"
        groups.append((match.group(1), match.group(2) == "1", block.count("<article class=\"row\"")))
    return groups


def test_is_event_page_rejects_listings_and_endpoints():
    assert build_site.is_event_page("https://puntomardelplata.com/actividades/fiesta-plop-20501")
    assert not build_site.is_event_page(
        "https://www.turismomardelplata.gob.ar/ASP/SP/resultados-eventos.asp?pagina=4&tipo=11"
    )
    assert not build_site.is_event_page("https://articket.com.ar/obtener_eventos/?cantidad_eventos=500")
    assert not build_site.is_event_page("https://api.venti.live/api/home/events?limit=100&page=1")
    assert not build_site.is_event_page("https://clubtri.com/")
    assert not build_site.is_event_page(None)


def test_articket_endpoint_is_rejected_without_the_trailing_slash():
    # S3c: "/obtener_eventos/" pinned the trailing slash, so the same endpoint
    # with no slash, a query string or a fragment read as a ficha and could be
    # published as "Fuente".
    for spelling in (
        "https://articket.com.ar/obtener_eventos",
        "https://articket.com.ar/obtener_eventos?cantidad_eventos=500",
        "https://articket.com.ar/obtener_eventos#cartelera",
        "https://articket.com.ar/obtener_eventos/?cantidad_eventos=500",
    ):
        assert not build_site.is_event_page(spelling), spelling
    # PRESERVE: Articket publishes each ficha under its own path segment.
    assert build_site.is_event_page("https://articket.com.ar/AN-ESPIL/")
    assert build_site.is_event_page("https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/")


def test_listing_marker_in_the_query_keeps_the_ficha_linkable():
    # R3-003: listing-ness is decided from the path, so a ficha whose query
    # string or fragment merely carries the marker (a redirect or ref
    # parameter) is still an event page and keeps its "Fuente" link. The
    # previous guard searched the whole URL and dropped these.
    for url in (
        "https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/?ref=/obtener_eventos",
        "https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/?next=https://articket.com.ar/obtener_eventos/?cantidad_eventos=500",
        "https://puntomardelplata.com/actividades/fiesta-plop-20501?volver=/colonprogramacion",
        "https://puntomardelplata.com/actividades/fiesta-plop-20501?origen=resultados-eventos.asp",
        "https://puntomardelplata.com/actividades/fiesta-plop-20501?fallback=api.venti.live",
        "https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/#/obtener_eventos",
    ):
        assert build_site.is_event_page(url), url


@pytest.mark.parametrize("marker", build_site.LISTING_URL_PATTERNS)
def test_every_listing_marker_rejects_its_trailing_slash_spellings(marker):
    # S3c: the guard drops the marker's trailing slash before comparing, so
    # every entry -- this one and any added later -- rejects the page with no
    # slash, with the slash, with a query string and with a fragment.
    segment = "/" + marker.strip("/")
    for suffix in ("", "/", "?limit=100", "#eventos"):
        url = f"https://example.com.ar{segment}{suffix}"
        assert not build_site.is_event_page(url), url


def test_is_event_page_requires_an_http_scheme_and_a_real_path():
    # D3: the scheme was never checked and an empty path with a query passed.
    assert not build_site.is_event_page("ftp://host/colonprogramacion")
    assert not build_site.is_event_page("ftp://www.mardelplata.gob.ar/colonprogramacion")
    assert not build_site.is_event_page("https://host/?p=1")
    assert not build_site.is_event_page("https://puntomardelplata.com/?p=1")
    # PRESERVE: both accepted schemes, and a real path is still a ficha.
    assert build_site.is_event_page("http://example.com.ar/evento/123")
    assert build_site.is_event_page("https://puntomardelplata.com/actividades/fiesta-plop-20501")
    assert build_site.is_event_page("https://clubtri.com/fuego-sagrado")
    assert not build_site.is_event_page("https://articket.com.ar/obtener_eventos/")
    assert not build_site.is_event_page("https://api.venti.live/api/home/events")
    assert not build_site.is_event_page("https://clubtri.com")
    assert not build_site.is_event_page("https://clubtri.com/")
    # PRESERVE: the Colón exception tolerates www and a trailing slash.
    assert build_site.is_event_page(COLON_PROGRAM_URL)
    assert build_site.is_event_page("https://mardelplata.gob.ar/colonprogramacion/")
    assert not build_site.is_event_page(COLON_PROGRAM_URL + "?pagina=2")


def test_colon_program_page_qualifies_as_a_source_link():
    # S2: Colón publishes the whole temporada on one page that is not
    # paginated by date, so the recorded URL still opens the events it lists.
    assert build_site.is_event_page(COLON_PROGRAM_URL)
    assert build_site.is_event_page(COLON_PROGRAM_URL + "/")


def test_colon_exception_is_only_that_host_and_path():
    assert not build_site.is_event_page("https://www.mardelplata.gob.ar/colonprogramacion-old")
    assert not build_site.is_event_page(COLON_PROGRAM_URL + "?pagina=2")
    assert not build_site.is_event_page("https://otro-sitio.com.ar/colonprogramacion")
    assert not build_site.is_event_page(
        "https://www.turismomardelplata.gob.ar/ASP/SP/resultados-eventos.asp?pagina=4&tipo=11"
    )


class TestDeterministicBuild:
    """Full build from the committed snapshot into a tmp dir."""

    def build(self, tmp_path, today=BUILD_TODAY):
        stats = build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=today)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        return stats, html

    def test_files_written(self, tmp_path):
        stats, _ = self.build(tmp_path)
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "assets" / "style.css").exists()
        assert (tmp_path / "assets" / "filter.js").exists()
        assert (tmp_path / "assets" / "app.js").exists()
        assert (tmp_path / "favicon.svg").exists()
        assert stats["files"] == [
            "index.html",
            "assets/style.css",
            "assets/filter.js",
            "assets/app.js",
            "favicon.svg",
        ]

    def test_filter_module_loads_before_the_script_that_uses_it(self, tmp_path):
        # app.js reads the predicate from that module at parse time, so the
        # tag order is part of the contract.
        _, html = self.build(tmp_path)
        assert '<script src="assets/filter.js"></script>' in html
        assert html.index("assets/filter.js") < html.index("assets/app.js")

    def test_counts_match_the_snapshot(self, tmp_path):
        stats, html = self.build(tmp_path)
        rows = html.count("<article class=\"row\"")
        assert stats["today"] == BUILD_TODAY.isoformat()
        assert stats["upcoming"] == rows
        assert stats["weekend"] == sum(rows for _, weekend, rows in day_groups(html) if weekend)
        assert rows > 0

    def test_each_event_is_listed_once_under_its_first_date(self, tmp_path):
        _, html = self.build(tmp_path)
        ids = re.findall(r'<article class="row" data-row data-id="([^"]+)"', html)
        assert ids
        assert len(set(ids)) == len(ids)

    def test_snapshot_has_no_exact_duplicate_rows(self):
        events, _, _ = build_site.collect_site_events(DATA_DIR, BUILD_TODAY)
        triples = [
            (event["venue_id"], build_site.normalize_key(event["title"]), day)
            for event in events
            for day in event["dates"]
        ]
        assert triples
        assert len(set(triples)) == len(triples)

    def test_day_groups_are_sorted_and_dated(self, tmp_path):
        _, html = self.build(tmp_path)
        groups = day_groups(html)
        assert groups
        assert [iso for iso, _, _ in groups] == sorted(iso for iso, _, _ in groups)
        for iso, weekend, rows in groups:
            assert rows >= 1
            assert weekend == build_site.in_weekend(iso, BUILD_TODAY)

    def test_hero_and_footer_copy(self, tmp_path):
        _, html = self.build(tmp_path)
        assert "Qué hay este finde" in html
        assert build_site.format_weekend_kicker(BUILD_TODAY) in html
        for label in ("agenda municipal", "Articket", "CultuTickets", "Club TRI", "Venti", "Ticketek", "Bombo", "Punto MDP"):
            assert label in html
        last_run = json.loads((DATA_DIR / "last_run.json").read_text(encoding="utf-8"))
        assert f"Actualizado {build_site.format_updated(last_run)}" in html

    def test_past_event_is_dropped(self, tmp_path):
        _, html = self.build(tmp_path)
        assert "Que Viva España" not in html

    def test_singles_from_normalized_are_included(self, tmp_path):
        # The deduped file only exports clusters; singles must come from normalized.
        _, html = self.build(tmp_path)
        assert "19º Encuentro Internacional de Coros Mardelcanto 2026" in html

    @pytest.mark.parametrize("today", TICKET_TODAYS)
    def test_known_ticket_url_is_linked(self, tmp_path, today):
        # Two pinned build dates, both inside the show's lifetime, so the row
        # is linked no matter what the calendar says the day the suite runs.
        _, html = self.build(tmp_path, today=today)
        assert 'href="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"' in html
        assert html.count('data-outbound="ticket"') > 0
        assert html.count('target="_blank" rel="noopener"') >= html.count('data-outbound="ticket"')

    def test_source_links_point_at_events_not_listings(self, tmp_path):
        # The municipal agenda is paginated by date, so the recorded page
        # drifts; the ticketeras expose a JSON endpoint instead of a ficha.
        _, html = self.build(tmp_path)
        assert "resultados-eventos.asp" not in html
        assert "obtener_eventos" not in html
        assert "api.venti.live" not in html

    def test_colon_program_page_recovers_the_seven_unlinked_rows(self, tmp_path):
        # S2 recovery target: 2 Colón-only rows + 5 shared with Municipal.
        today = date(2026, 11, 21)
        build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=today)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert html.count(f'href="{COLON_PROGRAM_URL}"') == 7

    def test_event_page_source_link_survives(self, tmp_path):
        _, html = self.build(tmp_path)
        assert "puntomardelplata.com/actividades/" in html

    def test_json_ld_is_parseable_and_lists_the_weekend(self, tmp_path):
        stats, html = self.build(tmp_path)
        match = JSON_LD_RE.search(html)
        assert match, "JSON-LD script not found"
        payload = json.loads(match.group(1))
        assert payload[0]["@type"] == "WebSite"
        assert payload[1]["@type"] == "ItemList"
        items = payload[1]["itemListElement"]
        assert len(items) == stats["weekend"]
        first = items[0]["item"]
        assert first["@type"] == "Event"
        assert first["name"]
        payload = json.loads(DATA_RE.search(html).group(1))
        weekend_start = payload["windows"]["weekend"]["start"]
        assert first["startDate"][:7] == weekend_start[:7]
        assert first["location"]["name"]


class TestRedesignMarkup:
    """Agenda, day navigation, themes and the expandable detail row."""

    def build(self, tmp_path):
        stats = build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=BUILD_TODAY)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        css = (tmp_path / "assets" / "style.css").read_text(encoding="utf-8")
        app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")
        payload = json.loads(DATA_RE.search(html).group(1))
        return stats, html, css, app_js, payload

    def test_day_navigation_markup(self, tmp_path):
        stats, html, _, _, payload = self.build(tmp_path)
        window = payload["windows"]["weekend"]
        days = (date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days + 1
        assert 'class="daynav"' in html
        day_nav = html.split('aria-label="Filtrar por día">', 1)[1].split("</nav>", 1)[0]
        assert 'data-view="weekend"' in day_nav
        assert f'data-view="{window["start"]}"' in day_nav
        assert f'data-view="{window["end"]}"' in day_nav
        assert 'data-view="next-weekend"' in day_nav
        assert 'data-view="all"' in day_nav
        assert day_nav.count("data-view=") == days + 3
        # The finde view is the default when the weekend has events.
        assert stats["weekend"] > 0
        assert re.search(r'class="day is-on" data-view="weekend"', html)

    def test_day_and_month_chips_toggle_without_scrolling(self, tmp_path):
        _, _, _, app_js, _ = self.build(tmp_path)
        # Clicking the active chip clears it back to "Todo"; no auto-scroll.
        assert "scrollIntoView" not in app_js
        assert 'state.view === view && view !== "all" ? "all" : view' in app_js

    def test_featured_stays_visible_when_filters_change(self, tmp_path):
        _, _, _, app_js, _ = self.build(tmp_path)
        assert "keepFeatured" not in app_js
        assert "featured.hidden" not in app_js

    def test_day_nav_is_not_sticky(self, tmp_path):
        _, _, css, _, _ = self.build(tmp_path)
        daynav = css.split(".daynav {", 1)[1].split("}", 1)[0]
        assert "position: sticky" not in daynav
        assert ".featured__foot" in css

    def test_month_navigation_markup(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        month_nav = html.split('aria-label="Filtrar por mes">', 1)[1].split("</nav>", 1)[0]
        keys = re.findall(r'data-view="month:(\d{4}-\d{2})"', month_nav)
        expected = sorted({event["dates"][0][:7] for event in payload["events"]})[: build_site.MONTH_NAV_LIMIT]
        assert keys == expected
        assert "Noviembre" in month_nav
        assert "Enero 2027" in month_nav

    def test_day_tab_counts_match_their_groups(self, tmp_path):
        stats, html, _, _, payload = self.build(tmp_path)
        tabs = dict(re.findall(r'data-view="([^"]+)"[^>]*>.*?<i>(\d+)</i>', html, re.DOTALL))
        groups = day_groups(html)
        for iso, _weekend, rows in groups:
            if iso in tabs:
                assert int(tabs[iso]) == rows
        assert int(tabs["weekend"]) == stats["weekend"]
        assert int(tabs["all"]) == stats["upcoming"]

        next_window = payload["windows"]["next_weekend"]
        expected_next = sum(
            1
            for event in payload["events"]
            if next_window["start"] <= event["dates"][0] <= next_window["end"]
        )
        if expected_next:
            assert int(tabs["next-weekend"]) == expected_next
        else:
            assert "next-weekend" not in tabs

        for key in re.findall(r'data-view="month:(\d{4}-\d{2})"', html):
            expected_month = sum(1 for event in payload["events"] if event["dates"][0].startswith(key))
            assert int(tabs[f"month:{key}"]) == expected_month

    def test_rows_carry_filter_attributes(self, tmp_path):
        stats, html, _, _, _ = self.build(tmp_path)
        rows = re.findall(r'<article class="row" ([^>]*)>', html)
        assert len(rows) == stats["upcoming"]
        for attrs in rows:
            for attribute in ("data-row", "data-id=", "data-date=", "data-in-weekend=",
                              "data-free=", "data-venue=", "data-search=", "data-initials=",
                              "data-title=", "data-when="):
                assert attribute in attrs

    def test_rows_have_an_expandable_detail(self, tmp_path):
        stats, html, _, _, _ = self.build(tmp_path)
        assert html.count('class="row__more js-disclose" aria-expanded="false"') == stats["upcoming"]
        controls = re.findall(r'aria-controls="(detail-[^"]+)"', html)
        details = re.findall(r'class="row__details" id="(detail-[^"]+)" hidden', html)
        assert len(controls) == stats["upcoming"]
        assert sorted(controls) == sorted(details)

    def test_every_row_has_a_share_action(self, tmp_path):
        stats, html, _, _, _ = self.build(tmp_path)
        featured_cards = html.count('data-feature="1"')
        assert featured_cards == build_site.FEATURED_LIMIT
        assert html.count('js-share') == stats["upcoming"] + featured_cards
        assert "Compartir" in html

    def test_outbound_links_match_the_payload(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        with_ticket = [event for event in payload["events"] if event["ticket_url"]]
        pattern = re.compile(
            r'<a class="row__cta row__cta--buy" href="[^"]+" target="_blank" rel="noopener" '
            r'data-outbound="ticket" data-event-id="[^"]+">Entradas</a>'
        )
        assert len(pattern.findall(html)) == len(with_ticket)
        assert "Entradas" in html

    def test_events_without_poster_get_a_typographic_thumb(self, tmp_path):
        _, html, _, _, _ = self.build(tmp_path)
        assert "row__thumb--type" in html
        assert "feature__fallback" in html or "feature__poster" in html

    def test_multi_date_events_show_the_extra_dates_tag(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        multi = [event for event in payload["events"] if len(event["dates"]) > 1]
        assert multi, "the snapshot should contain multi-date events"
        assert re.search(r'class="tag tag--more">\+\d+ fechas</span>', html)

    def test_theme_boot_toggle_and_tokens(self, tmp_path):
        _, html, css, app_js, _ = self.build(tmp_path)
        assert 'name="color-scheme" content="dark light"' in html
        assert 'id="theme-toggle"' in html
        assert "cartelera-theme" in html and "prefers-color-scheme" in html
        assert '[data-theme="light"]' in css
        assert "--bg: #080d12" in css and "--bg: #f4f1e9" in css
        assert "theme_change" in app_js

    def test_shell_uses_more_of_wide_screens(self, tmp_path):
        _, _, css, _, _ = self.build(tmp_path)
        assert "--shell: 1440px" in css
        assert "@media (min-width: 1680px)" in css
        assert "--shell: 1560px" in css

    def test_filter_and_carousel_css_replaces_the_modal(self, tmp_path):
        _, _, css, _, _ = self.build(tmp_path)
        assert ".filterbar" in css
        assert ".sala-drawer" in css
        assert ".sala-option" in css
        assert ".featured__page" in css
        assert ".filters-panel" not in css
        assert ".filters-overlay" not in css

    def test_filter_bar_is_inline_and_collapsible(self, tmp_path):
        _, html, _, app_js, _ = self.build(tmp_path)
        assert 'class="filterbar"' in html
        assert 'id="filter-free"' in html
        assert 'id="sala-toggle"' in html
        assert 'aria-controls="sala-drawer"' in html
        assert 'id="sala-drawer"' in html
        assert re.search(r'id="sala-drawer"[^>]*hidden', html)
        assert 'role="dialog"' not in html
        assert 'id="filters-panel"' not in html
        assert 'filters-overlay' not in html
        assert 'id="filters-days"' not in html
        assert 'id="venue-search"' in html
        assert 'id="sala-grid"' in html
        assert 'id="filter-count"' in html
        assert 'id="empty-state"' in html
        assert 'id="clear-filters"' in html
        assert "No hay eventos con esos filtros" in html
        for hook in (
            "filter_change",
            "auto-todo",
            "outbound_ticket",
            "share_whatsapp",
            "sala-drawer",
            "sala-toggle",
            "showFeaturedPage",
        ):
            assert hook in app_js

    def test_venue_chips_are_the_six_busiest_registered_venues(self, tmp_path):
        _, html, _, _, _ = self.build(tmp_path)
        events, registry, _ = build_site.collect_site_events(DATA_DIR, BUILD_TODAY)
        expected = build_site.top_venues(events, 6, registry)
        chips = re.findall(r'class="fchip" data-venue="([^"]+)"', html)
        assert chips == [venue_id for _, venue_id, _ in expected]
        assert len(chips) == 6

    def test_sala_drawer_lists_every_registered_venue(self, tmp_path):
        _, html, _, _, _ = self.build(tmp_path)
        events, registry, _ = build_site.collect_site_events(DATA_DIR, BUILD_TODAY)
        expected = build_site.venue_options(events, registry)
        drawer = html.split('id="sala-drawer"', 1)[1].split("</section>", 1)[0]
        assert f'data-preview="{build_site.SALA_PREVIEW_LIMIT}"' in drawer
        tags = re.findall(
            r'<button type="button" class="sala-option[^"]*" data-venue="[^"]*"[^>]*>',
            drawer,
        )
        assert len(tags) == len(expected)
        assert sum(" hidden" not in tag for tag in tags) == build_site.SALA_PREVIEW_LIMIT
        venue_ids = re.findall(r'data-venue="([^"]+)"', drawer)
        assert venue_ids == [venue_id for _, venue_id, _ in expected]
        assert f"Ver todas las salas ({len(expected)})" in drawer
        assert 'role="dialog"' not in drawer

    def test_intro_venue_stat_uses_the_registered_catalog(self, tmp_path):
        stats, html, _, _, _ = self.build(tmp_path)
        events, registry, _ = build_site.collect_site_events(DATA_DIR, BUILD_TODAY)
        assert stats["venues"] == len(build_site.venue_options(events, registry))
        assert f'<span data-label="Salas"><b>{stats["venues"]}</b></span>' in html

    def test_featured_carousel_pages_eight_events(self, tmp_path):
        _, html, _, app_js, payload = self.build(tmp_path)
        venue_names = re.findall(
            r'<article class="feature feature--(?:lead|mini)"[^>]*data-feature="1"[^>]*data-venue-name="([^"]+)"',
            html,
        )
        assert len(venue_names) == build_site.FEATURED_LIMIT == 8
        assert len(set(venue_names)) == 8
        pages = re.findall(r'<div class="featured__page featured__grid[^"]*"[^>]*>', html)
        assert len(pages) == 3
        assert sum("hidden" in page for page in pages) == 2
        # Every page carries its own lead, so the arrows rotate the main card too.
        assert html.count('class="feature feature--lead"') == 3
        assert 'id="featured-prev"' in html and 'id="featured-next"' in html
        assert 'id="featured-page-count"' in html
        assert "showFeaturedPage" in app_js
        assert 'id="featured-title">Destacados<' in html
        assert html.index('class="featured__foot"') > html.index('class="featured__pages"')
        known = {event["venue_name"] for event in payload["events"]}
        assert set(venue_names) <= known

    def test_featured_single_page_has_no_pager(self):
        event = build_site.merge_members(
            [make_member("articket", occurrences=["2026-10-18"], date_start="2026-10-18")],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        html = build_site.render_featured([event], SNAPSHOT_TODAY)
        assert "featured__grid--single" in html
        assert "featured__foot" not in html
        assert "featured-page-count" not in html

    def test_featured_prefers_a_poster_ticket_and_a_bigger_show(self):
        plain = build_site.merge_members(
            [
                make_member(
                    "articket",
                    occurrences=["2026-10-17"],
                    date_start="2026-10-17",
                )
            ],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        strong = build_site.merge_members(
            [
                make_member(
                    "articket",
                    source_event_id="articket-2",
                    occurrences=["2026-10-17"],
                    date_start="2026-10-17",
                    image_url="https://x/p.jpg",
                    ticket_url="https://x/t",
                    price_min=60000.0,
                )
            ],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        picked = build_site.pick_featured([plain, strong], SNAPSHOT_TODAY)
        assert picked[0]["slug"] == strong["slug"]

    def test_featured_keeps_one_event_per_venue_when_it_can(self):
        events = [
            build_site.merge_members(
                [make_member("articket", source_event_id=f"articket-{index}", venue_name=venue)],
                empty_index(),
                SNAPSHOT_TODAY,
            )
            for index, venue in enumerate(["Club TRI", "Club TRI", "Teatro Colón", "Vorterix"])
        ]
        picked = build_site.pick_featured(events, SNAPSHOT_TODAY, limit=2)
        assert len(picked) == 2
        assert len({event["venue_id"] for event in picked}) == 2

    def test_featured_is_absent_when_the_weekend_is_empty(self):
        event = build_site.merge_members(
            [make_member("articket", occurrences=["2026-11-20"], date_start="2026-11-20")],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        assert build_site.pick_featured([event], SNAPSHOT_TODAY) == []
        assert build_site.render_featured([], SNAPSHOT_TODAY) == ""

    def test_featured_ignores_events_outside_the_horizon(self):
        near = build_site.merge_members(
            [make_member("articket", occurrences=["2026-10-18"], date_start="2026-10-18")],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        far = build_site.merge_members(
            [
                make_member(
                    "articket",
                    source_event_id="articket-far",
                    occurrences=["2026-12-18"],
                    date_start="2026-12-18",
                )
            ],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        assert [event["slug"] for event in build_site.pick_featured([near, far], SNAPSHOT_TODAY)] == [near["slug"]]

    def test_intro_adapts_when_the_weekend_is_empty(self):
        empty_intro = build_site.render_intro([], SNAPSHOT_TODAY)
        assert "Próximos eventos" in empty_intro
        assert "este finde" not in empty_intro

        event = build_site.merge_members(
            [make_member("articket", occurrences=["2026-10-16"], date_start="2026-10-16")],
            empty_index(),
            SNAPSHOT_TODAY,
        )
        weekend_intro = build_site.render_intro([event], SNAPSHOT_TODAY)
        assert "este finde" in weekend_intro

    def test_empty_dataset_still_explains_the_page(self):
        page = build_site.render_index([], {}, SNAPSHOT_TODAY)
        assert "No hay eventos cargados todavía." in page
        assert 'id="empty-state">' in page

    def test_hidden_rows_have_a_display_rule(self, tmp_path):
        # .row sets display:grid, which would override the hidden attribute.
        _, _, css, _, _ = self.build(tmp_path)
        assert ".row[hidden]" in css
        assert ".daygroup[hidden]" in css
        assert ".featured[hidden]" in css
        assert ".sala-drawer[hidden]" in css
        assert ".sala-option[hidden]" in css
        assert ".featured__page[hidden]" in css

    def test_inlined_payload_is_parseable(self, tmp_path):
        stats, _, _, _, payload = self.build(tmp_path)
        assert payload["today"] == BUILD_TODAY.isoformat()
        assert payload["site"]["name"] == "Cartelera MDP"
        start, end = build_site.weekend_window(BUILD_TODAY)
        assert payload["windows"]["weekend"] == {"start": start.isoformat(), "end": end.isoformat()}
        assert len(payload["events"]) == stats["upcoming"]
        first = payload["events"][0]
        for field in ("id", "title", "venue_id", "dates", "is_free", "price_label"):
            assert field in first


TICKET_ONLINE_LABEL = "Solo con entrada online"
TICKET_STORAGE_KEY = "cartelera-ticket-only"


class TestTicketOnlyFilter:
    """S3: a chip isolates the events that have a purchase link.

    Filtering stays client-side like the rest of the bar, so the build keeps
    every row and only marks it; the browser decides whether to show it.
    """

    def build(self, tmp_path):
        stats = build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=BUILD_TODAY)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        css = (tmp_path / "assets" / "style.css").read_text(encoding="utf-8")
        app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")
        payload = json.loads(DATA_RE.search(html).group(1))
        return stats, html, css, app_js, payload

    def filterbar(self, html):
        return html.split('class="filterbar"', 1)[1].split('id="filter-count"', 1)[0]

    def test_ticket_chip_is_a_chip_in_the_existing_filter_bar(self, tmp_path):
        _, html, _, _, _ = self.build(tmp_path)
        bar = self.filterbar(html)
        chip = re.search(
            r'<button type="button" class="fchip fchip--ticket" id="filter-ticket" '
            r'data-filter="ticket" aria-pressed="false">(.*?)</button>',
            bar,
        )
        assert chip, "the ticket toggle must reuse the fchip button pattern"
        assert TICKET_ONLINE_LABEL in chip.group(1)
        # Sits with gratis and the venues, not in a separate panel.
        assert bar.index('id="filter-free"') < bar.index('id="filter-ticket"')
        assert bar.index('id="filter-ticket"') < bar.index('class="filterbar__venues"')

    def test_ticket_chip_counts_the_events_with_a_purchase_link(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        with_ticket = [event for event in payload["events"] if event["ticket_url"]]
        assert with_ticket
        assert len(with_ticket) < len(payload["events"])
        chip = self.filterbar(html).split('id="filter-ticket"', 1)[1]
        assert re.search(r"<em>(\d+)</em>", chip).group(1) == str(len(with_ticket))

    def test_payload_carries_no_unused_ticket_flag(self, tmp_path):
        # D2: the toggle reads the row's data-ticket, so a payload boolean
        # nobody read was dead weight in every build.
        _, _, _, _, payload = self.build(tmp_path)
        filter_js = (tmp_path / "assets" / "filter.js").read_text(encoding="utf-8")
        for event in payload["events"]:
            assert "has_ticket" not in event
        assert "row.dataset.ticket" in filter_js

    def test_every_row_carries_the_ticket_flag_of_its_event(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        flags = {event["id"]: bool(event["ticket_url"]) for event in payload["events"]}
        rows = re.findall(r'<article class="row" data-row data-id="([^"]+)"([^>]*)>', html)
        assert rows
        for event_id, attrs in rows:
            flag = re.search(r'data-ticket="([01])"', attrs)
            assert flag, f"row {event_id} has no ticket flag"
            assert flag.group(1) == ("1" if flags[event_id] else "0")
        assert any(flags.values()) and not all(flags.values())

    def test_toggle_extends_the_single_filter_path(self, tmp_path):
        _, _, _, app_js, _ = self.build(tmp_path)
        filter_js = (tmp_path / "assets" / "filter.js").read_text(encoding="utf-8")
        assert 'getElementById("filter-ticket")' in app_js
        # The predicate lives in the shared module -- which the page loads and
        # Node can require -- and is not duplicated in the script.
        assert "row.dataset.ticket" in filter_js
        assert "row.dataset.ticket" not in app_js
        assert "function matchesFilters" not in app_js
        assert "CarteleraFilter" in app_js
        assert "module.exports" in filter_js
        # The day badges and the count recalculate through the same predicate.
        tab_counts = app_js.split("function updateTabCounts", 1)[1].split("\n  }", 1)[0]
        assert "matches(row)" in tab_counts
        assert "inView(row, view)" in tab_counts
        # The toggle counts as a filter, so the existing auto-switch/empty
        # state logic engages instead of leaving a dead day tab.
        assert "state.ticket" in app_js.split("function activeFilters", 1)[1].split("\n  }", 1)[0]

    def test_toggle_is_remembered_and_announced(self, tmp_path):
        _, _, _, app_js, _ = self.build(tmp_path)
        assert f'var TICKET_KEY = "{TICKET_STORAGE_KEY}"' in app_js
        assert "localStorage.getItem(TICKET_KEY)" in app_js
        assert "localStorage.setItem(TICKET_KEY" in app_js
        assert "ticket: storedTicketOnly()" in app_js
        sync = app_js.split("function syncControls", 1)[1].split("\n  }", 1)[0]
        assert 'ticketButton.setAttribute("aria-pressed", String(state.ticket))' in sync
        assert 'ticketButton.classList.toggle("is-on", state.ticket)' in sync

    def test_ticket_chip_styles_reuse_the_chip_variant(self, tmp_path):
        _, _, css, _, _ = self.build(tmp_path)
        assert ".fchip--ticket" in css
        assert ".fchip--ticket.is-on" in css

    def test_clear_filters_turns_the_toggle_off(self, tmp_path):
        _, _, _, app_js, _ = self.build(tmp_path)
        reset = app_js.split("function resetFilters", 1)[1].split("\n  }", 1)[0]
        assert "state.ticket = false" in reset
        assert "persistTicketOnly(false)" in reset
        # The empty state is the one filters already use.
        assert "emptyState.hidden = visible !== 0" in app_js

    def test_existing_chips_still_share_the_bar_with_the_new_toggle(self, tmp_path):
        # PRESERVE: gratis and the venue chips keep their markup and counts.
        _, html, _, _, _ = self.build(tmp_path)
        bar = self.filterbar(html)
        assert re.search(
            r'class="fchip fchip--free" id="filter-free" data-filter="free" '
            r'aria-pressed="false">Gratis <em>\d+</em>',
            bar,
        )
        assert len(re.findall(r'class="fchip" data-venue=', bar)) == 6
        assert 'id="sala-toggle"' in bar


class TestWave2Sources:
    def test_new_sources_have_labels(self):
        assert build_site.SOURCE_LABELS["auditorium"] == "Auditorium"
        assert build_site.SOURCE_LABELS["colon"] == "Teatro Colón"
        assert build_site.SOURCE_LABELS["tuentrada"] == "TuEntrada"

    def test_new_source_priority(self):
        order = build_site.SOURCE_ORDER
        assert order.index("tuentrada") < order.index("auditorium")
        assert order.index("auditorium") < order.index("punto")
        assert order.index("colon") < order.index("punto")
        assert order.index("punto") < order.index("municipal")
