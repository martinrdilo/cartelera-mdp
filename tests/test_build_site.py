"""Tests for the static site generator: windows, merge rule, prices, build.

The integration test builds from the committed data/ snapshot (pipeline run
2026-10-13) with --today 2026-10-14, so the expected counts are fixed.
"""

import json
import re
from datetime import date
from pathlib import Path

import build_site

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
SNAPSHOT_TODAY = date(2026, 10, 14)
JSON_LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.DOTALL)


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

    def test_free_when_any_member_is_free(self):
        members = self.cluster() + [make_member("municipal", is_free=True, source_event_id="extra")]
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


class TestEscaping:
    def test_quotes_and_accents_are_escaped(self):
        member = make_member(
            "articket",
            title='Rock & Roll "en vivo" <script>alert(1)</script>',
            venue_name="Café Sábado",
        )
        event = build_site.merge_members([member], empty_index(), SNAPSHOT_TODAY)
        card = build_site.render_card(event, "all")
        assert "&amp;" in card
        assert "&quot;" in card
        assert "<script>alert(1)</script>" not in card
        assert "Café Sábado" in card

    def test_format_when_shortens_long_date_lists(self):
        label = build_site.format_when(["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"], "21:00")
        assert label == "Jue 15/10, Vie 16/10, Sáb 17/10 · 21:00 · +2 fechas"

    def test_format_when_single_date(self):
        assert build_site.format_when(["2026-10-15"], "21:00") == "Jue 15/10 · 21:00"


class TestDeterministicBuild:
    """Full build from the committed snapshot into a tmp dir."""

    def build(self, tmp_path):
        stats = build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=SNAPSHOT_TODAY)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        return stats, html

    def test_files_written(self, tmp_path):
        stats, _ = self.build(tmp_path)
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "assets" / "style.css").exists()
        assert (tmp_path / "favicon.svg").exists()
        assert stats["files"] == ["index.html", "assets/style.css", "favicon.svg"]

    def test_counts_match_the_snapshot(self, tmp_path):
        stats, html = self.build(tmp_path)
        assert stats["today"] == "2026-10-14"
        assert stats["upcoming"] == 145  # 41 merged clusters + 104 upcoming singles
        assert stats["weekend"] == 27
        assert html.count('data-card-scope="all"') == 145
        assert html.count('data-card-scope="weekend"') == 27

    def test_hero_and_footer_copy(self, tmp_path):
        _, html = self.build(tmp_path)
        assert "Este finde" in html
        assert "Jue 15/10 – Dom 18/10 · 27 shows" in html
        assert "Datos: agenda municipal EMTUR, Articket, CultuTickets, Club TRI." in html
        assert "Actualizado: 13/10/2026 21:14" in html

    def test_past_event_is_dropped(self, tmp_path):
        _, html = self.build(tmp_path)
        assert "Que Viva España" not in html

    def test_singles_from_normalized_are_included(self, tmp_path):
        # The deduped file only exports clusters; singles must come from normalized.
        _, html = self.build(tmp_path)
        assert "EL FUTURO IMPOSIBLE - PROYECCIÓN + CONVERSACIÓN" in html

    def test_known_ticket_url_is_linked(self, tmp_path):
        _, html = self.build(tmp_path)
        assert 'href="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"' in html
        assert html.count('data-outbound="ticket"') > 0
        assert html.count('target="_blank" rel="noopener"') == html.count('data-outbound="ticket"')

    def test_json_ld_is_parseable_and_lists_the_weekend(self, tmp_path):
        _, html = self.build(tmp_path)
        match = JSON_LD_RE.search(html)
        assert match, "JSON-LD script not found"
        payload = json.loads(match.group(1))
        assert payload[0]["@type"] == "WebSite"
        assert payload[1]["@type"] == "ItemList"
        items = payload[1]["itemListElement"]
        assert len(items) == 27
        first = items[0]["item"]
        assert first["@type"] == "Event"
        assert first["name"]
        assert first["startDate"].startswith("2026-10-")
        assert first["location"]["name"]
