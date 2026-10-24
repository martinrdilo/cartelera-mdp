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
# Integration builds use the latest committed snapshot (pipeline run Oct 22).
BUILD_TODAY = date(2026, 10, 22)
JSON_LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.DOTALL)
DATA_RE = re.compile(r'<script id="events-data" type="application/json">(.*?)</script>', re.DOTALL)


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

    def test_same_title_different_session_stays_two_rows(self):
        left = self.site_event("Dillom", "bendu", ["2027-01-30"])
        right = self.site_event("Dillom", "bendu", ["2027-01-31"])
        assert len(build_site.collapse_exact_duplicates([left, right])) == 2

    def test_same_title_different_venue_stays_two_rows(self):
        left = self.site_event("Dillom", "bendu", ["2027-01-30"])
        right = self.site_event("Dillom", "arena", ["2027-01-30"])
        assert len(build_site.collapse_exact_duplicates([left, right])) == 2

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


class TestDeterministicBuild:
    """Full build from the committed snapshot into a tmp dir."""

    def build(self, tmp_path):
        stats = build_site.build(data_dir=DATA_DIR, out_dir=tmp_path, today=BUILD_TODAY)
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        return stats, html

    def test_files_written(self, tmp_path):
        stats, _ = self.build(tmp_path)
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "assets" / "style.css").exists()
        assert (tmp_path / "assets" / "app.js").exists()
        assert (tmp_path / "favicon.svg").exists()
        assert stats["files"] == ["index.html", "assets/style.css", "assets/app.js", "favicon.svg"]

    def test_counts_match_the_snapshot(self, tmp_path):
        stats, html = self.build(tmp_path)
        rows = html.count("<article class=\"row\"")
        assert stats["today"] == "2026-10-22"
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
        assert "Jueves 22 — Domingo 25 · Octubre 2026" in html
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

    def test_known_ticket_url_is_linked(self, tmp_path):
        _, html = self.build(tmp_path)
        assert 'href="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI/"' in html
        assert html.count('data-outbound="ticket"') > 0
        assert html.count('target="_blank" rel="noopener"') >= html.count('data-outbound="ticket"')

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
        assert first["startDate"].startswith("2026-10-")
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
        stats, html, _, _, _ = self.build(tmp_path)
        assert 'class="daynav"' in html
        day_nav = html.split('aria-label="Filtrar por día">', 1)[1].split("</nav>", 1)[0]
        assert 'data-view="weekend"' in day_nav
        assert 'data-view="2026-10-22"' in day_nav
        assert 'data-view="2026-10-25"' in day_nav
        assert 'data-view="next-weekend"' in day_nav
        assert 'data-view="all"' in day_nav
        assert day_nav.count("data-view=") == 7
        # The finde view is the default when the weekend has events.
        assert stats["weekend"] > 0
        assert re.search(r'class="day is-on" data-view="weekend"', html)

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
        assert int(tabs["next-weekend"]) == expected_next

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
        assert featured_cards == 3
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

    def test_search_and_filter_controls(self, tmp_path):
        _, html, _, app_js, _ = self.build(tmp_path)
        assert 'id="search"' in html
        assert 'data-filter="free"' in html
        assert 'data-filter="venue"' in html
        assert 'id="filter-count"' in html
        assert 'id="empty-state"' in html
        assert 'id="clear-filters"' in html
        assert "No hay eventos con esos filtros" in html
        for hook in ("filter_change", "auto-todo", "outbound_ticket", "share_whatsapp"):
            assert hook in app_js

    def test_venue_chips_are_the_three_busiest_venues(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        expected = build_site.top_venues(payload["events"], 3)
        chips = re.findall(r'class="chip" data-filter="venue" data-value="([^"]+)"', html)
        assert chips == [venue_id for _, venue_id, _ in expected]
        assert len(chips) == 3

    def test_featured_board_uses_three_events_from_distinct_venues(self, tmp_path):
        _, html, _, _, payload = self.build(tmp_path)
        venue_names = re.findall(
            r'<article class="feature feature--(?:lead|mini)"[^>]*data-feature="1"[^>]*data-venue-name="([^"]+)"',
            html,
        )
        assert len(venue_names) == 3
        assert len(set(venue_names)) == 3
        assert 'id="featured-title">Destacados<' in html
        known = {event["venue_name"] for event in payload["events"]}
        assert set(venue_names) <= known

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

    def test_inlined_payload_is_parseable(self, tmp_path):
        stats, _, _, _, payload = self.build(tmp_path)
        assert payload["today"] == "2026-10-22"
        assert payload["site"]["name"] == "Cartelera MDP"
        assert payload["windows"]["weekend"] == {"start": "2026-10-22", "end": "2026-10-25"}
        assert len(payload["events"]) == stats["upcoming"]
        first = payload["events"][0]
        for field in ("id", "title", "venue_id", "dates", "is_free", "price_label"):
            assert field in first


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
